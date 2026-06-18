"""悠悠有品 API 客户端 — 通过 Playwright 绕过 WAF"""

import time
import logging

log = logging.getLogger("youpin_api")


class YoupinClient:
    """悠悠有品客户端（Playwright 浏览器自动化）"""

    def __init__(self, rate_limit: float = 3.0):
        self._rate_limit = rate_limit
        self._last_request = 0
        self._browser = None
        self._page = None
        self._pw = None
        self._ready = False

    def _ensure_browser(self):
        if self._ready:
            return
        try:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)
            self._page = self._browser.new_page()
            self._page.goto("https://www.youpin898.com/market",
                          wait_until="domcontentloaded", timeout=30000)
            self._page.wait_for_timeout(5000)  # 等 SPA 渲染
            self._ready = True
            log.info("悠悠有品浏览器已启动")
        except Exception as e:
            log.error(f"启动浏览器失败: {e}")
            raise

    def _wait_rate_limit(self):
        elapsed = time.time() - self._last_request
        if elapsed < self._rate_limit:
            time.sleep(self._rate_limit - elapsed)
        self._last_request = time.time()

    def _intercept_api(self, url_keyword: str, action, timeout: int = 8000) -> dict:
        """执行操作并拦截 API 响应"""
        self._ensure_browser()
        self._wait_rate_limit()
        result = {}

        def on_response(response):
            if url_keyword in response.url:
                try:
                    result["data"] = response.json()
                except:
                    pass

        self._page.on("response", on_response)
        try:
            action()
            self._page.wait_for_timeout(timeout)
        finally:
            self._page.remove_listener("response", on_response)

        return result.get("data", {})

    def get_market_list(self) -> list[dict]:
        """获取市场列表"""
        self._ensure_browser()

        def do_reload():
            self._page.reload(wait_until="domcontentloaded", timeout=20000)
            self._page.wait_for_timeout(5000)

        resp = self._intercept_api("querySaleTemplate", do_reload)
        items = resp.get("Data", [])
        return [_parse_item(it) for it in items]

    def search(self, keyword: str) -> list[dict]:
        """搜索饰品"""
        self._ensure_browser()

        def do_search():
            try:
                inp = self._page.locator('input[placeholder*="物品"], input[placeholder*="名称"]').first
                inp.fill(keyword)
                self._page.keyboard.press("Enter")
            except Exception as e:
                log.warning(f"搜索操作失败: {e}")

        resp = self._intercept_api("querySaleTemplate", do_search, timeout=10000)
        items = resp.get("Data", [])
        return [_parse_item(it) for it in items]

    def get_commodity_detail(self, template_id: int) -> dict:
        """获取商品详情"""
        self._ensure_browser()

        def do_nav():
            self._page.goto(f"https://www.youpin898.com/goods/{template_id}",
                          wait_until="domcontentloaded", timeout=20000)
            self._page.wait_for_timeout(5000)

        resp = self._intercept_api("queryTemplateDetail", do_nav)
        return resp.get("Data", {})

    def close(self):
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()
        self._ready = False


def _parse_item(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "name": item.get("commodityName", ""),
        "hash_name": item.get("commodityHashName", ""),
        "price": float(item.get("price", 0)),
        "steam_price": float(item.get("steamPrice", 0)),
        "on_sale_count": item.get("onSaleCount", 0),
        "icon": item.get("iconUrl", ""),
        "type": item.get("typeName", ""),
        "exterior": item.get("exterior", ""),
        "rarity": item.get("rarity", ""),
    }


def parse_commodity_list(data: list) -> list[dict]:
    return [_parse_item(it) for it in data]
