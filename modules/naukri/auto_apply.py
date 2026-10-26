from typing import List, Optional
from playwright.sync_api import Page
from config.config import settings
from core.browser import BrowserManager
from core.logger import log
from core.storage import db

def apply_to_naukri_job(page: Page, job_url: str, job_title: str, company: str, job_id: str = "") -> str:
    """
    Attempts to apply to a single Naukri job posting.
    Returns status string: 'APPLIED', 'ALREADY_APPLIED', 'COMPANY_SITE', 'SKIPPED_QUESTIONNAIRE', or 'FAILED'.
    """
    if db.is_already_applied("naukri", job_url, job_id):
        log.info(f"Skipping already recorded job: {job_title} at {company}")
        return "ALREADY_APPLIED"

    try:
        log.info(f"[cyan]Opening Naukri job: {job_title} ({company})...[/cyan]")
        page.goto(job_url, timeout=30000, wait_until="domcontentloaded")
        BrowserManager.human_delay(2.0, 3.5)

        # Check if already applied on page
        already_applied_indicators = [
            "text='Already Applied'",
            "span:has-text('Already applied')",
            ".already-applied",
            "button:has-text('Already applied')",
        ]
        for sel in already_applied_indicators:
            if page.locator(sel).first.is_visible(timeout=1500):
                log.info(f"Already applied to {job_title} according to Naukri.")
                db.record_applied_job(
                    platform="naukri",
                    job_id=job_id,
                    job_title=job_title,
                    company=company,
                    job_url=job_url,
                    status="ALREADY_APPLIED",
                    notes="Detected previous application badge"
                )
                return "ALREADY_APPLIED"

        # Check for external company site button
        external_btn = page.locator("button:has-text('Apply on company site'), a:has-text('Apply on company site')").first
        if external_btn.is_visible(timeout=1500):
            log.info(f"Job redirects to external company website: {company}")
            db.record_applied_job(
                platform="naukri",
                job_id=job_id,
                job_title=job_title,
                company=company,
                job_url=job_url,
                status="COMPANY_SITE",
                notes="External company site apply"
            )
            return "COMPANY_SITE"

        # Locate Naukri direct apply button
        apply_btn_selectors = [
            "#apply-button",
            "button.apply-button",
            "button:has-text('Apply')",
            "div.apply-button-container button",
        ]
        apply_btn = None
        for sel in apply_btn_selectors:
            cand = page.locator(sel).first
            if cand.is_visible(timeout=1500):
                apply_btn = cand
                break

        if not apply_btn:
            log.warning(f"No direct apply button found for {job_title}.")
            db.record_applied_job(
                platform="naukri",
                job_id=job_id,
                job_title=job_title,
                company=company,
                job_url=job_url,
                status="NO_APPLY_BUTTON",
                notes="Could not locate standard apply button"
            )
            return "NO_APPLY_BUTTON"

        BrowserManager.safe_click(apply_btn)
        BrowserManager.human_delay(2.5, 4.0)

        # Handle questionnaire / chatbot modal if it pops up
        chatbot_or_modal = page.locator("div.chatbot_Drawer, div.apply-message, div.bot-container, div.drawer-wrapper").first
        if chatbot_or_modal.is_visible(timeout=2000):
            log.info("Detected screening questions / chatbot modal. Handling basic questions...")
            handled = handle_naukri_screening_modal(page)
            if not handled:
                log.warning("Complex screening questionnaire requires manual review. Skipping.")
                db.record_applied_job(
                    platform="naukri",
                    job_id=job_id,
                    job_title=job_title,
                    company=company,
                    job_url=job_url,
                    status="SKIPPED_QUESTIONNAIRE",
                    notes="Requires manual screening answers"
                )
                return "SKIPPED_QUESTIONNAIRE"

        # Check for success confirmation
        success_indicators = [
            "text='Successfully applied'",
            "text='Application sent'",
            "text='You have successfully applied'",
            ".apply-message",
            "span:has-text('Applied')",
        ]
        is_success = False
        for s_sel in success_indicators:
            if page.locator(s_sel).first.is_visible(timeout=2500):
                is_success = True
                break

        status = "APPLIED" if is_success else "APPLIED_PENDING_CONFIRMATION"
        log.info(f"[green]✓ {status}: {job_title} at {company}[/green]")
        db.record_applied_job(
            platform="naukri",
            job_id=job_id,
            job_title=job_title,
            company=company,
            job_url=job_url,
            status=status,
            notes="Direct 1-Click apply completed"
        )
        return status

    except Exception as e:
        log.error(f"[red]Error applying to Naukri job '{job_title}': {e}[/red]")
        db.record_applied_job(
            platform="naukri",
            job_id=job_id,
            job_title=job_title,
            company=company,
            job_url=job_url,
            status="FAILED",
            notes=str(e)
        )
        return "FAILED"

def handle_naukri_screening_modal(page: Page) -> bool:
    """Answers common screening questions or yields if custom essay is required."""
    try:
        # Check if simple numeric inputs exist
        inputs = page.locator("input[type='text'], input[type='number']").all()
        for inp in inputs:
            if not inp.is_visible():
                continue
            placeholder = (inp.get_attribute("placeholder") or "").lower()
            label = ""
            parent = inp.locator("xpath=..")
            if parent.is_visible():
                label = parent.inner_text().lower()

            combined = f"{placeholder} {label}"
            if "experience" in combined:
                inp.fill(str(settings.profile.years_of_experience))
            elif "notice" in combined:
                inp.fill(str(settings.profile.notice_period_days))
            elif "ctc" in combined or "salary" in combined:
                inp.fill(str(settings.profile.expected_salary_lpa))

        # Check for radio buttons with 'Yes'
        yes_radios = page.locator("label:has-text('Yes'), input[value*='yes' i]").all()
        for yr in yes_radios:
            if yr.is_visible():
                try:
                    yr.click()
                except Exception:
                    pass

        # Submit modal if a button exists
        submit_btn = page.locator("button:has-text('Submit and Apply'), button:has-text('Submit'), button:has-text('Save & Apply')").first
        if submit_btn.is_visible(timeout=2000):
            BrowserManager.safe_click(submit_btn)
            BrowserManager.human_delay(2.0, 3.0)
            return True

        return True
    except Exception as e:
        log.debug(f"Modal handler encountered: {e}")
        return False

def run_naukri_auto_apply(page: Page, limit: Optional[int] = None) -> int:
    """Scrapes jobs matching user configuration and auto-applies up to the specified limit."""
    max_apps = limit or settings.naukri.max_applications_per_run
    log.info(f"[bold cyan]Starting Naukri Auto-Apply (Target: up to {max_apps} applications)...[/bold cyan]")

    applied_count = 0
    from modules.naukri.scraper import scrape_naukri_jobs

    for kw in settings.naukri.search_keywords:
        for loc in settings.naukri.locations:
            if applied_count >= max_apps:
                break

            jobs = scrape_naukri_jobs(page, keyword=kw, location=loc, max_pages=1)
            for j in jobs:
                if applied_count >= max_apps:
                    break

                res = apply_to_naukri_job(
                    page=page,
                    job_url=j["job_url"],
                    job_title=j["job_title"],
                    company=j["company"],
                    job_id=j.get("job_id", "")
                )
                if res in ("APPLIED", "APPLIED_PENDING_CONFIRMATION"):
                    applied_count += 1
                BrowserManager.human_delay(2.0, 4.0)

    log.info(f"[bold green]✓ Naukri Auto-Apply completed. Total applied in this run: {applied_count}[/bold green]")
    return applied_count
