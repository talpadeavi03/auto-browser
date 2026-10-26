import random
import time
from pathlib import Path
from typing import Optional, Generator
from contextlib import contextmanager

from playwright.sync_api import sync_playwright, BrowserContext, Page, Locator
from playwright_stealth import Stealth

from config.config import settings
from core.logger import log

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

class BrowserManager:
    """
    Manages Playwright browser lifecycle with persistent profile,
    anti-bot stealth injection, and realistic human behavior simulation.
    """
    def __init__(self, headless: Optional[bool] = None, slow_mo: Optional[int] = None):
        self.headless = headless if headless is not None else settings.browser.headless
        self.slow_mo = slow_mo if slow_mo is not None else settings.browser.slow_mo_ms
        self.user_data_dir = Path(settings.browser.user_data_dir)
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        self.stealth = Stealth()
        self.playwright = None
        self.context: Optional[BrowserContext] = None

    def start(self) -> BrowserContext:
        """Starts Playwright with persistent context and stealth configuration."""
        if self.context:
            return self.context

        self.playwright = sync_playwright().start()

        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-default-browser-check",
            "--disable-infobars",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--window-size=1400,900",
        ]

        log.info(f"Launching persistent browser context (headless={self.headless})...")
        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.user_data_dir),
            headless=self.headless,
            slow_mo=self.slow_mo,
            user_agent=DEFAULT_USER_AGENT,
            viewport={"width": 1400, "height": 900},
            args=args,
            accept_downloads=True,
            timeout=settings.browser.timeout_ms,
        )

        # Inject stealth hooks on all existing and future pages
        for page in self.context.pages:
            self.prepare_page(page)

        self.context.on("page", lambda new_page: self.prepare_page(new_page))
        return self.context

    def prepare_page(self, page: Page):
        """Applies stealth and anti-bot evasions to a given page."""
        try:
            self.stealth.apply_stealth_sync(page)
            # Extra evasion scripts
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                window.chrome = {
                    runtime: {}
                };
            """)
        except Exception as e:
            log.warning(f"Could not apply extra stealth scripts: {e}")

    def new_page(self) -> Page:
        """Returns the main active page or creates a new stealth page."""
        if not self.context:
            self.start()

        if self.context.pages:
            page = self.context.pages[0]
        else:
            page = self.context.new_page()

        self.prepare_page(page)
        return page

    def close(self):
        """Gracefully closes context and Playwright instance."""
        try:
            if self.context:
                self.context.close()
                self.context = None
            if self.playwright:
                self.playwright.stop()
                self.playwright = None
            log.info("Browser session closed safely.")
        except Exception as e:
            log.error(f"Error while closing browser: {e}")

    # Human-like interaction helpers
    @staticmethod
    def human_delay(min_sec: float = 1.0, max_sec: float = 2.5):
        """Simulates natural human hesitation."""
        time.sleep(random.uniform(min_sec, max_sec))

    @staticmethod
    def human_type(locator: Locator, text: str, delay_range: tuple = (0.04, 0.12)):
        """Types text character by character with human typing variances."""
        locator.click()
        BrowserManager.human_delay(0.2, 0.5)
        locator.fill("") # Clear first
        for char in text:
            locator.type(char, delay=int(random.uniform(*delay_range) * 1000))

    @staticmethod
    def human_scroll(page: Page, steps: int = 3, distance: int = 400):
        """Smoothly scrolls page to emulate real human browsing behavior."""
        for _ in range(steps):
            delta = distance + random.randint(-50, 50)
            page.mouse.wheel(0, delta)
            time.sleep(random.uniform(0.4, 0.8))

    @staticmethod
    def safe_click(locator: Locator):
        """Hovers over element briefly before clicking."""
        try:
            locator.scroll_into_view_if_needed(timeout=5000)
            locator.hover(timeout=5000)
            time.sleep(random.uniform(0.1, 0.3))
            locator.click()
        except Exception:
            # Fallback direct click
            locator.click(force=True)

@contextmanager
def get_browser(headless: Optional[bool] = None) -> Generator[BrowserManager, None, None]:
    """Context manager wrapper for clean resource handling."""
    manager = BrowserManager(headless=headless)
    try:
        manager.start()
        yield manager
    finally:
        manager.close()
