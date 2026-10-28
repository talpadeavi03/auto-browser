import base64
import json
import os
import time
from pathlib import Path
from typing import Optional
from playwright.sync_api import Page
from config.config import settings
from core.browser import BrowserManager, clean_and_normalize_cookies
from core.logger import log

DEFAULT_GOOGLE_ACCOUNT = "talpadeavi0303@gmail.com"

def persist_session_cookies(page: Page) -> int:
    """Extracts, cleans, and persists active session cookies to data/auth_state.json and data/auth_secret_for_github.txt."""
    try:
        context = page.context
        cookies = context.cookies()
        cleaned = clean_and_normalize_cookies(cookies)
        if not cleaned:
            return 0

        payload = {"cookies": cleaned}
        json_str = json.dumps(payload, indent=2)
        b64_str = base64.b64encode(json_str.encode("utf-8")).decode("utf-8")

        data_dir = Path("data")
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "auth_state.json").write_text(json_str, encoding="utf-8")
        (data_dir / "auth_secret_for_github.txt").write_text(b64_str, encoding="utf-8")

        log.info(f"[bold green]✓ Automatically saved {len(cleaned)} cleaned session cookies to data/auth_state.json & data/auth_secret_for_github.txt![/bold green]")
        return len(cleaned)
    except Exception as e:
        log.warning(f"Could not persist session cookies: {e}")
        return 0

def login_with_google(page: Page, target_email: str = DEFAULT_GOOGLE_ACCOUNT) -> bool:
    """
    Executes autonomous Google OAuth sign-in flow.
    Clicks 'Sign in with Google' or 'Continue with Google', handles the Google popup/redirect,
    chooses the target Google account (talpadeavi0303@gmail.com), and approves authorization.
    """
    google_selectors = [
        "a.socialbtn.google",
        "a:has-text('Sign in with Google')",
        "button:has-text('Sign in with Google')",
        "button:has-text('Continue with Google')",
        "button.google-sign-in-btn",
        "div.nsm7Bb-HzV7m-LgbsSe",
        "#container-for-google-btn button",
        "a:has-text('Google')",
        "button:has-text('Google')",
    ]

    btn = None
    for sel in google_selectors:
        candidate = page.locator(sel).first
        if candidate.count() > 0 and candidate.is_visible():
            btn = candidate
            break

    # If top-level button not found, search inside Google GSI iframe (used by LinkedIn, etc.)
    if not btn:
        gsi_frames = [f for f in page.frames if "accounts.google.com/gsi/button" in f.url]
        for f in gsi_frames:
            cand = f.locator("div[role='button'], div.nsm7Bb-HzV7m-LgbsSe, [aria-labelledby*='button-label']").first
            if cand.count() > 0 and cand.is_visible():
                btn = cand
                break

    if not btn:
        return False

    log.info(f"[cyan]Found Google Sign-In button. Initiating Google OAuth for '{target_email}'...[/cyan]")
    try:
        context = page.context
        target_page = page
        try:
            with context.expect_page(timeout=8000) as popup_info:
                btn.click()
            popup = popup_info.value
            popup.wait_for_load_state("domcontentloaded", timeout=15000)
            target_page = popup
        except Exception:
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            target_page = page

        BrowserManager.human_delay(2.0, 3.5)

        # 1. Account Chooser
        acc_locators = [
            f":text('{target_email}')",
            f"[data-email*='{target_email}']",
            f"div[data-identifier*='{target_email}']",
            f"li:has-text('{target_email}')",
            ":text('Avinash Talpade')",
        ]
        chosen = False
        for loc in acc_locators:
            acc = target_page.locator(loc).first
            if acc.count() > 0 and acc.is_visible():
                log.info(f"Selecting Google account: {target_email}...")
                acc.click()
                chosen = True
                break

        # 2. If email input field is asked
        if not chosen:
            email_input = target_page.locator("input#identifierId, input[type='email'], input[name='identifier']").first
            if email_input.count() > 0 and email_input.is_visible(timeout=3000):
                log.info(f"Entering Google account email: {target_email}...")
                BrowserManager.human_type(email_input, target_email)
                BrowserManager.human_delay(0.5, 1.0)
                next_btn = target_page.locator("#identifierNext button, #identifierNext, button:has-text('Next')").first
                if next_btn.is_visible():
                    next_btn.click()
                BrowserManager.human_delay(2.0, 3.5)

        # 3. Handle 'Continue' / 'Allow' approval button if Google prompts
        consent_selectors = [
            "button:has-text('Continue')",
            "button:has-text('Allow')",
            "button:has-text('Confirm')",
            "#submit_approve_access",
        ]
        for c_sel in consent_selectors:
            c_btn = target_page.locator(c_sel).first
            if c_btn.count() > 0 and c_btn.is_visible():
                c_btn.click()
                BrowserManager.human_delay(2.0, 3.0)
                break

        # Wait for redirection back to platform
        page.wait_for_timeout(5000)
        persist_session_cookies(page)
        return True
    except Exception as e:
        log.warning(f"Google OAuth flow note: {e}")
        return False

def auto_login_linkedin(page: Page) -> bool:
    """
    Autonomously logs into LinkedIn using Google OAuth or direct credentials.
    """
    # 1. Try Google Sign-In first if available
    try:
        if "linkedin.com/login" not in page.url.lower():
            page.goto("https://www.linkedin.com/login", timeout=30000, wait_until="domcontentloaded")
            BrowserManager.human_delay(1.5, 2.5)
        if login_with_google(page, DEFAULT_GOOGLE_ACCOUNT):
            current_url = page.url.lower()
            if any(x in current_url for x in ["/feed", "/jobs", "/in/", "/mynetwork"]):
                log.info("[bold green]✓ LinkedIn Google OAuth login successful![/bold green]")
                persist_session_cookies(page)
                return True
    except Exception as g_err:
        log.debug(f"LinkedIn Google login attempt note: {g_err}")

    # 2. Fallback to direct credentials
    user = os.getenv("LINKEDIN_USERNAME") or getattr(settings.linkedin, "username", None)
    pwd = os.getenv("LINKEDIN_PASSWORD") or getattr(settings.linkedin, "password", None)

    if not user or not pwd or "example.com" in user or "your_" in user or "your_" in pwd:
        log.debug("LinkedIn real credentials not set in .env (contains template placeholder).")
        return False

    log.info(f"[cyan]Attempting autonomous LinkedIn credential login for: {user}...[/cyan]")
    try:
        page.goto("https://www.linkedin.com/login", timeout=30000, wait_until="domcontentloaded")
        BrowserManager.human_delay(1.5, 2.5)

        user_input = page.locator("#username, input[name='session_key'], input[id*='username']").first
        if not user_input.is_visible(timeout=5000):
            return False

        BrowserManager.human_type(user_input, user)
        BrowserManager.human_delay(0.5, 1.2)

        pwd_input = page.locator("#password, input[name='session_password'], input[id*='password']").first
        if not pwd_input.is_visible(timeout=5000):
            return False

        BrowserManager.human_type(pwd_input, pwd)
        BrowserManager.human_delay(0.8, 1.5)

        submit_btn = page.locator("button[type='submit'], button:has-text('Sign in'), button:has-text('Log in')").first
        submit_btn.click()

        page.wait_for_load_state("domcontentloaded", timeout=20000)
        BrowserManager.human_delay(3.0, 5.0)

        current_url = page.url.lower()
        if any(x in current_url for x in ["/feed", "/jobs", "/in/", "/mynetwork"]):
            log.info("[bold green]✓ LinkedIn autonomous login successful![/bold green]")
            persist_session_cookies(page)
            return True

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
    Autonomously logs into Naukri.com using Google OAuth or direct credentials.
    """
    try:
        page.goto("https://www.naukri.com/nlogin/login", timeout=30000, wait_until="domcontentloaded")
        BrowserManager.human_delay(1.5, 2.5)

        # 1. Try Google Sign-In first (Naukri socialbtn google)
        if login_with_google(page, DEFAULT_GOOGLE_ACCOUNT):
            current_url = page.url.lower()
            if any(x in current_url for x in ["/mnjuser", "/homepage", "/my-naukri"]) and "nlogin" not in current_url:
                log.info("[bold green]✓ Naukri Google OAuth login successful![/bold green]")
                persist_session_cookies(page)
                return True
            if page.locator(".profile-name, .nI-gNb-drawer, .view-profile-wrapper").first.is_visible(timeout=3000):
                log.info("[bold green]✓ Naukri Google OAuth verified by profile element![/bold green]")
                persist_session_cookies(page)
                return True
    except Exception as g_err:
        log.debug(f"Naukri Google login attempt note: {g_err}")

    # 2. Fallback to direct credentials
    user = os.getenv("NAUKRI_USERNAME")
    pwd = os.getenv("NAUKRI_PASSWORD")

    if not user or not pwd or "example.com" in user or "your_" in user or "your_" in pwd:
        log.debug("Naukri real credentials not set in .env (contains template placeholder).")
        return False

    log.info(f"[cyan]Attempting autonomous Naukri credential login for: {user}...[/cyan]")
    try:
        page.goto("https://www.naukri.com/nlogin/login", timeout=30000, wait_until="domcontentloaded")
        BrowserManager.human_delay(1.5, 2.5)

        user_input = page.locator("#usernameField, input[placeholder*='Username'], input[placeholder*='Email']").first
        if not user_input.is_visible(timeout=5000):
            return False

        BrowserManager.human_type(user_input, user)
        BrowserManager.human_delay(0.5, 1.2)

        pwd_input = page.locator("#passwordField, input[placeholder*='password'], input[type='password']").first
        if not pwd_input.is_visible(timeout=5000):
            return False

        BrowserManager.human_type(pwd_input, pwd)
        BrowserManager.human_delay(0.8, 1.5)

        submit_btn = page.locator("button[type='submit'], button:has-text('Login')").first
        submit_btn.click()

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

        return False
    except Exception as e:
        log.error(f"Error during autonomous Naukri login: {e}")
        return False
