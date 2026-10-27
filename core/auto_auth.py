import base64
import json
import os
import time
from pathlib import Path
from typing import Optional
from playwright.sync_api import Page
from config.config import settings
from core.browser import BrowserManager
from core.logger import log

def persist_session_cookies(page: Page) -> int:
    """Extracts and persists active session cookies to data/auth_state.json and data/auth_secret_for_github.txt."""
    try:
        context = page.context
        cookies = context.cookies()
        filtered = [c for c in cookies if any(d in c.get("domain", "") for d in ["naukri.com", "linkedin.com"])]
        if not filtered:
            return 0

        payload = {"cookies": filtered}
        json_str = json.dumps(payload, indent=2)
        b64_str = base64.b64encode(json_str.encode("utf-8")).decode("utf-8")

        data_dir = Path("data")
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "auth_state.json").write_text(json_str, encoding="utf-8")
        (data_dir / "auth_secret_for_github.txt").write_text(b64_str, encoding="utf-8")

        log.info(f"[bold green]✓ Automatically saved {len(filtered)} session cookies to data/auth_state.json![/bold green]")
        return len(filtered)
    except Exception as e:
        log.warning(f"Could not persist session cookies: {e}")
        return 0

def auto_login_linkedin(page: Page) -> bool:
    """
    Autonomously logs into LinkedIn using credentials from LINKEDIN_USERNAME and LINKEDIN_PASSWORD.
    Handles human typing cadence, error detection, and automatic session persistence.
    """
    user = os.getenv("LINKEDIN_USERNAME") or getattr(settings.linkedin, "username", None)
    pwd = os.getenv("LINKEDIN_PASSWORD") or getattr(settings.linkedin, "password", None)

    if not user or not pwd:
        log.debug("LinkedIn credentials not found in environment (LINKEDIN_USERNAME / LINKEDIN_PASSWORD).")
        return False

    log.info(f"[cyan]Attempting autonomous LinkedIn login for: {user}...[/cyan]")
    try:
        page.goto("https://www.linkedin.com/login", timeout=30000, wait_until="domcontentloaded")
        BrowserManager.human_delay(1.5, 2.5)

        # 1. Fill Username
        user_input = page.locator("#username, input[name='session_key'], input[id*='username']").first
        if not user_input.is_visible(timeout=5000):
            log.warning("LinkedIn username input field not found.")
            return False

        BrowserManager.human_type(user_input, user)
        BrowserManager.human_delay(0.5, 1.2)

        # 2. Fill Password
        pwd_input = page.locator("#password, input[name='session_password'], input[id*='password']").first
        if not pwd_input.is_visible(timeout=5000):
            log.warning("LinkedIn password input field not found.")
            return False

        BrowserManager.human_type(pwd_input, pwd)
        BrowserManager.human_delay(0.8, 1.5)

        # 3. Click Submit
        submit_btn = page.locator("button[type='submit'], button:has-text('Sign in'), button:has-text('Log in')").first
        submit_btn.click()

        # 4. Wait for navigation / response
        page.wait_for_load_state("domcontentloaded", timeout=20000)
        BrowserManager.human_delay(3.0, 5.0)

        current_url = page.url.lower()

        # Handle Security Checkpoints / Verification
        if "checkpoint" in current_url or "challenge" in current_url:
            log.warning(f"[bold yellow]LinkedIn triggered a security verification checkpoint:[/bold yellow] {page.url}")
            log.info("Please complete the verification prompt on your screen.")
            # Wait up to 60 seconds if user is in headful mode
            for _ in range(12):
                BrowserManager.human_delay(4.0, 6.0)
                if not any(x in page.url.lower() for x in ["checkpoint", "challenge", "login"]):
                    break

        current_url = page.url.lower()
        if any(x in current_url for x in ["/feed", "/jobs", "/in/", "/mynetwork"]):
            log.info("[bold green]✓ LinkedIn autonomous login successful![/bold green]")
            persist_session_cookies(page)
            return True
        elif "error" in current_url or page.locator("#error-for-username, #error-for-password").first.is_visible(timeout=1000):
            err_msg = page.locator("#error-for-username, #error-for-password").first.inner_text().strip()
            log.error(f"LinkedIn login failed: {err_msg}")
            return False

        # General auth indicator check
        if page.locator(".global-nav__me-photo, nav.global-nav, img.global-nav__me-photo").first.is_visible(timeout=3000):
            log.info("[bold green]✓ LinkedIn autonomous login verified by nav element![/bold green]")
            persist_session_cookies(page)
            return True

        return False
    except Exception as e:
        log.error(f"Error during autonomous LinkedIn login: {e}")
        return False

def auto_login_naukri(page: Page) -> bool:
    """
    Autonomously logs into Naukri.com using credentials from NAUKRI_USERNAME and NAUKRI_PASSWORD.
    Handles human typing cadence, error detection, and automatic session persistence.
    """
    user = os.getenv("NAUKRI_USERNAME")
    pwd = os.getenv("NAUKRI_PASSWORD")

    if not user or not pwd:
        log.debug("Naukri credentials not found in environment (NAUKRI_USERNAME / NAUKRI_PASSWORD).")
        return False

    log.info(f"[cyan]Attempting autonomous Naukri login for: {user}...[/cyan]")
    try:
        page.goto("https://www.naukri.com/nlogin/login", timeout=30000, wait_until="domcontentloaded")
        BrowserManager.human_delay(1.5, 2.5)

        # 1. Fill Username
        user_input = page.locator("#usernameField, input[placeholder*='Username'], input[placeholder*='Email']").first
        if not user_input.is_visible(timeout=5000):
            log.warning("Naukri username input field not found.")
            return False

        BrowserManager.human_type(user_input, user)
        BrowserManager.human_delay(0.5, 1.2)

        # 2. Fill Password
        pwd_input = page.locator("#passwordField, input[placeholder*='password'], input[type='password']").first
        if not pwd_input.is_visible(timeout=5000):
            log.warning("Naukri password input field not found.")
            return False

        BrowserManager.human_type(pwd_input, pwd)
        BrowserManager.human_delay(0.8, 1.5)

        # 3. Click Submit
        submit_btn = page.locator("button[type='submit'], button:has-text('Login')").first
        submit_btn.click()

        # 4. Wait for navigation
        page.wait_for_load_state("domcontentloaded", timeout=20000)
        BrowserManager.human_delay(3.0, 5.0)

        current_url = page.url.lower()
        if any(x in current_url for x in ["/mnjuser", "/homepage", "/my-naukri"]) and "nlogin" not in current_url:
            log.info("[bold green]✓ Naukri autonomous login successful![/bold green]")
            persist_session_cookies(page)
            return True

        if page.locator(".profile-name, .nI-gNb-drawer, .view-profile-wrapper").first.is_visible(timeout=3000):
            log.info("[bold green]✓ Naukri autonomous login verified by profile element![/bold green]")
            persist_session_cookies(page)
            return True

        log.warning(f"Naukri login incomplete. Current URL: {page.url}")
        return False
    except Exception as e:
        log.error(f"Error during autonomous Naukri login: {e}")
        return False
