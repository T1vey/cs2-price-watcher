"""
CS2 Price Watcher — FastAPI backend
Endpoints:
  GET    /api/items            - list watched items with latest prices
  POST   /api/items            - add a new item (URL or id, auto-detect source)
  DELETE /api/items/{id}       - remove an item
  POST   /api/refresh          - force refresh all prices
  GET    /api/settings         - get current settings
  POST   /api/settings         - update settings
  GET    /api/health           - health check

The background loop polls every `poll_interval` seconds (default 30).
Prices are cached in memory; a snapshot is also persisted to config.json.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import re
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import config as cfg_mod
from buff_api import BuffClient, parse_sell_items
from youpin_api import YoupinClient

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("server")
APPDATA_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / cfg_mod.APP_NAME
APPDATA_DIR.mkdir(parents=True, exist_ok=True)
fh = logging.FileHandler(APPDATA_DIR / "server.log", encoding="utf-8")
fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s",
                                 datefmt="%H:%M:%S"))
log.addHandler(fh)

# ─── State ──────────────────────────────────────────────────────────────────
_lock = threading.RLock()
_state: dict[str, Any] = {
    "cfg": cfg_mod.load(),
    "buff": None,            # lazy
    "youpin": None,          # lazy
    "prices": {},            # goods_id -> {buff: {...}, youpin: {...}, ts: ...}
    "history": {},           # goods_id -> [price, ...] (last N)
    "alerts": [],            # recent alert events
    "last_refresh": 0.0,
    "refreshing": False,
    "last_error": None,
}

PRICE_HISTORY_MAX = 100
RECOVERY_PAUSE = 1.0
BUFF_PAUSE = 1.5
YOUPIN_PAUSE = 3.0


# ─── URL Parsing ────────────────────────────────────────────────────────────
BUFF_RE = re.compile(r"buff\.163\.com/(?:[a-z-]+/)?goods/(\d+)", re.I)
YOUPIN_RE = re.compile(r"youpin898\.com/(?:[a-z-]+/)?(?:goods/)?(\d+)", re.I)
BUFF_NUM = re.compile(r"^(\d{4,10})$")


def parse_url(text: str) -> tuple[Optional[str], Optional[int]]:
    """Return (source, goods_id) from URL or raw id."""
    text = (text or "").strip()
    if not text:
        return None, None
    m = BUFF_RE.search(text)
    if m:
        return "buff", int(m.group(1))
    m = YOUPIN_RE.search(text)
    if m:
        return "youpin", int(m.group(1))
    m = BUFF_NUM.match(text)
    if m:
        return "buff", int(m.group(1))
    return None, None


# ─── Clients (lazy) ─────────────────────────────────────────────────────────
def get_buff() -> BuffClient:
    with _lock:
        if _state["buff"] is None:
            c = BuffClient(rate_limit=BUFF_PAUSE)
            cookie = _state["cfg"].get("buff_cookie", "")
            if cookie:
                try:
                    c.set_cookies(cookie)
                except Exception as e:
                    log.warning("设置 Buff Cookie 失败: %s", e)
            _state["buff"] = c
        return _state["buff"]


def get_youpin() -> YoupinClient:
    with _lock:
        if _state["youpin"] is None:
            _state["youpin"] = YoupinClient(rate_limit=YOUPIN_PAUSE)
        return _state["youpin"]


# ─── Price Fetchers ─────────────────────────────────────────────────────────
def _fetch_buff(gid: int) -> dict:
    """Fetch current Buff price. Returns dict with low/avg/count/icon or error."""
    try:
        c = get_buff()
        data = c.get_sell_orders(gid)
        listings = parse_sell_items(data)
        if not listings:
            return {"error": "no_listings"}
        prices = [float(l["price"]) for l in listings if l.get("price")]
        if not prices:
            return {"error": "no_prices"}
        icon = next((l.get("icon") for l in listings if l.get("icon")), "")
        return {
            "low": round(min(prices), 2),
            "avg": round(sum(prices) / len(prices), 2),
            "count": len(prices),
            "icon": icon,
        }
    except Exception as e:
        log.warning("Buff 拉取 %s 失败: %s", gid, e)
        return {"error": str(e)[:160]}


def _fetch_youpin(gid: int) -> dict:
    """Fetch current YouPin price. Returns dict with low/avg/count/icon or error."""
    try:
        c = get_youpin()
        data = c.get_commodity_detail(gid) or {}
        # YouPin's response shape varies; tolerate both
        low = float(data.get("price") or data.get("MinPrice") or 0)
        avg = float(data.get("steamPrice") or data.get("AvgPrice") or low)
        count = int(data.get("onSaleCount") or data.get("OnSaleCount") or 0)
        icon = data.get("iconUrl") or data.get("icon") or ""
        name = data.get("commodityName") or data.get("name") or ""
        if low <= 0:
            return {"error": "no_price"}
        return {
            "low": round(low, 2),
            "avg": round(avg, 2),
            "count": count,
            "icon": icon,
            "name": name,
        }
    except Exception as e:
        log.warning("YouPin 拉取 %s 失败: %s", gid, e)
        return {"error": str(e)[:160]}


def _check_item(item: dict) -> dict:
    """Refresh one item; return updated price snapshot dict."""
    gid = item["goods_id"]
    src = item.get("source", "buff")
    snap: dict[str, Any] = {"ts": time.time(), "goods_id": gid, "source": src}
    if src == "youpin":
        snap["youpin"] = _fetch_youpin(gid)
        # Cross-check Buff if we can resolve it (optional - skipped for speed)
    else:
        snap["buff"] = _fetch_buff(gid)
    return snap


def _evaluate_alerts(item: dict, snap: dict) -> list[dict]:
    """Compute alert events based on thresholds. Returns list of alert dicts."""
    cfg = _state["cfg"]
    threshold_pct = float(cfg.get("price_drop_pct", 10))
    target = float(item.get("target_price", 0) or 0)

    src = item.get("source", "buff")
    src_snap = snap.get("buff") or snap.get("youpin") or {}
    low = float(src_snap.get("low", 0) or 0)
    avg = float(src_snap.get("avg", 0) or 0)
    if low <= 0:
        return []

    events = []
    # Target price
    if target > 0 and low <= target:
        events.append({
            "type": "target",
            "title": "🎯 到达目标价",
            "message": f"¥{low:.2f} ≤ ¥{target:.2f}",
        })
    # Below avg
    if cfg.get("alert_below_avg", True) and avg > 0:
        pct = (avg - low) / avg * 100
        if pct >= threshold_pct:
            events.append({
                "type": "below_avg",
                "title": "📉 低于均价",
                "message": f"{pct:.0f}% below avg (¥{low:.2f} / avg ¥{avg:.2f})",
            })
    # Recent drop (history based)
    h = _state["history"].setdefault(item["goods_id"], [])
    if len(h) >= 5:
        recent_avg = sum(h[-5:]) / 5
        if recent_avg > 0:
            drop = (recent_avg - low) / recent_avg * 100
            if drop >= threshold_pct:
                events.append({
                    "type": "drop",
                    "title": "⚠️ 近期大跌",
                    "message": f"drop {drop:.0f}% to ¥{low:.2f}",
                })
    return events


def _record_alerts(item: dict, events: list[dict]):
    """Append events to rolling alert log; mark item alerting if non-empty."""
    if not events:
        return
    with _lock:
        # Per-item cooldown
        cooldown_key = (item["goods_id"], events[0]["type"])
        now = time.time()
        last = _state.setdefault("_alert_cooldown", {}).get(cooldown_key, 0)
        if now - last < 300:
            return
        _state["_alert_cooldown"][cooldown_key] = now
        for ev in events:
            _state["alerts"].append({
                "ts": now,
                "goods_id": item["goods_id"],
                "name": item.get("name", f"#{item['goods_id']}"),
                **ev,
            })
        # Trim
        _state["alerts"] = _state["alerts"][-50:]


def refresh_all() -> dict:
    """Refresh all watched items synchronously. Used by background task."""
    with _lock:
        if _state["refreshing"]:
            return {"status": "busy"}
        _state["refreshing"] = True
    try:
        items = list(_state["cfg"].get("watchlist", []))
        log.info("开始刷新 %d 个饰品", len(items))
        ok = 0
        err = 0
        for item in items:
            try:
                snap = _check_item(item)
                gid = item["goods_id"]
                with _lock:
                    prev = _state["prices"].get(gid, {})
                    merged = {**prev, **snap}
                    _state["prices"][gid] = merged
                    # Update history with primary source low price
                    primary_low = (snap.get("buff") or snap.get("youpin") or {}).get("low")
                    if primary_low and primary_low > 0:
                        hist = _state["history"].setdefault(gid, [])
                        hist.append(primary_low)
                        if len(hist) > PRICE_HISTORY_MAX:
                            del hist[: len(hist) - PRICE_HISTORY_MAX]
                events = _evaluate_alerts(item, snap)
                _record_alerts(item, events)
                ok += 1
                time.sleep(RECOVERY_PAUSE)
            except Exception as e:
                log.error("刷新 %s 失败: %s", item.get("name"), e)
                err += 1
        with _lock:
            _state["last_refresh"] = time.time()
            _state["last_error"] = None
        log.info("刷新完成: 成功 %d / 失败 %d", ok, err)
        return {"status": "ok", "ok": ok, "err": err}
    finally:
        with _lock:
            _state["refreshing"] = False


async def _poll_loop():
    cfg = _state["cfg"]
    interval = int(cfg.get("poll_interval", 30))
    log.info("后台轮询启动 (间隔 %ds)", interval)
    # First pass: do an initial refresh shortly after startup
    await asyncio.sleep(2)
    while True:
        try:
            await asyncio.to_thread(refresh_all)
        except Exception as e:
            log.error("轮询异常: %s", e)
            with _lock:
                _state["last_error"] = str(e)
        # Re-read interval in case user changed it
        interval = max(5, int(_state["cfg"].get("poll_interval", 30)))
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_poll_loop())
    yield
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass
    with _lock:
        if _state.get("youpin"):
            try:
                _state["youpin"].close()
            except Exception:
                pass


# ─── App ────────────────────────────────────────────────────────────────────
app = FastAPI(title="CS2 Price Watcher API", version="1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Pydantic models ────────────────────────────────────────────────────────
class ItemIn(BaseModel):
    url: Optional[str] = None
    goods_id: Optional[int] = None
    source: Optional[str] = None  # override auto-detect
    name: Optional[str] = None
    target_price: float = 0.0


class ItemPatch(BaseModel):
    target_price: Optional[float] = None
    name: Optional[str] = None


class SettingsIn(BaseModel):
    poll_interval: Optional[int] = Field(default=None, ge=5, le=3600)
    price_drop_pct: Optional[int] = Field(default=None, ge=1, le=99)
    alert_below_avg: Optional[bool] = None
    sound_alert: Optional[bool] = None
    buff_cookie: Optional[str] = None
    youpin_cookie: Optional[str] = None


# ─── Helpers ────────────────────────────────────────────────────────────────
def _item_view(it: dict) -> dict:
    gid = it["goods_id"]
    snap = _state["prices"].get(gid, {})
    # Get the other platform's cached price if it exists
    buff = snap.get("buff")
    youpin = snap.get("youpin")
    primary_low = None
    if buff and isinstance(buff, dict) and "low" in buff:
        primary_low = buff["low"]
    elif youpin and isinstance(youpin, dict) and "low" in youpin:
        primary_low = youpin["low"]

    diff = None
    if buff and youpin and "low" in buff and "low" in youpin:
        diff = round(buff["low"] - youpin["low"], 2)

    # Determine alert status
    target = float(it.get("target_price", 0) or 0)
    alerting = False
    if primary_low and target > 0 and primary_low <= target:
        alerting = True
    if alerting is False:
        cfg = _state["cfg"]
        threshold = float(cfg.get("price_drop_pct", 10))
        avg = None
        if buff and "avg" in buff:
            avg = buff["avg"]
        elif youpin and "avg" in youpin:
            avg = youpin["avg"]
        if primary_low and avg and avg > 0:
            pct = (avg - primary_low) / avg * 100
            if pct >= threshold:
                alerting = True

    return {
        "id": gid,
        "goods_id": gid,
        "name": it.get("name") or f"#{gid}",
        "category": _detect_category(it.get("name", "")),
        "source": it.get("source", "buff"),
        "target_price": target,
        "buff": buff,
        "youpin": youpin,
        "price_diff": diff,
        "alerting": alerting,
        "ts": snap.get("ts"),
    }


def _coerce_float(value: Any) -> Optional[float]:
    """Best-effort positive float parser for API payloads with mixed shapes."""
    if value is None:
        return None
    try:
        if isinstance(value, str):
            value = value.strip().replace("¥", "").replace(",", "")
            if not value:
                return None
        num = float(value)
        if not math.isfinite(num) or num <= 0:
            return None
        return num
    except (TypeError, ValueError):
        return None


def _first_price(*payloads: dict) -> Optional[float]:
    keys = (
        "price", "sell_min_price", "quick_price", "steam_price_cny",
        "steam_price", "steamPrice", "reference_price", "sell_reference_price",
        "market_min_price", "min_price", "lowest_price", "low",
    )
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for key in keys:
            price = _coerce_float(payload.get(key))
            if price is not None:
                return round(price, 2)
    return None


# CS2 weapon categories
_CATEGORIES = {
    "匕首": ["匕首", "刺刀", "蝴蝶刀", "爪刀", "折叠刀", "穿肠刀", "猎杀者", "鲍伊",
             "弯刀", "暗影双匕", "骷髅刀", "廓尔喀刀", "短剑", "经典刀", "karambit",
             "bayonet", "butterfly", "flip", "gut", "huntsman", "bowie", "falchion",
             "shadow daggers", "skeleton", "navaja", "stiletto", "talon", "ursus",
             "classic"],
    "手枪": ["手枪", "沙鹰", "usp", "glock", "p250", "tec-9", "five-seven", "cz75",
             "deagle", "r8", "双持贝瑞塔", "p2000", "desert eagle", "dual berettas"],
    "步枪": ["步枪", "ak-47", "m4a4", "m4a1", "aug", "sg 553", "famas", "galil",
             "scar-20", "g3sg1", "awp", "ssg 08"],
    "冲锋枪": ["冲锋枪", "mp9", "mp7", "mp5", "ump-45", "p90", "mac-10", "pp-bizon",
               "mp5-sd"],
    "霰弹枪": ["霰弹枪", "nova", "xm1014", "mag-7", "sawed-off"],
    "机枪": ["机枪", "negev", "m249"],
    "手套": ["手套", "运动手套", "摩托手套", "专业手套", "血猎手套", "手部束带",
             "driver gloves", "sport gloves", "specialist gloves", "bloodhound gloves",
             "hydra gloves", "broken fang gloves"],
    "印花": ["印花", "sticker"],
    "武器箱": ["武器箱", "case", "钥匙"],
    "探员": ["探员", "agent"],
}


def _detect_category(name: str) -> str:
    """Detect CS2 weapon category from item name."""
    low = name.lower()
    for cat, keywords in _CATEGORIES.items():
        for kw in keywords:
            if kw in low:
                return cat
    return "其他"


def _normalize_buff_search(data: Any, limit: int = 20) -> list[dict]:
    """Normalize Buff search responses to the frontend search contract."""
    if isinstance(data, dict):
        raw_items = data.get("items") or data.get("goods") or data.get("list") or []
    elif isinstance(data, list):
        raw_items = data
    else:
        raw_items = []

    results: list[dict] = []
    for raw in raw_items[:limit]:
        if not isinstance(raw, dict):
            continue
        goods_info = raw.get("goods_info") if isinstance(raw.get("goods_info"), dict) else {}
        gid = raw.get("goods_id") or raw.get("id") or goods_info.get("goods_id") or goods_info.get("id")
        try:
            gid = int(gid)
        except (TypeError, ValueError):
            continue
        name = (
            raw.get("name")
            or raw.get("market_hash_name")
            or raw.get("goods_name")
            or goods_info.get("name")
            or goods_info.get("market_hash_name")
            or f"#{gid}"
        )
        icon = (
            raw.get("icon_url")
            or raw.get("icon")
            or goods_info.get("icon_url")
            or goods_info.get("icon")
            or ""
        )
        results.append({
            "name": name,
            "goods_id": gid,
            "source": "buff",
            "price": _first_price(raw, goods_info),
            "icon": icon,
        })
    return results


def _normalize_youpin_search(data: Any, limit: int = 20) -> list[dict]:
    """Normalize YouPin search responses to the frontend search contract."""
    raw_items = data if isinstance(data, list) else []
    results: list[dict] = []
    for raw in raw_items[:limit]:
        if not isinstance(raw, dict):
            continue
        gid = raw.get("goods_id") or raw.get("template_id") or raw.get("id")
        try:
            gid = int(gid)
        except (TypeError, ValueError):
            continue
        name = raw.get("name") or raw.get("commodityName") or raw.get("hash_name") or f"#{gid}"
        icon = raw.get("icon") or raw.get("iconUrl") or ""
        results.append({
            "name": name,
            "goods_id": gid,
            "source": "youpin",
            "price": _first_price(raw),
            "icon": icon,
        })
    return results


def _extract_history_prices(payload: Any) -> list[float]:
    """Extract price samples from Buff price history response variants."""
    prices: list[float] = []
    price_keys = (
        "price", "sell_min_price", "lowest_price", "min_price",
        "avg_price", "average_price", "value", "low",
    )

    def price_from_node(node: Any) -> Optional[float]:
        if isinstance(node, dict):
            for key in price_keys:
                price = _coerce_float(node.get(key))
                if price is not None:
                    return price
            return None
        if isinstance(node, (list, tuple)):
            candidates = []
            for value in node:
                price = _coerce_float(value)
                # Timestamps commonly appear next to prices; ignore obvious epoch values.
                if price is not None and price < 1_000_000:
                    candidates.append(price)
            return candidates[-1] if candidates else None
        price = _coerce_float(node)
        return price if price is not None and price < 1_000_000 else None

    def walk(node: Any):
        direct = price_from_node(node)
        if direct is not None:
            prices.append(direct)
            return
        if isinstance(node, dict):
            preferred = ("price_history", "history", "items", "records", "list", "data")
            values = [node[k] for k in preferred if k in node]
            if not values:
                values = list(node.values())
            for value in values:
                walk(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value)

    walk(payload)
    return prices


# ─── Routes ─────────────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {"ok": True, "ts": time.time()}


@app.get("/api/items")
def list_items():
    with _lock:
        cfg = _state["cfg"]
        items = [_item_view(it) for it in cfg.get("watchlist", [])]
        return {
            "items": items,
            "last_refresh": _state["last_refresh"],
            "refreshing": _state["refreshing"],
            "last_error": _state["last_error"],
        }


@app.get("/api/search")
def search_items(q: str):
    """Search Buff and YouPin for items matching a user query."""
    keyword = (q or "").strip()
    if len(keyword) < 2:
        return {"results": [], "errors": []}

    results: list[dict] = []
    errors: list[str] = []

    # 1. Buff search (requires cookie for search API)
    try:
        buff_data = get_buff().search(keyword)
        results.extend(_normalize_buff_search(buff_data))
    except Exception as e:
        log.info("Buff 搜索 API 不可用（需 Cookie），用列表过滤: %s", e)
        try:
            list_data = get_buff().list_items()
            items = list_data.get("items", [])
            kw = keyword.lower()
            matched = [it for it in items
                       if kw in (it.get("name", "") or "").lower()
                       or kw in (it.get("market_hash_name", "") or "").lower()]
            results.extend(_normalize_buff_search({"items": matched}))
        except Exception as e2:
            errors.append(f"Buff: {str(e2)[:120]}")

    # 2. YouPin search (via Playwright) — 需要登录才能搜索
    try:
        yp_data = get_youpin().search(keyword)
        if yp_data:
            results.extend(_normalize_youpin_search(yp_data))
    except Exception as e:
        log.debug("YouPin 搜索不可用: %s", e)

    # Dedupe + add category
    deduped: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for item in results:
        key = (item.get("source", ""), int(item.get("goods_id") or 0))
        if key in seen or not key[1]:
            continue
        seen.add(key)
        item["category"] = _detect_category(item.get("name", ""))
        deduped.append(item)

    return {"results": deduped[:30], "errors": errors}


@app.get("/api/recommend/{gid}")
def recommend_range(gid: int, source: str = "buff"):
    """Recommend a monitoring range from recent price history."""
    normalized_source = (source or "buff").lower()
    prices: list[float] = []
    history_error: Optional[str] = None

    if normalized_source == "buff":
        try:
            history_payload = get_buff().get_price_history(gid, days=7)
            prices = _extract_history_prices(history_payload)[-7:]
        except Exception as e:
            log.warning("Buff 历史价格拉取失败 %s: %s", gid, e)
            history_error = str(e)[:160]

    if not prices:
        with _lock:
            prices = [
                price for price in
                (_coerce_float(p) for p in _state["history"].get(int(gid), [])[-7:])
                if price is not None
            ]

    if not prices:
        with _lock:
            snap = _state["prices"].get(int(gid), {})
        current = _coerce_float((snap.get("buff") or snap.get("youpin") or {}).get("low"))
        if current is not None:
            prices = [current]

    if not prices:
        detail = history_error or "no price history available"
        raise HTTPException(status_code=404, detail=detail)

    low = round(min(prices), 2)
    avg = round(sum(prices) / len(prices), 2)
    high = round(max(prices), 2)
    recommended_target = round(low * 0.9, 2)
    return {
        "low": low,
        "avg": avg,
        "high": high,
        "recommended_target": recommended_target,
        "points": [round(p, 2) for p in prices],
    }


@app.post("/api/items")
def add_item(payload: ItemIn, background: BackgroundTasks):
    src, gid = None, None
    if payload.goods_id:
        gid = int(payload.goods_id)
        src = payload.source or "buff"
    if payload.url:
        s, g = parse_url(payload.url)
        if g and not gid:
            src, gid = s, g
    if not gid:
        raise HTTPException(status_code=400, detail="无法解析 URL 或 goods_id")

    # Look up name + initial price
    name = payload.name or f"#{gid}"
    snap: dict = {"ts": time.time(), "goods_id": gid, "source": src}
    if src == "youpin":
        d = _fetch_youpin(gid)
        if "name" in d and d["name"]:
            name = d["name"]
        if "error" not in d:
            snap["youpin"] = d
    else:
        # Try to get name from goods info, but tolerate failure
        try:
            info = get_buff().get_goods_info(gid)
            if isinstance(info, dict):
                if info.get("name"):
                    name = info["name"]
                if info.get("icon_url"):
                    snap.setdefault("buff", {})["icon"] = info["icon_url"]
        except Exception as e:
            log.info("Buff info 拉取失败 (非致命): %s", e)
        d = _fetch_buff(gid)
        if "error" not in d:
            snap["buff"] = d

    with _lock:
        watchlist = _state["cfg"].setdefault("watchlist", [])
        for it in watchlist:
            if it["goods_id"] == gid:
                # Update
                it["source"] = src
                it["name"] = name
                if payload.target_price:
                    it["target_price"] = float(payload.target_price)
                _state["prices"][gid] = {**_state["prices"].get(gid, {}), **snap}
                cfg_mod.save(_state["cfg"])
                return {"status": "updated", "item": _item_view(it)}
        new = {
            "goods_id": gid,
            "name": name,
            "source": src,
            "target_price": float(payload.target_price or 0),
        }
        watchlist.append(new)
        _state["prices"][gid] = snap
        cfg_mod.save(_state["cfg"])

    # Trigger background refresh
    background.add_task(refresh_all)
    return {"status": "added", "item": _item_view(new)}


@app.delete("/api/items/{gid}")
def delete_item(gid: int):
    with _lock:
        watchlist = _state["cfg"].get("watchlist", [])
        before = len(watchlist)
        watchlist[:] = [w for w in watchlist if int(w["goods_id"]) != int(gid)]
        if len(watchlist) == before:
            raise HTTPException(status_code=404, detail="not found")
        _state["prices"].pop(int(gid), None)
        _state["history"].pop(int(gid), None)
        cfg_mod.save(_state["cfg"])
    return {"status": "removed", "id": gid}


@app.patch("/api/items/{gid}")
def patch_item(gid: int, payload: ItemPatch):
    with _lock:
        for it in _state["cfg"].get("watchlist", []):
            if int(it["goods_id"]) == int(gid):
                if payload.target_price is not None:
                    it["target_price"] = float(payload.target_price)
                if payload.name:
                    it["name"] = payload.name
                cfg_mod.save(_state["cfg"])
                return {"status": "ok", "item": _item_view(it)}
    raise HTTPException(status_code=404, detail="not found")


@app.post("/api/refresh")
def force_refresh(background: BackgroundTasks):
    background.add_task(refresh_all)
    return {"status": "queued"}


@app.get("/api/settings")
def get_settings():
    with _lock:
        cfg = dict(_state["cfg"])
    # Don't leak cookies to frontend
    cfg.pop("buff_cookie", None)
    cfg.pop("youpin_cookie", None)
    return cfg


@app.post("/api/settings")
def update_settings(payload: SettingsIn):
    with _lock:
        cfg = _state["cfg"]
        changed = False
        if payload.poll_interval is not None:
            cfg["poll_interval"] = int(payload.poll_interval)
            changed = True
        if payload.price_drop_pct is not None:
            cfg["price_drop_pct"] = int(payload.price_drop_pct)
            changed = True
        if payload.alert_below_avg is not None:
            cfg["alert_below_avg"] = bool(payload.alert_below_avg)
            changed = True
        if payload.sound_alert is not None:
            cfg["sound_alert"] = bool(payload.sound_alert)
            changed = True
        if payload.buff_cookie is not None:
            cfg["buff_cookie"] = payload.buff_cookie
            # Reset client to pick up new cookie
            _state["buff"] = None
        if payload.youpin_cookie is not None:
            cfg["youpin_cookie"] = payload.youpin_cookie
        if changed:
            cfg_mod.save(cfg)
    return {"status": "ok"}


@app.get("/api/alerts")
def get_alerts():
    with _lock:
        return {"alerts": list(reversed(_state["alerts"][-30:]))}


@app.get("/api/history/{gid}")
def get_history(gid: int, limit: int = 30):
    with _lock:
        h = _state["history"].get(int(gid), [])[-limit:]
    return {"goods_id": gid, "history": h}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")
