"""悠悠有品 API 客户端 — 获取 CS2 饰品在售价格"""

import time
import logging
import requests

YOUPIN_API = "https://api.youpin898.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://www.youpin898.com/",
    "Origin": "https://www.youpin898.com",
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
}

log = logging.getLogger("youpin_api")


class YoupinClient:
    """悠悠有品 API 客户端"""

    def __init__(self, rate_limit: float = 2.0, max_retries: int = 3):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._last_request = 0
        self._rate_limit = rate_limit
        self._max_retries = max_retries

    def set_cookies(self, cookies: str):
        """设置登录 Cookie（必须，否则被 WAF 拦截）
        从浏览器开发者工具复制 Cookie
        """
        for item in cookies.split(";"):
            item = item.strip()
            if "=" in item:
                k, v = item.split("=", 1)
                self.session.cookies.set(k.strip(), v.strip())

    def _post(self, path: str, data: dict = None) -> dict:
        """带限速 + 重试的 POST 请求"""
        url = f"{YOUPIN_API}{path}"

        for attempt in range(self._max_retries):
            elapsed = time.time() - self._last_request
            if elapsed < self._rate_limit:
                time.sleep(self._rate_limit - elapsed)

            try:
                resp = self.session.post(url, json=data or {}, timeout=15)
                self._last_request = time.time()

                if resp.status_code == 405:
                    raise ValueError("被 WAF 拦截，请更新 Cookie")
                if resp.status_code == 429:
                    wait = min(5 * (attempt + 1), 30)
                    log.warning(f"Rate limited, waiting {wait}s...")
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                result = resp.json()

                code = result.get("Code")
                if code == 0 or code == 200:
                    return result.get("Data", {})
                else:
                    raise ValueError(f"YouPin API: {code} - {result.get('Message')}")

            except requests.exceptions.Timeout:
                log.warning(f"Timeout, retry {attempt+1}/{self._max_retries}")
                time.sleep(2)
            except requests.exceptions.ConnectionError:
                log.warning(f"Connection error, retry {attempt+1}/{self._max_retries}")
                time.sleep(5)

        raise RuntimeError(f"请求失败，已重试 {self._max_retries} 次: {path}")

    def search_market(self, keyword: str = "", page: int = 1, page_size: int = 20) -> dict:
        """
        搜索市场在售饰品
        返回: {"CommodityList": [...], "Total": N}
        """
        data = {
            "pageIndex": page,
            "pageSize": page_size,
        }
        if keyword:
            data["keyword"] = keyword
        return self._post("/api/homepage/pc/goods/market/queryOnSaleCommodityList", data)

    def get_commodity_detail(self, template_id: int) -> dict:
        """
        获取商品详情
        """
        return self._post("/api/homepage/pc/goods/market/queryTemplateDetail", {
            "templateId": template_id,
        })

    def get_price_trend(self, template_id: int) -> dict:
        """
        获取价格趋势
        """
        return self._post("/api/youpin/price/trend/filter/info", {
            "templateId": template_id,
        })


def parse_commodity_list(data: dict) -> list[dict]:
    """
    解析商品列表，提取关键信息
    """
    results = []
    for item in data.get("CommodityList", []):
        results.append({
            "template_id": item.get("TemplateId"),
            "name": item.get("CommodityName", ""),
            "price": float(item.get("Price", 0)),
            "on_sale_count": item.get("OnSaleCount", 0),
            "icon": item.get("ImageUrl", ""),
            "game": item.get("GameName", "csgo"),
        })
    return results
