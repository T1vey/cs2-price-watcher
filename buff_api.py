"""Buff API 客户端 — 获取 CS2 饰品在售价格"""

import time
import logging
import requests

BUFF_BASE = "https://buff.163.com/api/market"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://buff.163.com/",
}

log = logging.getLogger("buff_api")


class BuffClient:
    """Buff 市场 API 客户端"""

    def __init__(self, rate_limit: float = 1.5, max_retries: int = 3):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._last_request = 0
        self._rate_limit = rate_limit
        self._max_retries = max_retries

    def set_cookies(self, cookies: str):
        """设置登录 Cookie（启用搜索功能）
        从浏览器开发者工具复制 Cookie 字符串
        """
        for item in cookies.split(";"):
            item = item.strip()
            if "=" in item:
                k, v = item.split("=", 1)
                self.session.cookies.set(k.strip(), v.strip())

    def _get(self, path: str, params: dict = None) -> dict:
        """带限速 + 重试的 GET 请求"""
        url = f"{BUFF_BASE}{path}"

        for attempt in range(self._max_retries):
            elapsed = time.time() - self._last_request
            if elapsed < self._rate_limit:
                time.sleep(self._rate_limit - elapsed)

            try:
                resp = self.session.get(url, params=params, timeout=15)
                self._last_request = time.time()

                if resp.status_code == 429:
                    wait = min(5 * (attempt + 1), 30)
                    log.warning(f"Rate limited, waiting {wait}s...")
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                data = resp.json()

                code = data.get("code")
                if code == "OK":
                    return data.get("data", {})
                elif code == "Login Required":
                    raise ValueError("需要登录 Cookie，请在设置中配置")
                else:
                    raise ValueError(f"Buff API: {code} - {data.get('msg')}")

            except requests.exceptions.Timeout:
                log.warning(f"Timeout on {path}, retry {attempt+1}/{self._max_retries}")
                time.sleep(2)
            except requests.exceptions.ConnectionError:
                log.warning(f"Connection error on {path}, retry {attempt+1}/{self._max_retries}")
                time.sleep(5)

        raise RuntimeError(f"请求失败，已重试 {self._max_retries} 次: {path}")

    # ── 公开接口（无需登录）──

    def list_items(self, page: int = 1) -> dict:
        """浏览饰品列表"""
        return self._get("/goods", {"game": "csgo", "page_num": page})

    def get_sell_orders(self, goods_id: int, page: int = 1) -> dict:
        """获取某饰品的在售列表（按价格升序）"""
        return self._get("/goods/sell_order", {
            "game": "csgo",
            "goods_id": goods_id,
            "page_num": page,
            "sort_by": "price.asc",
        })

    def get_goods_info(self, goods_id: int) -> dict:
        """获取饰品详情（最低价、在售数量等）"""
        return self._get("/goods/info", {"game": "csgo", "goods_id": goods_id})

    def get_price_history(self, goods_id: int, days: int = 7) -> dict:
        """获取价格历史"""
        return self._get("/goods/price_history", {
            "game": "csgo", "goods_id": goods_id, "days": days,
        })

    # ── 需要登录的接口 ──

    def search(self, keyword: str, page: int = 1) -> dict:
        """搜索饰品（需要 Cookie）"""
        return self._get("/goods", {
            "game": "csgo", "page_num": page, "search": keyword,
        })


def parse_sell_items(data: dict) -> list[dict]:
    """
    解析在售列表，提取关键信息
    返回: [{"price": 12.5, "wear": 0.15, "paint_seed": 123, "stattrak": False}, ...]
    """
    results = []
    for item in data.get("items", []):
        price = float(item.get("price", 0))
        asset = item.get("asset_info", {})
        info = asset.get("info", {})

        # 磨损值：可能是字符串 "0.15..." 或数字
        wear_raw = info.get("paintwear")
        wear = None
        if wear_raw is not None:
            try:
                wear = float(wear_raw)
            except (ValueError, TypeError):
                pass

        # StatTrak：从顶层 goods_info 的 quality 标签判断
        is_st = False
        goods_info = item.get("goods_info", {})
        quality = goods_info.get("info", {}).get("tags", {}).get("quality", {})
        if quality:
            is_st = "StatTrak" in quality.get("localized_name", "")

        results.append({
            "id": item.get("id"),
            "price": price,
            "wear": wear,
            "paint_seed": info.get("paintseed"),
            "stattrak": is_st,
            "icon": goods_info.get("icon_url", ""),
        })

    return results
