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
    c = (200, 220, 255, 255)
    lw = max(int(2 * s), 1)
    draw.rectangle([cx - int(12*s), cy - lw, cx + int(12*s), cy + lw], fill=c)
    draw.rectangle([cx - lw, cy - int(12*s), cx + lw, cy + int(12*s)], fill=c)
    cr = int(8 * s)
    draw.ellipse([cx-cr, cy-cr, cx+cr, cy+cr], outline=c, width=lw)
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
    def __init__(self, cfg: dict, log: logging.Logger, on_alert=None, on_price_update=None):
        self.cfg = cfg
        self.log = log
        self.on_alert = on_alert or (lambda *a: None)
        self.on_price_update = on_price_update or (lambda *a: None)
        self.client = BuffClient(rate_limit=1.5)
        self._running = False
        self._stop = threading.Event()
        self._prices = {}
        self._last_alert = {}
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

        data = self.client.get_sell_orders(gid)
        listings = parse_sell_items(data)

        if not listings:
            return

        prices = [l["price"] for l in listings]
        lowest = prices[0]
        avg = sum(prices) / len(prices)

        if gid not in self._prices:
            self._prices[gid] = []
        self._prices[gid].append(lowest)
        self._prices[gid] = self._prices[gid][-100:]

        self.log.info(f"[{name}] 最低: ¥{lowest:.2f} 均价: ¥{avg:.2f} 在售: {len(listings)}")
        self.on_price_update(gid, lowest, avg, len(listings))

        now = time.time()
        if now - self._last_alert.get(gid, 0) < 300:
            return

        alerted = False

        if target > 0 and lowest <= target:
            self.on_alert(name, f"🎯 到达目标价！¥{lowest:.2f} ≤ ¥{target:.2f}", lowest)
            alerted = True

        if self.cfg.get("alert_below_avg") and avg > 0:
            pct = (avg - lowest) / avg * 100
            if pct >= self.cfg.get("price_drop_pct", 10):
                self.on_alert(name, f"📉 低于均价 {pct:.0f}%！¥{lowest:.2f} (均价 ¥{avg:.2f})", lowest)
                alerted = True

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
        self._live_prices = {}  # {goods_id: {"lowest": x, "avg": y, "count": z}}
        self._build()

    def _build(self):
        self.win = tk.Tk()
        self.win.title("CS2 Price Watcher — 设置")
        self.win.geometry("680x580")
        self.win.resizable(False, False)
        self.win.configure(bg="#1a1a2e")

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background="#1a1a2e", foreground="#e0e0e0", fieldbackground="#16213e")
        style.configure("TLabel", background="#1a1a2e", foreground="#e0e0e0", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10))
        style.configure("Header.TLabel", font=("Segoe UI", 14, "bold"), foreground="#ff6b6b")
        style.configure("Treeview", background="#16213e", foreground="#e0e0e0",
                        fieldbackground="#16213e", font=("Segoe UI", 9))
        style.configure("Treeview.Heading", background="#0f3460", foreground="#e0e0e0",
                        font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", "#2a5298")])

        pad = {"padx": 16, "pady": 6}

        ttk.Label(self.win, text="🎯 CS2 Price Watcher", style="Header.TLabel").pack(pady=(16, 6))

        # ── 监控列表（带实时价格）──
        frm_list = ttk.LabelFrame(self.win, text="监控列表", padding=8)
        frm_list.pack(fill="both", expand=True, **pad)

        cols = ("名称", "目标价", "当前最低", "在售均价", "在售数")
        self.tree = ttk.Treeview(frm_list, columns=cols, show="headings", height=8)
        widths = (240, 80, 90, 90, 70)
        for c, w in zip(cols, widths):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="center")
        self.tree.column("名称", anchor="w")
        self.tree.pack(fill="both", expand=True)

        self._refresh_list()

        btn_frame = ttk.Frame(frm_list)
        btn_frame.pack(fill="x", pady=(6, 0))
        ttk.Button(btn_frame, text="＋ 添加饰品", command=self._add_item).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="－ 移除选中", command=self._remove_item).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="🔄 刷新价格", command=self._refresh_prices).pack(side="left", padx=2)

        # ── Cookie 配置 ──
        frm_cookie = ttk.LabelFrame(self.win, text="Buff Cookie（可选，启用搜索功能）", padding=8)
        frm_cookie.pack(fill="x", **pad)

        self.var_cookie = tk.StringVar(value=self.cfg.get("buff_cookie", ""))
        cookie_entry = ttk.Entry(frm_cookie, textvariable=self.var_cookie, width=70, show="*")
        cookie_entry.pack(fill="x")
        ttk.Label(frm_cookie, text="从浏览器 F12 → Network → 复制 Cookie，可解锁搜索",
                  font=("Segoe UI", 8), foreground="#888").pack(anchor="w")

        # ── 参数 ──
        frm_params = ttk.LabelFrame(self.win, text="参数", padding=8)
        frm_params.pack(fill="x", **pad)

        row1 = ttk.Frame(frm_params)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="检查间隔：").pack(side="left")
        self.var_poll = tk.IntVar(value=self.cfg["poll_interval"])
        ttk.Entry(row1, textvariable=self.var_poll, width=5).pack(side="left", padx=2)
        ttk.Label(row1, text="秒    跌幅阈值：").pack(side="left")
        self.var_drop = tk.IntVar(value=self.cfg["price_drop_pct"])
        ttk.Entry(row1, textvariable=self.var_drop, width=5).pack(side="left", padx=2)
        ttk.Label(row1, text="%    ").pack(side="left")

        self.var_sound = tk.BooleanVar(value=self.cfg.get("sound_alert", True))
        ttk.Checkbutton(row1, text="声音提醒", variable=self.var_sound).pack(side="left")

        # ── 按钮 ──
        frm_btn = ttk.Frame(self.win)
        frm_btn.pack(pady=(8, 16))
        ttk.Button(frm_btn, text="保存并应用", command=self._save).pack(side="left", padx=8)
        ttk.Button(frm_btn, text="关闭", command=self.win.destroy).pack(side="left", padx=8)

        # 居中
        self.win.update_idletasks()
        w, h = self.win.winfo_width(), self.win.winfo_height()
        x = (self.win.winfo_screenwidth() - w) // 2
        y = (self.win.winfo_screenheight() - h) // 2
        self.win.geometry(f"+{x}+{y}")

    def _refresh_list(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for item in self.cfg["watchlist"]:
            gid = item["goods_id"]
            tp = item.get("target_price", 0)
            target = f"¥{tp:.2f}" if tp and tp > 0 else "—"
            lp = self._live_prices.get(gid, {})
            lowest = f"¥{lp['lowest']:.2f}" if "lowest" in lp else "…"
            avg = f"¥{lp['avg']:.2f}" if "avg" in lp else "…"
            count = str(lp.get("count", "…"))
            self.tree.insert("", "end", values=(item["name"], target, lowest, avg, count))

    def _add_item(self):
        # 有 Cookie 时用搜索，没有时用粘贴链接
        cookie = self.var_cookie.get().strip()
        if cookie:
            self._add_by_search()
        else:
            self._add_by_url()

    def _add_by_search(self):
        keyword = simpledialog.askstring("搜索饰品", "输入饰品名称：", parent=self.win)
        if not keyword:
            return
        try:
            client = BuffClient()
            client.set_cookies(self.var_cookie.get().strip())
            data = client.search(keyword)
            items = data.get("items", [])
            if not items:
                messagebox.showinfo("结果", "未找到饰品")
                return
            # 弹出选择列表
            choices = [f"{i['name']}  ¥{i.get('sell_min_price', '?')}" for i in items[:15]]
            choice = self._pick_from_list("选择饰品", choices)
            if choice is None:
                return
            selected = items[choice]
            self._confirm_add(selected["id"], selected["name"], float(selected.get("sell_min_price", 0)))
        except Exception as e:
            messagebox.showerror("错误", str(e))

    def _add_by_url(self):
        url = simpledialog.askstring("添加饰品",
            "粘贴 Buff 链接或 goods_id：\n"
            "例: https://buff.163.com/goods/773635 或 773635",
            parent=self.win)
        if not url:
            return
        goods_id = self._parse_goods_id(url)
        if not goods_id:
            messagebox.showerror("错误", "无法解析，请输入 Buff 链接或数字 ID")
            return
        try:
            client = BuffClient()
            info = client.get_goods_info(goods_id)
            name = info.get("name", f"#{goods_id}")
            min_price = float(info.get("sell_min_price", 0))
            self._confirm_add(goods_id, name, min_price)
        except Exception as e:
            messagebox.showerror("错误", str(e))

    def _confirm_add(self, goods_id, name, current_price):
        target = simpledialog.askfloat("目标价格",
            f"{name}\n当前最低: ¥{current_price:.2f}\n\n低于此价格时提醒（0=不限）：",
            parent=self.win, minvalue=0)
        config.add_watch(self.cfg, goods_id, name, target or 0)
        self._refresh_list()

    def _pick_from_list(self, title, choices):
        dlg = tk.Toplevel(self.win)
        dlg.title(title)
        dlg.geometry("500x350")
        dlg.configure(bg="#1a1a2e")
        dlg.transient(self.win)
        dlg.grab_set()
        result = [None]
        lb = tk.Listbox(dlg, bg="#16213e", fg="#e0e0e0", selectbackground="#2a5298",
                        font=("Segoe UI", 10))
        lb.pack(fill="both", expand=True, padx=10, pady=10)
        for c in choices:
            lb.insert(tk.END, c)
        def confirm():
            sel = lb.curselection()
            if sel:
                result[0] = sel[0]
            dlg.destroy()
        ttk.Button(dlg, text="确定", command=confirm).pack(pady=(0, 10))
        lb.bind("<Double-Button-1>", lambda e: confirm())
        dlg.wait_window()
        return result[0]

    def _parse_goods_id(self, text):
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

    def _refresh_prices(self):
        """后台刷新所有饰品的当前价格"""
        def do_refresh():
            client = BuffClient(rate_limit=1.5)
            for item in self.cfg["watchlist"]:
                try:
                    data = client.get_sell_orders(item["goods_id"])
                    listings = parse_sell_items(data)
                    if listings:
                        prices = [l["price"] for l in listings]
                        self._live_prices[item["goods_id"]] = {
                            "lowest": prices[0],
                            "avg": sum(prices) / len(prices),
                            "count": len(prices),
                        }
                except Exception:
                    pass
            # 回到主线程刷新 UI
            self.win.after(0, self._refresh_list)
        threading.Thread(target=do_refresh, daemon=True).start()

    def _save(self):
        self.cfg["poll_interval"] = max(5, self.var_poll.get())
        self.cfg["price_drop_pct"] = max(1, self.var_drop.get())
        self.cfg["sound_alert"] = self.var_sound.get()
        self.cfg["buff_cookie"] = self.var_cookie.get().strip()
        config.save(self.cfg)
        if self.on_save:
            self.on_save(self.cfg)
        messagebox.showinfo("已保存", "配置已保存，监控已重启")


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

    def _on_alert(self, name, msg, price):
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
        if self.icon and hasattr(self.icon, 'notify'):
            try:
                self.icon.notify(f"{name}\n{msg}", "CS2 价格提醒")
            except Exception:
                pass

    def _on_price_update(self, goods_id, lowest, avg, count):
        """价格更新回调（托盘 tooltip 更新）"""
        if self.watcher:
            wl = self.cfg.get("watchlist", [])
            name = next((w["name"] for w in wl if w["goods_id"] == goods_id), "")
            # 只更新 tooltip，不频繁刷新图标
            if self.icon:
                self.icon.title = f"监控中 | {name}: ¥{lowest:.2f}"

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
        # 设置 Cookie
        self.watcher = PriceWatcher(
            self.cfg, self.log,
            on_alert=self._on_alert,
            on_price_update=self._on_price_update,
        )
        cookie = self.cfg.get("buff_cookie", "")
        if cookie:
            self.watcher.client.set_cookies(cookie)
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
