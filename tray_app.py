"""
CS2 Price Watcher — 系统托盘应用
=================================
监控 Buff 饰品价格，低价/异动时提醒。
"""

import sys
import os
import re

if sys.platform == "win32":
    try:
        import ctypes
        _hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if _hwnd:
            ctypes.windll.user32.ShowWindow(_hwnd, 0)
    except Exception:
        pass

import time
import threading
import logging
import winsound
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from pathlib import Path
from typing import Optional

import pystray
from PIL import Image, ImageDraw

import config
from buff_api import BuffClient, parse_sell_items

APPDATA_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / config.APP_NAME
LOCK_FILE = APPDATA_DIR / ".lock"
SIGNAL_FILE = APPDATA_DIR / ".show_settings"

# ──────────────────────────────────────────────
#  图标
# ──────────────────────────────────────────────

def create_icon(size=64, has_alert=False):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx, cy = size // 2, size // 2
    s = size / 64
    r = int(28 * s)
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(30, 50, 90, 255))

    # 瞄准镜/准星
    c = (200, 220, 255, 255)
    lw = max(int(2 * s), 1)
    # 十字
    draw.rectangle([cx - int(12*s), cy - lw, cx + int(12*s), cy + lw], fill=c)
    draw.rectangle([cx - lw, cy - int(12*s), cx + lw, cy + int(12*s)], fill=c)
    # 圆
    cr = int(8 * s)
    draw.ellipse([cx-cr, cy-cr, cx+cr, cy+cr], outline=c, width=lw)
    # 中心点
    dr = int(2 * s)
    draw.ellipse([cx-dr, cy-dr, cx+dr, cy+dr], fill=(255, 80, 80, 255) if has_alert else c)

    if has_alert:
        dot_r = int(6 * s)
        dx, dy = cx + int(18*s), cy - int(18*s)
        draw.ellipse([dx-dot_r, dy-dot_r, dx+dot_r, dy+dot_r], fill=(255, 60, 60, 255))

    return img


# ──────────────────────────────────────────────
#  价格监控引擎
# ──────────────────────────────────────────────

class PriceWatcher:
    def __init__(self, cfg: dict, log: logging.Logger, on_alert=None):
        self.cfg = cfg
        self.log = log
        self.on_alert = on_alert or (lambda *a: None)
        self.client = BuffClient(rate_limit=1.5)
        self._running = False
        self._stop = threading.Event()
        self._prices = {}   # {goods_id: [最近价格列表]}
        self._last_alert = {}  # {goods_id: 上次提醒时间}
        self._thread = None

    def start(self):
        if self._running:
            return
        self._stop.clear()
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._running = False

    def _run(self):
        self.log.info(f"开始监控 {len(self.cfg['watchlist'])} 个饰品")
        while not self._stop.is_set():
            for item in self.cfg["watchlist"]:
                if self._stop.is_set():
                    break
                try:
                    self._check_item(item)
                except Exception as e:
                    self.log.error(f"检查 {item['name']} 失败: {e}")

            for _ in range(int(self.cfg["poll_interval"] * 10)):
                if self._stop.is_set():
                    break
                time.sleep(0.1)

    def _check_item(self, item: dict):
        gid = item["goods_id"]
        name = item["name"]
        target = item.get("target_price", 0)

        # 获取在售列表
        data = self.client.get_sell_orders(gid)
        listings = parse_sell_items(data)

        if not listings:
            return

        prices = [l["price"] for l in listings]
        lowest = prices[0]
        avg = sum(prices) / len(prices)

        # 记录价格历史
        if gid not in self._prices:
            self._prices[gid] = []
        self._prices[gid].append(lowest)
        self._prices[gid] = self._prices[gid][-100:]

        self.log.info(f"[{name}] 最低: ¥{lowest:.2f} 均价: ¥{avg:.2f} 在售: {len(listings)}")

        # 冷却检查：同一个饰品 5 分钟内不重复提醒
        now = time.time()
        if now - self._last_alert.get(gid, 0) < 300:
            return

        alerted = False

        # 检查 1: 目标价
        if target > 0 and lowest <= target:
            self.on_alert(name, f"🎯 到达目标价！¥{lowest:.2f} ≤ ¥{target:.2f}", lowest)
            alerted = True

        # 检查 2: 低于均价
        if self.cfg.get("alert_below_avg") and avg > 0:
            pct = (avg - lowest) / avg * 100
            if pct >= self.cfg.get("price_drop_pct", 10):
                self.on_alert(name, f"📉 低于均价 {pct:.0f}%！¥{lowest:.2f} (均价 ¥{avg:.2f})", lowest)
                alerted = True

        # 检查 3: 近期价格跌幅
        history = self._prices.get(gid, [])
        if len(history) >= 5:
            recent_avg = sum(history[-5:]) / 5
            if recent_avg > 0:
                drop = (recent_avg - lowest) / recent_avg * 100
                if drop >= self.cfg.get("price_drop_pct", 10):
                    self.on_alert(name, f"⚠️ 近期跌 {drop:.0f}%！¥{lowest:.2f} (5次均 ¥{recent_avg:.2f})", lowest)
                    alerted = True

        if alerted:
            self._last_alert[gid] = now


# ──────────────────────────────────────────────
#  设置窗口
# ──────────────────────────────────────────────

class SettingsDialog:
    def __init__(self, cfg: dict, watcher: PriceWatcher = None, on_save=None):
        self.cfg = cfg
        self.watcher = watcher
        self.on_save = on_save
        self._build()

    def _build(self):
        self.win = tk.Tk()
        self.win.title("CS2 Price Watcher — 设置")
        self.win.geometry("600x500")
        self.win.resizable(False, False)
        self.win.configure(bg="#1a1a2e")

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background="#1a1a2e", foreground="#e0e0e0", fieldbackground="#16213e")
        style.configure("TLabel", background="#1a1a2e", foreground="#e0e0e0", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10))
        style.configure("Header.TLabel", font=("Segoe UI", 14, "bold"), foreground="#ff6b6b")

        pad = {"padx": 16, "pady": 6}

        ttk.Label(self.win, text="🎯 CS2 Price Watcher", style="Header.TLabel").pack(pady=(16, 6))

        # ── 监控列表 ──
        frm_list = ttk.LabelFrame(self.win, text="监控列表", padding=8)
        frm_list.pack(fill="both", expand=True, **pad)

        cols = ("名称", "目标价", "当前最低")
        self.tree = ttk.Treeview(frm_list, columns=cols, show="headings", height=8)
        for c in cols:
            self.tree.heading(c, text=c)
        self.tree.column("名称", width=300)
        self.tree.column("目标价", width=100, anchor="center")
        self.tree.column("当前最低", width=100, anchor="center")
        self.tree.pack(fill="both", expand=True)

        self._refresh_list()

        btn_frame = ttk.Frame(frm_list)
        btn_frame.pack(fill="x", pady=(6, 0))
        ttk.Button(btn_frame, text="＋ 搜索添加", command=self._add_item).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="－ 移除选中", command=self._remove_item).pack(side="left", padx=2)

        # ── 参数 ──
        frm_params = ttk.Frame(self.win)
        frm_params.pack(fill="x", **pad)

        row1 = ttk.Frame(frm_params)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="检查间隔：").pack(side="left")
        self.var_poll = tk.IntVar(value=self.cfg["poll_interval"])
        ttk.Entry(row1, textvariable=self.var_poll, width=5).pack(side="left", padx=2)
        ttk.Label(row1, text="秒    价格跌幅阈值：").pack(side="left")
        self.var_drop = tk.IntVar(value=self.cfg["price_drop_pct"])
        ttk.Entry(row1, textvariable=self.var_drop, width=5).pack(side="left", padx=2)
        ttk.Label(row1, text="%").pack(side="left")

        self.var_sound = tk.BooleanVar(value=self.cfg.get("sound_alert", True))
        ttk.Checkbutton(frm_params, text="声音提醒", variable=self.var_sound).pack(anchor="w", pady=4)

        # ── 按钮 ──
        frm_btn = ttk.Frame(self.win)
        frm_btn.pack(pady=(8, 16))
        ttk.Button(frm_btn, text="保存", command=self._save).pack(side="left", padx=8)
        ttk.Button(frm_btn, text="关闭", command=self.win.destroy).pack(side="left", padx=8)

        self.win.update_idletasks()
        w, h = self.win.winfo_width(), self.win.winfo_height()
        x = (self.win.winfo_screenwidth() - w) // 2
        y = (self.win.winfo_screenheight() - h) // 2
        self.win.geometry(f"+{x}+{y}")

    def _refresh_list(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for item in self.cfg["watchlist"]:
            tp = item.get("target_price", 0)
            target = f"¥{tp:.2f}" if tp and tp > 0 else "—"
            self.tree.insert("", "end", values=(item["name"], target, ""))

    def _add_item(self):
        url = simpledialog.askstring("添加饰品",
            "粘贴 Buff 链接或 goods_id：\n"
            "例: https://buff.163.com/goods/773635 或 773635",
            parent=self.win)
        if not url:
            return

        # 解析 goods_id
        goods_id = self._parse_goods_id(url)
        if not goods_id:
            messagebox.showerror("错误", "无法解析，请输入 Buff 链接或数字 ID")
            return

        try:
            from buff_api import BuffClient
            client = BuffClient()
            info = client.get_goods_info(goods_id)
            name = info.get("name", f"#{goods_id}")
            min_price = float(info.get("sell_min_price", 0))

            target = simpledialog.askfloat("目标价格",
                f"{name}\n当前最低: ¥{min_price:.2f}\n\n低于此价格时提醒（0=不限）：",
                parent=self.win, minvalue=0)

            config.add_watch(self.cfg, goods_id, name, target or 0)
            self._refresh_list()
        except Exception as e:
            messagebox.showerror("错误", str(e))

    def _parse_goods_id(self, text: str) -> Optional[int]:
        """从 Buff URL 或纯数字解析 goods_id"""
        text = text.strip()
        if text.isdigit():
            return int(text)
        m = re.search(r'/goods/(\d+)', text)
        if m:
            return int(m.group(1))
        return None

    def _remove_item(self):
        sel = self.tree.selection()
        if not sel:
            return
        idx = self.tree.index(sel[0])
        item = self.cfg["watchlist"][idx]
        config.remove_watch(self.cfg, item["goods_id"])
        self._refresh_list()

    def _save(self):
        self.cfg["poll_interval"] = max(5, self.var_poll.get())
        self.cfg["price_drop_pct"] = max(1, self.var_drop.get())
        self.cfg["sound_alert"] = self.var_sound.get()
        config.save(self.cfg)
        if self.on_save:
            self.on_save(self.cfg)
        messagebox.showinfo("已保存", "配置已保存")


# ──────────────────────────────────────────────
#  系统托盘
# ──────────────────────────────────────────────

class TrayApp:
    def __init__(self):
        self.cfg = config.load()
        self.log = self._setup_logging()
        self.watcher = None
        self.icon = None
        self._status = "就绪"
        self._has_alert = False

    def _setup_logging(self):
        log = logging.getLogger("cs2_watcher")
        log.setLevel(logging.INFO)
        log.handlers.clear()
        fmt = logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S")
        log_path = APPDATA_DIR / "watcher.log"
        APPDATA_DIR.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(fmt)
        log.addHandler(fh)
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        log.addHandler(ch)
        return log

    def _on_alert(self, name: str, msg: str, price: float):
        """价格异动回调"""
        self.log.warning(f"🔔 [{name}] {msg}")
        self._has_alert = True
        if self.icon:
            self.icon.icon = create_icon(64, has_alert=True)
            self.icon.title = f"⚠️ {name}: ¥{price:.2f}"
        if self.cfg.get("sound_alert"):
            try:
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            except Exception:
                pass
        # Windows 通知
        if self.icon and hasattr(self.icon, 'notify'):
            try:
                self.icon.notify(f"{name}\n{msg}", "CS2 价格提醒")
            except Exception:
                pass

    def _create_tray(self):
        img = create_icon(64, has_alert=self._has_alert)
        menu = pystray.Menu(
            pystray.MenuItem(f"状态: {self._status}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("打开设置", self._on_settings),
            pystray.MenuItem("清除提醒", self._clear_alert),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._on_exit),
        )
        self.icon = pystray.Icon("cs2-price-watcher", img, f"CS2 Watcher — {self._status}", menu)

    def _on_settings(self, *a):
        threading.Thread(target=self._show_settings, daemon=True).start()

    def _show_settings(self):
        if self.watcher:
            self.watcher.stop()
        dlg = SettingsDialog(self.cfg, self.watcher, on_save=self._on_saved)
        dlg.win.mainloop()

    def _on_saved(self, new_cfg):
        self.cfg = new_cfg
        self._start_watcher()

    def _clear_alert(self, *a):
        self._has_alert = False
        if self.icon:
            self.icon.icon = create_icon(64, has_alert=False)

    def _on_exit(self, *a):
        if self.watcher:
            self.watcher.stop()
        if self.icon:
            self.icon.stop()

    def _start_watcher(self):
        self.watcher = PriceWatcher(self.cfg, self.log, on_alert=self._on_alert)
        self.watcher.start()
        self._status = f"监控中 ({len(self.cfg['watchlist'])} 个)"

    def _watch_signal(self):
        while True:
            time.sleep(1)
            if SIGNAL_FILE.exists():
                try:
                    SIGNAL_FILE.unlink()
                except OSError:
                    pass
                self._on_settings()

    def run(self):
        if not self.cfg["watchlist"]:
            self.log.info("首次运行，打开设置")
            dlg = SettingsDialog(self.cfg, on_save=self._on_saved)
            dlg.win.mainloop()
        else:
            self._start_watcher()

        threading.Thread(target=self._watch_signal, daemon=True).start()
        self._create_tray()
        self.icon.run()


# ──────────────────────────────────────────────
#  入口
# ──────────────────────────────────────────────

if __name__ == "__main__":
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    if LOCK_FILE.exists():
        try:
            old_pid = int(LOCK_FILE.read_text().strip())
            os.kill(old_pid, 0)
            SIGNAL_FILE.write_text("open")
            sys.exit(0)
        except (ValueError, OSError, ProcessLookupError):
            LOCK_FILE.unlink(missing_ok=True)

    LOCK_FILE.write_text(str(os.getpid()))
    import atexit
    atexit.register(lambda: LOCK_FILE.unlink(missing_ok=True))

    try:
        app = TrayApp()
        app.run()
    except Exception as e:
        logging.exception(f"Fatal: {e}")
        sys.exit(1)
