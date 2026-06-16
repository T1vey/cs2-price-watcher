"""Buff API 客户端 — 获取 CS2 饰品在售价格"""

import time
import requests
from typing import Optional

BUFF_BASE = "https://buff.163.com/api/market"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://buff.163.com/",
}


class BuffClient:
    """Buff 市场 API 客户端"""

    def __init__(self, rate_limit: float = 1.0):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._last_request = 0
        self._rate_limit = rate_limit  # 最小请求间隔（秒）

    def _get(self, path: str, params: dict = None) -> dict:
        """带限速的 GET 请求"""
        elapsed = time.time() - self._last_request
        if elapsed < self._rate_limit:
            time.sleep(self._rate_limit - elapsed)

        url = f"{BUFF_BASE}{path}"
        resp = self.session.get(url, params=params, timeout=15)
        self._last_request = time.time()
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != "OK":
            raise ValueError(f"Buff API error: {data.get('code')} - {data.get('msg')}")
        return data.get("data", {})

    def search(self, keyword: str, page: int = 1) -> dict:
        """
        搜索饰品（需要登录 Cookie）
        返回: {"items": [...], "total_count": N}
        """
        return self._get("/goods", {
            "game": "csgo",
            "page_num": page,
            "search": keyword,
        })

    def list_items(self, page: int = 1) -> dict:
        """
        浏览饰品列表（不需要登录，不支持排序）
        """
        return self._get("/goods", {
            "game": "csgo",
            "page_num": page,
        })

    def get_sell_orders(self, goods_id: int, page: int = 1, sort: str = "default") -> dict:
        """
        获取某饰品的在售列表
        返回: {"items": [{"price": "12.5", "asset_info": {...}}, ...]}
        """
        return self._get("/goods/sell_order", {
            "game": "csgo",
            "goods_id": goods_id,
            "page_num": page,
            "sort_by": sort,
        })

    def get_goods_info(self, goods_id: int) -> dict:
        """
        获取饰品详情（最低价、参考价、在售数量等）
        """
        return self._get("/goods/info", {
            "game": "csgo",
            "goods_id": goods_id,
        })

    def get_price_history(self, goods_id: int, days: int = 7) -> dict:
        """
        获取价格历史
        """
        return self._get("/goods/price_history", {
            "game": "csgo",
            "goods_id": goods_id,
            "days": days,
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

        results.append({
            "id": item.get("id"),
            "price": price,
            "wear": info.get("paintwear"),
            "paint_seed": info.get("paintseed"),
            "stattrak": "StatTrak" in asset.get("goods_info", {}).get("info", {}).get("tags", {}).get("quality", {}).get("localized_name", ""),
            "icon": asset.get("goods_info", {}).get("icon_url", ""),
        })

    return results
