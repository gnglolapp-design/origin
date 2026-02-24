from __future__ import annotations
from playwright.sync_api import sync_playwright, Page
import time

class RenderClient:
    def __init__(self, headless: bool = True) -> None:
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(headless=headless)
        self.ctx = self.browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=1.0,
            user_agent="OriginsDBSync/1.0 (+discord webhooks)"
        )
        self.page = self.ctx.new_page()

    def goto(self, url: str) -> Page:
        self.page.goto(url, wait_until="domcontentloaded", timeout=120_000)
        # attendre un peu pour les chargements JS
        self.page.wait_for_timeout(1200)
        try:
            self.page.wait_for_load_state("networkidle", timeout=60_000)
        except Exception:
            pass
        return self.page

    def close(self) -> None:
        self.ctx.close()
        self.browser.close()
        self.pw.stop()
