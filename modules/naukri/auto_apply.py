from typing import List, Optional
from playwright.sync_api import Page
from config.config import settings
from core.browser import BrowserManager
from core.logger import log
from core.storage import db
from core.ai_assistant import ai_assistant
from core.ai_matcher import ai_matcher
from modules.external.universal_apply import UniversalATSApplier

def apply_to_naukri_job(page: Page, job_url: str, job_title: str, company: str, job_id: str = "", match_score: float = 0.0) -> str:
    """
    Attempts to apply to a single Naukri job posting.
    Returns status string: 'APPLIED', 'ALREADY_APPLIED', 'COMPANY_SITE', 'SKIPPED_QUESTIONNAIRE', or 'FAILED'.
    """
    if db.is_already_applied("naukri", job_url, job_id):
        log.info(f"Skipping already recorded job: {job_title} at {company}")
        return "ALREADY_APPLIED"

    try:
        score_tag = f" [AI Match: {match_score*100:.1f}%]" if match_score > 0 else ""
        log.info(f"[cyan]Opening Naukri job: {job_title} ({company}){score_tag}...[/cyan]")
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
            log.info(f"Job redirects to external company website: {company}. Launching Universal ATS Applier...")
            try:
                with page.context.expect_page(timeout=6000) as new_page_info:
                    BrowserManager.safe_click(external_btn)
                ext_page = new_page_info.value
                ext_page.wait_for_load_state("domcontentloaded")
                res = UniversalATSApplier.apply(ext_page, ext_page.url, job_title, company, job_id)
                ext_page.close()
                return res
            except Exception as ext_err:
                log.warning(f"Could not open external popup ({ext_err}). Trying in current tab...")
                ext_url = page.url
                return UniversalATSApplier.apply(page, ext_url, job_title, company, job_id)

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

        # Check for unauthenticated login drawer (Naukri opens drawer-wrapper with login form if user session expired)
        login_drawer = page.locator("div.drawer-wrapper:has-text('Login'), div.drawer-wrapper:has(input[type='password']), #usernameField, form:has-text('Login to apply')").first
        if login_drawer.is_visible(timeout=1500):
            log.warning(f"❌ Naukri session is unauthenticated (login drawer detected) for {job_title}. Cannot apply without active session.")
            db.record_applied_job(
                platform="naukri",
                job_id=job_id,
                job_title=job_title,
                company=company,
                job_url=job_url,
                status="FAILED_AUTH_REQUIRED",
                notes="Naukri session expired or unauthenticated: login drawer appeared on apply"
            )
            return "FAILED_AUTH_REQUIRED"

        # Handle questionnaire / chatbot modal if it pops up
        chatbot_or_modal = page.locator("div.chatbot_Drawer, div.apply-message, div.bot-container").first
        if chatbot_or_modal.is_visible(timeout=2000):
            log.info("Detected screening questions / chatbot modal. Handling questions...")
            handled = handle_naukri_screening_modal(page)
            if not handled:
                log.warning("Screening questionnaire requires manual review or could not be completed. Skipping.")
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

        # Check for success confirmation or updated UI
        success_indicators = [
            "text='Successfully applied'",
            "text='Application sent'",
            "text='You have successfully applied'",
            ".apply-message",
            "span:has-text('Applied')",
            "button:has-text('Applied')",
            ".already-applied",
        ]
        is_success = False
        for s_sel in success_indicators:
            try:
                if page.locator(s_sel).first.is_visible(timeout=2500):
                    is_success = True
                    break
            except Exception:
                pass

        if is_success:
            status = "SUBMITTED"
            note_details = "Direct 1-Click apply submitted and verified"
            if match_score > 0:
                note_details += f" | AI Match: {match_score*100:.1f}%"
            log.info(f"[bold green]✓ {status}: {job_title} at {company}[/bold green]")
        else:
            status = "FAILED_UNCONFIRMED"
            note_details = "Apply button clicked but application was not confirmed by Naukri"
            log.warning(f"⚠️ {status}: {job_title} at {company} (could not verify server confirmation)")

        db.record_applied_job(
            platform="naukri",
            job_id=job_id,
            job_title=job_title,
            company=company,
            job_url=job_url,
            status=status,
            notes=note_details,
            match_score=match_score
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
        # Check if this is actually a login modal masquerading as screening
        if page.locator("#usernameField, input[type='password'], form:has-text('Login')").first.is_visible(timeout=1000):
            log.warning("Detected login form inside drawer. User is not authenticated.")
            return False

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

            combined = f"{placeholder} {label}".strip()
            if "experience" in combined:
                inp.fill(str(settings.profile.years_of_experience))
            elif "notice" in combined:
                inp.fill(str(settings.profile.notice_period_days))
            elif "ctc" in combined or "salary" in combined:
                inp.fill(str(settings.profile.expected_salary_lpa))
            elif ai_assistant.is_active and combined:
                ai_val = ai_assistant.answer_question(combined, field_type="text")
                if ai_val:
                    inp.fill(ai_val)

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

        # Check for send button in chatbot
        send_btn = page.locator("button.send-btn, button[aria-label*='Send' i], .sendMsg, .send-icon").first
        if send_btn.is_visible(timeout=1500):
            BrowserManager.safe_click(send_btn)
            BrowserManager.human_delay(2.0, 3.0)
            return True

        # If chatbot/modal is still open and unsubmitted, return False
        if page.locator("div.chatbot_Drawer, div.apply-message, div.bot-container").first.is_visible(timeout=1000):
            log.warning("Screening modal is still open. Could not locate submit action.")
            return False

        return True
    except Exception as e:
        log.debug(f"Modal handler encountered: {e}")
        return False

def run_naukri_auto_apply(page: Page, limit: Optional[int] = None) -> int:
    """Scrapes jobs matching user configuration and auto-applies up to the specified limit."""
    import time
    max_apps = limit or settings.naukri.max_applications_per_run
    max_inspected = max(max_apps * 3, 12)
    max_runtime_sec = 300 # 5 minutes hard safety timeout
    start_time = time.time()

    log.info(f"[bold cyan]Starting Naukri Auto-Apply (Target: up to {max_apps} applications, max inspected: {max_inspected})...[/bold cyan]")

    applied_count = 0
    inspected_count = 0
    from modules.naukri.scraper import scrape_naukri_jobs

    stop_search = False
    for kw in settings.naukri.search_keywords:
        if stop_search:
            break
        for loc in settings.naukri.locations:
            if stop_search:
                break

            if applied_count >= max_apps or inspected_count >= max_inspected or (time.time() - start_time) > max_runtime_sec:
                stop_search = True
                break

            jobs = scrape_naukri_jobs(page, keyword=kw, location=loc, max_pages=1)
            ranked_jobs = ai_matcher.filter_and_rank_jobs(jobs)
            for j in ranked_jobs:
                if applied_count >= max_apps or inspected_count >= max_inspected or (time.time() - start_time) > max_runtime_sec:
                    stop_search = True
                    break

                inspected_count += 1
                res = apply_to_naukri_job(
                    page=page,
                    job_url=j["job_url"],
                    job_title=j["job_title"],
                    company=j["company"],
                    job_id=j.get("job_id", ""),
                    match_score=j.get("match_score", 0.0)
                )
                if res in ("APPLIED", "SUBMITTED"):
                    applied_count += 1
                BrowserManager.human_delay(2.0, 3.5)

    log.info(f"[bold green]✓ Naukri Auto-Apply completed. Total applied in this run: {applied_count} (Inspected: {inspected_count})[/bold green]")
    return applied_count
