import base64
import json
import os
import random
import shutil
import socket
import time
from pathlib import Path
from typing import Optional, Generator
from contextlib import contextmanager

from playwright.sync_api import sync_playwright, BrowserContext, Browser, Page, Locator
from playwright_stealth import Stealth

from config.config import settings
from core.logger import log

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

def is_cdp_port_open(host: str = "127.0.0.1", port: int = 9222) -> bool:
    """Checks whether Brave is already running with a remote debugging port."""
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False

def find_brave_executable() -> Optional[str]:
    """Auto-detects the path to the Brave browser executable on Linux/POSIX."""
    candidates = [
        settings.browser.brave_path,
        str(Path.home() / ".local/share/flatpak/exports/bin/com.brave.Browser"),
        "/var/lib/flatpak/exports/bin/com.brave.Browser",
        "/usr/bin/brave-browser",
        "/usr/bin/brave",
        shutil.which("brave-browser"),
        shutil.which("brave"),
        shutil.which("com.brave.Browser"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return str(c)
    return None

class BrowserManager:
    """
    Manages Playwright browser lifecycle with persistent profile,
    anti-bot stealth injection, and realistic human behavior simulation.
    Supports native Brave Browser as well as standard Chromium.
    Supports direct connection to currently open Brave via CDP (port 9222).
    """
    def __init__(self, headless: Optional[bool] = None, slow_mo: Optional[int] = None):
        self.headless = headless if headless is not None else settings.browser.headless
        self.slow_mo = slow_mo if slow_mo is not None else settings.browser.slow_mo_ms
        self.user_data_dir = Path(settings.browser.user_data_dir)
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        self.stealth = Stealth()
        self.playwright = None
        self.cdp_browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None

    def start(self) -> BrowserContext:
        """Starts Playwright with persistent context or connects to running Brave via CDP."""
        if self.context:
            return self.context

        self.playwright = sync_playwright().start()

        # Check if user already has Brave open with remote debugging
        if is_cdp_port_open():
            try:
                log.info("[bold green]Found running Brave with Remote Debugging (port 9222)![/bold green] Connecting directly to your live session...")
                self.cdp_browser = self.playwright.chromium.connect_over_cdp("http://127.0.0.1:9222")
                if self.cdp_browser.contexts:
                    self.context = self.cdp_browser.contexts[0]
                else:
                    self.context = self.cdp_browser.new_context()
                return self.context
            except Exception as cdp_err:
                log.warning(f"Could not connect via CDP ({cdp_err}). Launching standalone instance...")

        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-default-browser-check",
            "--disable-infobars",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--window-size=1400,900",
        ]

        executable_path = None
        if settings.browser.engine.lower() == "brave":
            brave_bin = find_brave_executable()
            if brave_bin:
                executable_path = brave_bin
                log.info(f"[bold magenta]Using Brave Browser:[/bold magenta] {brave_bin}")
            else:
                log.warning("Brave requested but executable not found. Falling back to bundled Chromium.")

        log.info(f"Launching persistent browser context (headless={self.headless})...")
        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.user_data_dir),
            executable_path=executable_path,
            headless=self.headless,
            slow_mo=self.slow_mo,
            user_agent=DEFAULT_USER_AGENT,
            viewport={"width": 1400, "height": 900},
            args=args,
            accept_downloads=True,
            timeout=settings.browser.timeout_ms,
        )

        # Inject stored session cookies if available (cloud / standalone execution)
        cookies_to_load = []
        auth_env = (os.getenv("AUTH_STORAGE_STATE") or "").strip()
        auth_file = Path("data/auth_state.json")
        if auth_env:
            try:
                if auth_env.startswith("{") and "cookies" in auth_env:
                    data = json.loads(auth_env)
                    cookies_to_load = data.get("cookies", [])
                else:
                    clean_b64 = "".join(auth_env.split())
                    missing_padding = len(clean_b64) % 4
                    if missing_padding:
                        clean_b64 += "=" * (4 - missing_padding)
                    raw_json = base64.b64decode(clean_b64, validate=False).decode("utf-8")
                    data = json.loads(raw_json)
                    cookies_to_load = data.get("cookies", [])
            except Exception as e:
                log.warning(f"Could not decode AUTH_STORAGE_STATE environment variable: {e}")
        elif auth_file.exists():
            try:
                data = json.loads(auth_file.read_text())
                cookies_to_load = data.get("cookies", [])
            except Exception as e:
                log.warning(f"Could not read data/auth_state.json: {e}")

        if cookies_to_load:
            try:
                self.context.add_cookies(cookies_to_load)
                log.info(f"[bold green]✓ Restored {len(cookies_to_load)} authenticated session cookies![/bold green]")
            except Exception as e:
                log.warning(f"Could not restore session cookies: {e}")

        for page in self.context.pages:
            self.prepare_page(page)

        self.context.on("page", lambda new_page: self.prepare_page(new_page))
        return self.context

    def prepare_page(self, page: Page):
        """Applies stealth and anti-bot evasions to a given page."""
        try:
            self.stealth.apply_stealth_sync(page)
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                window.chrome = {
                    runtime: {}
                };
            """)
        except Exception as e:
            log.debug(f"Could not apply extra stealth scripts: {e}")

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
            if self.cdp_browser:
                # Disconnect from user's live browser without killing their tabs
                self.cdp_browser.close()
                self.cdp_browser = None
                self.context = None
            elif self.context:
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
