"""配置管理"""

import json
from pathlib import Path

APP_NAME = "CS2-PriceWatcher"
CONFIG_DIR = Path.home() / "AppData" / "Local" / APP_NAME
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS = {
    "watchlist": [],           # [{"goods_id": 123, "name": "...", "target_price": 100.0, "source": "buff"}, ...]
    "poll_interval": 30,
    "price_drop_pct": 10,
    "alert_below_avg": True,
    "avg_days": 7,
    "sound_alert": True,
    "buff_cookie": "",
    "youpin_cookie": "",       # 悠悠有品 Cookie（被 WAF 保护，必须提供）
}


def load() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            return {**DEFAULTS, **saved}
        except (json.JSONDecodeError, IOError):
            pass
    return dict(DEFAULTS)


def save(cfg: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def add_watch(cfg: dict, goods_id: int, name: str, target_price: float = 0):
    """添加监控饰品"""
    for item in cfg["watchlist"]:
        if item["goods_id"] == goods_id:
            item["target_price"] = target_price
            item["name"] = name
            save(cfg)
            return
    cfg["watchlist"].append({
        "goods_id": goods_id,
        "name": name,
        "target_price": target_price,
    })
    save(cfg)


def remove_watch(cfg: dict, goods_id: int):
    """移除监控饰品"""
    cfg["watchlist"] = [w for w in cfg["watchlist"] if w["goods_id"] != goods_id]
    save(cfg)
