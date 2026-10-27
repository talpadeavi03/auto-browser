import time
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
from config.config import settings
from core.browser import BrowserManager
from core.logger import log, console
from core.storage import db

NAUKRI_PROFILE_URL = "https://www.naukri.com/mnjuser/profile"
NAUKRI_LOGIN_URL = "https://www.naukri.com/nlogin/login"

def is_naukri_logged_in(page: Page, navigate: bool = False) -> bool:
    """Verifies whether the current session is actively authenticated on Naukri."""
    try:
        if navigate:
            page.goto(NAUKRI_PROFILE_URL, timeout=25000, wait_until="domcontentloaded")
            BrowserManager.human_delay(1.5, 2.5)

        current_url = page.url.lower()
        if "nlogin" in current_url or "login" in current_url:
            return False

        if any(x in current_url for x in ["/mnjuser", "/my-naukri", "/homepage"]):
            return True

        profile_indicators = [
            ".profile-name",
            ".view-profile-wrapper",
            "div.nI-gNb-drawer",
            "#lazyAttachCV",
            ".widgetHead",
        ]
        for sel in profile_indicators:
            if page.locator(sel).first.is_visible(timeout=1000):
                return True
        return "mnjuser/profile" in current_url
    except Exception as e:
        log.debug(f"Error checking Naukri login state: {e}")
        return False

def refresh_naukri_profile(page: Page) -> bool:
    """
    Refreshes Naukri profile by toggling a character in the Resume Headline
    and re-saving it. This triggers Naukri's algorithm to update the 'Last Updated'
    timestamp to today, boosting visibility in recruiter searches to the top.
    """
    log.info("[bold cyan]Starting Naukri Profile Refresh Booster...[/bold cyan]")
    try:
        page.goto(NAUKRI_PROFILE_URL, timeout=30000, wait_until="domcontentloaded")
        BrowserManager.human_delay(2.5, 4.0)

        if not is_naukri_logged_in(page):
            log.error("[bold red]Not logged into Naukri![/bold red] Please run 'python main.py login --platform naukri' first.")
            return False

        log.info("Navigated to profile. Locating Resume Headline section...")

        # Find the Resume Headline edit button
        # Multiple selector fallbacks for different Naukri UI themes
        edit_button_selectors = [
            "span.edit.icon:right-of(:text('Resume Headline'))",
            "div.widgetHead:has-text('Resume Headline') span.edit",
            "div.resumeHeadline span.edit",
            "span:has-text('Resume Headline') ~ span.edit",
            "div[data-section='resumeHeadline'] .edit",
            "//span[contains(text(), 'Resume Headline')]/following::span[contains(@class, 'edit')][1]"
        ]

        edit_btn = None
        for sel in edit_button_selectors:
            try:
                candidate = page.locator(sel).first
                if candidate.is_visible(timeout=2000):
                    edit_btn = candidate
                    break
            except Exception:
                continue

        if not edit_btn or not edit_btn.is_visible():
            # Try scrolling to reveal the widget
            log.info("Scrolling down to reveal Resume Headline...")
            BrowserManager.human_scroll(page, steps=3, distance=300)
            BrowserManager.human_delay(1.5, 2.5)
            for sel in edit_button_selectors:
                try:
                    candidate = page.locator(sel).first
                    if candidate.is_visible(timeout=2000):
                        edit_btn = candidate
                        break
                except Exception:
                    continue

        if not edit_btn:
            log.warning("Could not find standard Resume Headline edit button. Attempting direct modal trigger...")
            # Fallback: Try clicking anywhere in the resume headline preview or headline text
            headline_box = page.locator("div.resumeHeadline, div.widgetHead:has-text('Resume Headline')").first
            if headline_box.is_visible():
                edit_btn = headline_box.locator("text=Edit").first

        if not edit_btn:
            log.error("[red]Could not locate Resume Headline edit button on Naukri profile page.[/red]")
            return False

        BrowserManager.safe_click(edit_btn)
        BrowserManager.human_delay(1.5, 2.5)

        # Locate textarea
        textarea_selectors = [
            "#resumeHeadlineTxt",
            "textarea.resumeHeadlineTxt",
            "textarea[placeholder*='Resume Headline']",
            "div.modal textarea",
            "textarea",
        ]
        textarea = None
        for sel in textarea_selectors:
            candidate = page.locator(sel).first
            if candidate.is_visible(timeout=2000):
                textarea = candidate
                break

        if not textarea:
            log.error("[red]Could not find headline textarea in edit modal.[/red]")
            return False

        current_headline = textarea.input_value().strip()
        log.info(f"Current Headline length: {len(current_headline)} chars")

        # Toggle trailing period or space to trigger a change
        if current_headline.endswith("."):
            updated_headline = current_headline[:-1]
        else:
            updated_headline = current_headline + "."

        # Type the subtle update
        textarea.fill(updated_headline)
        BrowserManager.human_delay(1.0, 1.8)

        # Locate and click Save button
        save_btn_selectors = [
            "form[name='resumeHeadlineForm'] button:has-text('Save')",
            "div.action button:has-text('Save')",
            "button:has-text('Save')",
            ".btn-dark-ot:has-text('Save')",
        ]
        save_btn = None
        for sel in save_btn_selectors:
            candidate = page.locator(sel).first
            if candidate.is_visible(timeout=2000):
                save_btn = candidate
                break

        if not save_btn:
            log.error("[red]Could not find Save button on headline modal.[/red]")
            return False

        BrowserManager.safe_click(save_btn)
        BrowserManager.human_delay(2.0, 3.5)

        log.info("[bold green]✓ Naukri profile updated successfully![/bold green]")
        db.record_profile_refresh("naukri", f"Resume headline updated (length={len(updated_headline)})")
        return True

    except Exception as e:
        log.error(f"[red]Error during Naukri profile refresh: {e}[/red]")
        return False
