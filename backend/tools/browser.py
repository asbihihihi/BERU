from typing import Any

class BrowserService:
    """Lazy Playwright browser session. Does not bypass site authentication or security."""
    def __init__(self): self.playwright=None; self.browser=None; self.page=None
    async def _page(self):
        if self.page is None:
            from playwright.async_api import async_playwright
            self.playwright=await async_playwright().start(); self.browser=await self.playwright.chromium.launch(headless=True); self.page=await self.browser.new_page()
        return self.page
    async def open_url(self,a:dict[str,Any]):
        page=await self._page(); await page.goto(a["url"],wait_until="domcontentloaded",timeout=30000); return {"url":page.url,"title":await page.title()}
    async def get_page_title(self,a:dict[str,Any]): return {"title":await (await self._page()).title()}
    async def get_page_text(self,a:dict[str,Any]): return {"text":(await (await self._page()).locator("body").inner_text())[:30000]}
    async def click(self,a:dict[str,Any]): await (await self._page()).locator(a["selector"]).click(); return {"clicked":a["selector"]}
    async def type(self,a:dict[str,Any]): await (await self._page()).locator(a["selector"]).fill(a["text"]); return {"typed":a["selector"]}
    async def press_key(self,a:dict[str,Any]): await (await self._page()).keyboard.press(a["key"]); return {"pressed":a["key"]}
    async def take_page_screenshot(self,a:dict[str,Any]):
        path=a.get("path","browser_screenshot.png"); await (await self._page()).screenshot(path=path,full_page=True); return {"path":path}
