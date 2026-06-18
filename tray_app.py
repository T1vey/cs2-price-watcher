"""
CS2 Price Watcher — 系统托盘应用
监控 Buff + 悠悠有品 饰品价格，低价/异动时提醒。
"""

import sys, os, re, time, threading, logging, winsound
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from pathlib import Path
from typing import Optional

if sys.platform == "win32":
    try:
        import ctypes
        _h = ctypes.windll.kernel32.GetConsoleWindow()
        if _h: ctypes.windll.user32.ShowWindow(_h, 0)
    except: pass

import pystray
from PIL import Image, ImageDraw

import config
from buff_api import BuffClient, parse_sell_items
from youpin_api import YoupinClient

APPDATA_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / config.APP_NAME
LOCK_FILE = APPDATA_DIR / ".lock"
SIGNAL_FILE = APPDATA_DIR / ".show_settings"


def create_icon(size=64, has_alert=False):
    img = Image.new("RGBA", (size, size), (0,0,0,0))
    draw = ImageDraw.Draw(img)
    cx, cy, s = size//2, size//2, size/64
    r = int(28*s)
    draw.ellipse([cx-r,cy-r,cx+r,cy+r], fill=(30,50,90,255))
    c = (200,220,255,255); lw = max(int(2*s),1)
    draw.rectangle([cx-int(12*s),cy-lw,cx+int(12*s),cy+lw], fill=c)
    draw.rectangle([cx-lw,cy-int(12*s),cx+lw,cy+int(12*s)], fill=c)
    cr = int(8*s)
    draw.ellipse([cx-cr,cy-cr,cx+cr,cy+cr], outline=c, width=lw)
    dr = int(2*s)
    draw.ellipse([cx-dr,cy-dr,cx+dr,cy+dr], fill=(255,80,80,255) if has_alert else c)
    if has_alert:
        dot_r=int(6*s); dx,dy=cx+int(18*s),cy-int(18*s)
        draw.ellipse([dx-dot_r,dy-dot_r,dx+dot_r,dy+dot_r], fill=(255,60,60,255))
    return img


class PriceWatcher:
    def __init__(self, cfg, log, on_alert=None, on_price_update=None):
        self.cfg = cfg; self.log = log
        self.on_alert = on_alert or (lambda *a: None)
        self.on_price_update = on_price_update or (lambda *a: None)
        self.buff = BuffClient(rate_limit=1.5)
        self.youpin = YoupinClient(rate_limit=2.0)
        self._running = False; self._stop = threading.Event()
        self._prices = {}; self._last_alert = {}; self._thread = None

    def start(self):
        if self._running: return
        self._stop.clear(); self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set(); self._running = False

    def _run(self):
        self.log.info(f"开始监控 {len(self.cfg['watchlist'])} 个饰品")
        while not self._stop.is_set():
            for item in self.cfg["watchlist"]:
                if self._stop.is_set(): break
                try: self._check(item)
                except Exception as e: self.log.error(f"检查 {item['name']} 失败: {e}")
            for _ in range(int(self.cfg["poll_interval"]*10)):
                if self._stop.is_set(): break
                time.sleep(0.1)

    def _check(self, item):
        src = item.get("source", "buff")
        if src == "youpin": self._check_youpin(item)
        else: self._check_buff(item)

    def _check_buff(self, item):
        data = self.buff.get_sell_orders(item["goods_id"])
        listings = parse_sell_items(data)
        if not listings: return
        prices = [l["price"] for l in listings]
        self._process(item, prices[0], sum(prices)/len(prices), len(prices))

    def _check_youpin(self, item):
        try:
            data = self.youpin.get_commodity_detail(item["goods_id"])
            # 悠悠有品详情返回结构
            lowest = float(data.get("price", 0) or data.get("MinPrice", 0))
            avg = float(data.get("steamPrice", lowest) or data.get("AvgPrice", lowest))
            count = int(data.get("onSaleCount", 0) or data.get("OnSaleCount", 0))
            if lowest > 0: self._process(item, lowest, avg, count)
        except Exception as e:
            self.log.error(f"[{item['name']}] 悠悠有品查询失败: {e}")

    def _process(self, item, lowest, avg, count):
        gid = item["goods_id"]; name = item["name"]; target = item.get("target_price", 0)
        src = "UU" if item.get("source") == "youpin" else "Buff"
        if gid not in self._prices: self._prices[gid] = []
        self._prices[gid].append(lowest)
        self._prices[gid] = self._prices[gid][-100:]
        self.log.info(f"[{name}] ({src}) 最低: ¥{lowest:.2f} 均价: ¥{avg:.2f} 在售: {count}")
        self.on_price_update(gid, lowest, avg, count)
        now = time.time()
        if now - self._last_alert.get(gid, 0) < 300: return
        alerted = False
        if target > 0 and lowest <= target:
            self.on_alert(name, f"🎯 到达目标价！¥{lowest:.2f} ≤ ¥{target:.2f}", lowest); alerted = True
        if self.cfg.get("alert_below_avg") and avg > 0:
            pct = (avg-lowest)/avg*100
            if pct >= self.cfg.get("price_drop_pct", 10):
                self.on_alert(name, f"📉 低于均价 {pct:.0f}%！¥{lowest:.2f} (均价 ¥{avg:.2f})", lowest); alerted = True
        h = self._prices.get(gid, [])
        if len(h) >= 5:
            ra = sum(h[-5:])/5
            if ra > 0:
                drop = (ra-lowest)/ra*100
                if drop >= self.cfg.get("price_drop_pct", 10):
                    self.on_alert(name, f"⚠️ 近期跌 {drop:.0f}%！¥{lowest:.2f}", lowest); alerted = True
        if alerted: self._last_alert[gid] = now


class SettingsDialog:
    def __init__(self, cfg, watcher=None, on_save=None):
        self.cfg = cfg; self.watcher = watcher; self.on_save = on_save
        self._live_prices = {}; self._build()

    def _build(self):
        self.win = tk.Tk()
        self.win.title("CS2 Price Watcher — 设置")
        self.win.geometry("700x620"); self.win.resizable(False, False)
        self.win.configure(bg="#1a1a2e")
        style = ttk.Style(); style.theme_use("clam")
        style.configure(".", background="#1a1a2e", foreground="#e0e0e0", fieldbackground="#16213e")
        style.configure("TLabel", background="#1a1a2e", foreground="#e0e0e0", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10))
        style.configure("Header.TLabel", font=("Segoe UI", 14, "bold"), foreground="#ff6b6b")
        style.configure("Treeview", background="#16213e", foreground="#e0e0e0", fieldbackground="#16213e", font=("Segoe UI", 9))
        style.configure("Treeview.Heading", background="#0f3460", foreground="#e0e0e0", font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", "#2a5298")])
        pad = {"padx": 16, "pady": 6}
        ttk.Label(self.win, text="🎯 CS2 Price Watcher", style="Header.TLabel").pack(pady=(16,6))

        # 监控列表
        frm = ttk.LabelFrame(self.win, text="监控列表", padding=8)
        frm.pack(fill="both", expand=True, **pad)
        cols = ("来源","名称","目标价","当前最低","在售均价","在售数")
        self.tree = ttk.Treeview(frm, columns=cols, show="headings", height=8)
        for c,w in zip(cols,(50,220,80,90,90,60)):
            self.tree.heading(c,text=c); self.tree.column(c,width=w,anchor="center")
        self.tree.column("名称",anchor="w"); self.tree.column("来源",anchor="center")
        self.tree.pack(fill="both", expand=True)
        self._refresh_list()
        bf = ttk.Frame(frm); bf.pack(fill="x", pady=(6,0))
        ttk.Button(bf, text="＋ 添加饰品", command=self._add_item).pack(side="left", padx=2)
        ttk.Button(bf, text="－ 移除选中", command=self._remove_item).pack(side="left", padx=2)
        ttk.Button(bf, text="🔄 刷新价格", command=self._refresh_prices).pack(side="left", padx=2)

        # Cookie
        fc = ttk.LabelFrame(self.win, text="Buff Cookie（可选，启用搜索）", padding=8)
        fc.pack(fill="x", **pad)
        r1 = ttk.Frame(fc); r1.pack(fill="x", pady=2)
        ttk.Label(r1, text="Cookie：", width=8).pack(side="left")
        self.var_cookie = tk.StringVar(value=self.cfg.get("buff_cookie",""))
        ttk.Entry(r1, textvariable=self.var_cookie, width=60, show="*").pack(side="left", fill="x", expand=True)
        ttk.Label(fc, text="悠悠有品无需 Cookie（自动通过浏览器获取）",
                  font=("Segoe UI", 8), foreground="#888").pack(anchor="w")

        # 参数
        fp = ttk.LabelFrame(self.win, text="参数", padding=8)
        fp.pack(fill="x", **pad)
        r3 = ttk.Frame(fp); r3.pack(fill="x", pady=2)
        ttk.Label(r3, text="检查间隔：").pack(side="left")
        self.var_poll = tk.IntVar(value=self.cfg["poll_interval"])
        ttk.Entry(r3, textvariable=self.var_poll, width=5).pack(side="left", padx=2)
        ttk.Label(r3, text="秒    跌幅阈值：").pack(side="left")
        self.var_drop = tk.IntVar(value=self.cfg["price_drop_pct"])
        ttk.Entry(r3, textvariable=self.var_drop, width=5).pack(side="left", padx=2)
        ttk.Label(r3, text="%    ").pack(side="left")
        self.var_sound = tk.BooleanVar(value=self.cfg.get("sound_alert",True))
        ttk.Checkbutton(r3, text="声音提醒", variable=self.var_sound).pack(side="left")

        fb = ttk.Frame(self.win); fb.pack(pady=(8,16))
        ttk.Button(fb, text="保存并应用", command=self._save).pack(side="left", padx=8)
        ttk.Button(fb, text="关闭", command=self.win.destroy).pack(side="left", padx=8)
        self.win.update_idletasks()
        w,h = self.win.winfo_width(), self.win.winfo_height()
        self.win.geometry(f"+{(self.win.winfo_screenwidth()-w)//2}+{(self.win.winfo_screenheight()-h)//2}")

    def _refresh_list(self):
        for r in self.tree.get_children(): self.tree.delete(r)
        for it in self.cfg["watchlist"]:
            gid = it["goods_id"]; tp = it.get("target_price",0)
            tgt = f"¥{tp:.2f}" if tp and tp > 0 else "—"
            lp = self._live_prices.get(gid, {})
            lo = f"¥{lp['lowest']:.2f}" if "lowest" in lp else "…"
            av = f"¥{lp['avg']:.2f}" if "avg" in lp else "…"
            ct = str(lp.get("count","…"))
            src = it.get("source","buff").upper()
            self.tree.insert("","end",values=(src,it["name"],tgt,lo,av,ct))

    def _add_item(self):
        cookie = self.var_cookie.get().strip()
        if cookie: self._add_by_search()
        else: self._add_by_url()

    def _add_by_search(self):
        kw = simpledialog.askstring("搜索饰品", "输入饰品名称：", parent=self.win)
        if not kw: return
        try:
            c = BuffClient(); c.set_cookies(self.var_cookie.get().strip())
            data = c.search(kw); items = data.get("items",[])
            if not items: messagebox.showinfo("结果","未找到饰品"); return
            ch = self._pick([f"{i['name']}  ¥{i.get('sell_min_price','?')}" for i in items[:15]])
            if ch is None: return
            s = items[ch]
            self._confirm(s["id"], s["name"], float(s.get("sell_min_price",0)), "buff")
        except Exception as e: messagebox.showerror("错误",str(e))

    def _add_by_url(self):
        url = simpledialog.askstring("添加饰品",
            "粘贴链接或 ID：\nBuff: buff.163.com/goods/773635\n悠悠有品: youpin898.com/...", parent=self.win)
        if not url: return
        src, gid = self._parse(url)
        if not gid: messagebox.showerror("错误","无法解析"); return
        try:
            if src == "youpin":
                c = YoupinClient()
                d = c.get_commodity_detail(gid)
                self._confirm(gid, d.get("commodityName",f"#{gid}"), float(d.get("price",0)), "youpin")
                c.close()
            else:
                c = BuffClient()
                d = c.get_goods_info(gid)
                self._confirm(gid, d.get("name",f"#{gid}"), float(d.get("sell_min_price",0)), "buff")
        except Exception as e: messagebox.showerror("错误",str(e))

    def _confirm(self, gid, name, price, src="buff"):
        tgt = simpledialog.askfloat("目标价格",
            f"[{src.upper()}] {name}\n当前最低: ¥{price:.2f}\n\n低于此价格时提醒（0=不限）：",
            parent=self.win, minvalue=0)
        for it in self.cfg["watchlist"]:
            if it["goods_id"] == gid:
                it.update({"target_price":tgt or 0,"name":name,"source":src})
                config.save(self.cfg); self._refresh_list(); return
        self.cfg["watchlist"].append({"goods_id":gid,"name":name,"target_price":tgt or 0,"source":src})
        config.save(self.cfg); self._refresh_list()

    def _parse(self, text):
        text = text.strip()
        if text.isdigit(): return "buff", int(text)
        m = re.search(r'buff\.163\.com/goods/(\d+)', text)
        if m: return "buff", int(m.group(1))
        m = re.search(r'youpin898\.com.*?/(\d+)', text)
        if m: return "youpin", int(m.group(1))
        return None, None

    def _pick(self, choices):
        dlg = tk.Toplevel(self.win); dlg.title("选择"); dlg.geometry("500x350")
        dlg.configure(bg="#1a1a2e"); dlg.transient(self.win); dlg.grab_set()
        res = [None]
        lb = tk.Listbox(dlg, bg="#16213e", fg="#e0e0e0", selectbackground="#2a5298", font=("Segoe UI",10))
        lb.pack(fill="both",expand=True,padx=10,pady=10)
        for c in choices: lb.insert(tk.END, c)
        def ok():
            s = lb.curselection()
            if s: res[0] = s[0]
            dlg.destroy()
        ttk.Button(dlg, text="确定", command=ok).pack(pady=(0,10))
        lb.bind("<Double-Button-1>", lambda e: ok())
        dlg.wait_window(); return res[0]

    def _remove_item(self):
        sel = self.tree.selection()
        if not sel: return
        idx = self.tree.index(sel[0])
        it = self.cfg["watchlist"][idx]
        config.remove_watch(self.cfg, it["goods_id"]); self._refresh_list()

    def _refresh_prices(self):
        def go():
            bc = BuffClient(rate_limit=1.5)
            for it in self.cfg["watchlist"]:
                try:
                    if it.get("source") == "youpin": continue  # 悠悠有品暂不支持批量刷新
                    data = bc.get_sell_orders(it["goods_id"])
                    ls = parse_sell_items(data)
                    if ls:
                        ps = [l["price"] for l in ls]
                        self._live_prices[it["goods_id"]] = {"lowest":ps[0],"avg":sum(ps)/len(ps),"count":len(ps)}
                except: pass
            self.win.after(0, self._refresh_list)
        threading.Thread(target=go, daemon=True).start()

    def _save(self):
        self.cfg["poll_interval"] = max(5, self.var_poll.get())
        self.cfg["price_drop_pct"] = max(1, self.var_drop.get())
        self.cfg["sound_alert"] = self.var_sound.get()
        self.cfg["buff_cookie"] = self.var_cookie.get().strip()
        config.save(self.cfg)
        if self.on_save: self.on_save(self.cfg)
        messagebox.showinfo("已保存","配置已保存，监控已重启")


class TrayApp:
    def __init__(self):
        self.cfg = config.load()
        self.log = self._setup_logging()
        self.watcher = None; self.icon = None
        self._status = "就绪"; self._has_alert = False

    def _setup_logging(self):
        log = logging.getLogger("cs2_watcher"); log.setLevel(logging.INFO)
        log.handlers.clear()
        fmt = logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S")
        APPDATA_DIR.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(APPDATA_DIR/"watcher.log", encoding="utf-8"); fh.setFormatter(fmt); log.addHandler(fh)
        ch = logging.StreamHandler(); ch.setFormatter(fmt); log.addHandler(ch)
        return log

    def _on_alert(self, name, msg, price):
        self.log.warning(f"🔔 [{name}] {msg}")
        self._has_alert = True
        if self.icon:
            self.icon.icon = create_icon(64, has_alert=True)
            self.icon.title = f"⚠️ {name}: ¥{price:.2f}"
        if self.cfg.get("sound_alert"):
            try: winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            except: pass
        if self.icon and hasattr(self.icon, 'notify'):
            try: self.icon.notify(f"{name}\n{msg}", "CS2 价格提醒")
            except: pass

    def _on_price_update(self, gid, lowest, avg, count):
        wl = self.cfg.get("watchlist",[])
        nm = next((w["name"] for w in wl if w["goods_id"] == gid), "")
        if self.icon: self.icon.title = f"监控中 | {nm}: ¥{lowest:.2f}"

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
        self.icon = pystray.Icon("cs2-watcher", img, f"CS2 Watcher — {self._status}", menu)

    def _on_settings(self, *a):
        threading.Thread(target=self._show_settings, daemon=True).start()

    def _show_settings(self):
        if self.watcher: self.watcher.stop()
        dlg = SettingsDialog(self.cfg, self.watcher, on_save=self._on_saved)
        dlg.win.mainloop()

    def _on_saved(self, new_cfg):
        self.cfg = new_cfg; self._start_watcher()

    def _clear_alert(self, *a):
        self._has_alert = False
        if self.icon: self.icon.icon = create_icon(64, has_alert=False)

    def _on_exit(self, *a):
        if self.watcher: self.watcher.stop()
        if self.icon: self.icon.stop()

    def _start_watcher(self):
        self.watcher = PriceWatcher(self.cfg, self.log, on_alert=self._on_alert, on_price_update=self._on_price_update)
        bc = self.cfg.get("buff_cookie","")
        if bc: self.watcher.buff.set_cookies(bc)
        yc = self.cfg.get("youpin_cookie","")
        if yc: self.watcher.youpin.set_cookies(yc)
        self.watcher.start()
        self._status = f"监控中 ({len(self.cfg['watchlist'])} 个)"

    def _watch_signal(self):
        while True:
            time.sleep(1)
            if SIGNAL_FILE.exists():
                try: SIGNAL_FILE.unlink()
                except: pass
                self._on_settings()

    def run(self):
        if not self.cfg["watchlist"]:
            self.log.info("首次运行，打开设置")
            dlg = SettingsDialog(self.cfg, on_save=self._on_saved)
            dlg.win.mainloop()
        else: self._start_watcher()
        threading.Thread(target=self._watch_signal, daemon=True).start()
        self._create_tray(); self.icon.run()


if __name__ == "__main__":
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    if LOCK_FILE.exists():
        try:
            old = int(LOCK_FILE.read_text().strip())
            os.kill(old, 0); SIGNAL_FILE.write_text("open"); sys.exit(0)
        except: LOCK_FILE.unlink(missing_ok=True)
    LOCK_FILE.write_text(str(os.getpid()))
    import atexit; atexit.register(lambda: LOCK_FILE.unlink(missing_ok=True))
    try: app = TrayApp(); app.run()
    except Exception as e: logging.exception(f"Fatal: {e}"); sys.exit(1)
