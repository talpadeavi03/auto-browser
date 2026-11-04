import os
from typing import List, Optional
from playwright.sync_api import Page
from config.config import settings
from core.browser import BrowserManager
from core.logger import log
from core.storage import db
from core.ai_assistant import ai_assistant
from core.ai_matcher import ai_matcher
from core.auto_auth import auto_login_naukri, persist_session_cookies
from modules.naukri.profile_updater import is_naukri_logged_in
from modules.external.universal_apply import UniversalATSApplier

def _attempt_naukri_drawer_login(page: Page, drawer) -> bool:
    """Attempts to log into Naukri directly inside the login drawer if user credentials are present."""
    user = os.getenv("NAUKRI_USERNAME")
    pwd = os.getenv("NAUKRI_PASSWORD")
    if not user or not pwd or "example.com" in user or "your_" in user or "your_" in pwd:
        return False

    try:
        log.info(f"[cyan]Attempting in-drawer Naukri login for: {user}...[/cyan]")
        u_inp = drawer.locator("#usernameField, input[placeholder*='Username'], input[placeholder*='Email'], input[type='text']:visible").first
        if not u_inp.is_visible(timeout=2500):
            return False

        BrowserManager.human_type(u_inp, user)
        BrowserManager.human_delay(0.5, 1.0)

        p_inp = drawer.locator("#passwordField, input[placeholder*='password'], input[type='password']:visible").first
        if not p_inp.is_visible(timeout=2500):
            return False

        BrowserManager.human_type(p_inp, pwd)
        BrowserManager.human_delay(0.8, 1.2)

        login_btn = drawer.locator("button[type='submit'], button:has-text('Login')").first
        if login_btn.is_visible():
            login_btn.click()
        else:
            p_inp.press("Enter")

        BrowserManager.human_delay(3.0, 5.0)
        persist_session_cookies(page)

        if not drawer.is_visible(timeout=2000) or page.locator(".profile-name, .nI-gNb-drawer").first.is_visible(timeout=2000):
            log.info("[bold green]✓ In-drawer login succeeded![/bold green]")
            return True
        return False
    except Exception as e:
        log.warning(f"In-drawer login error: {e}")
        return False

def apply_to_naukri_job(page: Page, job_url: str, job_title: str, company: str, job_id: str = "", match_score: float = 0.0) -> str:
    """
    Attempts to apply to a single Naukri job posting.
    Returns status string: 'SUBMITTED', 'ALREADY_APPLIED', 'SKIPPED_QUESTIONNAIRE', or 'FAILED'.
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
                res = UniversalATSApplier.apply(ext_page, ext_page.url, job_title, company, job_id, match_score=match_score)
                ext_page.close()
                return res
            except Exception as ext_err:
                log.warning(f"Could not open external popup ({ext_err}). Trying in current tab...")
                ext_url = page.url
                return UniversalATSApplier.apply(page, ext_url, job_title, company, job_id, match_score=match_score)

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
            log.warning(f"Naukri session inactive (login drawer detected) for {job_title}. Attempting autonomous in-drawer login...")
            logged_in = _attempt_naukri_drawer_login(page, login_drawer)
            if not logged_in:
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
            log.info("✓ In-drawer login succeeded. Re-triggering apply button...")
            if apply_btn.is_visible():
                BrowserManager.safe_click(apply_btn)
                BrowserManager.human_delay(2.0, 3.5)

        # Handle questionnaire / chatbot modal if it pops up
        chatbot_or_modal = page.locator("div.chatbot_Drawer, div.apply-message, div.bot-container, div[class*='chatbot' i]").first
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
            "div.apply-message:has-text('applied')",
            "div.apply-message:has-text('successful')",
            "span:has-text('Applied')",
            "button:has-text('Applied')",
            ".already-applied",
            "text='Application submitted'",
            "div.applied-snippet",
            "div.banner-msg:has-text('applied')",
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
    """
    Intelligently handles multi-turn conversational screening questions
    in Naukri's chatbot drawer (div.chatbot_Drawer / bot-container).
    """
    try:
        drawer = page.locator("div.chatbot_Drawer, div.apply-message, div.bot-container, div[class*='chatbot' i]").first
        if not drawer.is_visible(timeout=2000):
            return True

        # Check if this is actually a login modal masquerading as screening
        if drawer.locator("#usernameField, input[type='password'], form:has-text('Login')").first.is_visible(timeout=800):
            log.warning("Detected login form inside drawer. User is not authenticated.")
            if _attempt_naukri_drawer_login(page, drawer):
                return True
            return False

        max_turns = 8
        for turn in range(1, max_turns + 1):
            BrowserManager.human_delay(1.5, 2.5)

            # Check if drawer has closed or dismissed
            if not drawer.is_visible(timeout=1000):
                log.info("Chatbot screening drawer dismissed/closed successfully.")
                return True

            # Check for success messages inside drawer
            try:
                drawer_text = drawer.inner_text().lower()
                if any(s in drawer_text for s in [
                    "successfully applied", "application sent", "you have successfully applied",
                    "thank you for answering", "response has been recorded", "application received"
                ]):
                    log.info(f"[green]✓ Screening chatbot confirmed submission: {drawer_text[:60]}[/green]")
                    close_btn = drawer.locator("button.crossIcon, button:has-text('Done'), .crossIcon, [aria-label='Close']").first
                    if close_btn.is_visible(timeout=1000):
                        BrowserManager.safe_click(close_btn)
                    return True
            except Exception:
                pass

            # Check for final submit / save button
            submit_btn = drawer.locator("button:has-text('Submit and Apply'), button:has-text('Save & Apply'), button:has-text('Submit'), button:has-text('Apply')").first
            if submit_btn.is_visible(timeout=1000):
                btn_txt = submit_btn.inner_text().strip()
                log.info(f"Turn {turn}: Found submit button '{btn_txt}'. Clicking...")
                BrowserManager.safe_click(submit_btn)
                BrowserManager.human_delay(2.0, 3.5)
                if not drawer.is_visible(timeout=2000):
                    return True
                continue

            # Identify the last bot question
            bot_msgs = drawer.locator(".bot-msg, .bot-message, .botMsg, div.msg, p.msg, div.content").all()
            last_question = ""
            for msg in reversed(bot_msgs):
                try:
                    t = msg.inner_text().strip()
                    if t and len(t) > 3:
                        last_question = t
                        break
                except Exception:
                    pass

            if last_question:
                log.info(f"Turn {turn}: Chatbot prompt: '{last_question[:80]}'...")

            # 1. Quick-Reply Chips / Buttons
            chips = drawer.locator("div.quick-replies button, ul.chips li, .chip, button.chip, span.chip, div.chips-container button, div[role='button']").all()
            visible_chips = [c for c in chips if c.is_visible()]
            if visible_chips:
                chip_texts = [c.inner_text().strip() for c in visible_chips]
                log.info(f"Turn {turn}: Available chatbot chips: {chip_texts}")

                chosen_chip = None
                yes_chip = next((c for c in visible_chips if c.inner_text().strip().lower() in ["yes", "हाँ", "y"]), None)
                no_chip = next((c for c in visible_chips if c.inner_text().strip().lower() in ["no", "नहीं", "n"]), None)
                q_lower = last_question.lower()

                if "sponsorship" in q_lower or "visa" in q_lower or "criminal" in q_lower:
                    chosen_chip = no_chip or visible_chips[0]
                elif yes_chip:
                    chosen_chip = yes_chip
                else:
                    if "notice" in q_lower or "availability" in q_lower or "join" in q_lower:
                        for c in visible_chips:
                            ct = c.inner_text().lower()
                            if any(k in ct for k in ["15", "immediate", "serving", "1 month", "30", "< 15"]):
                                chosen_chip = c
                                break
                    elif "experience" in q_lower or "exp" in q_lower:
                        for c in visible_chips:
                            ct = c.inner_text().lower()
                            if any(k in ct for k in ["3", "4", "3-5", "2-4", "3.5"]):
                                chosen_chip = c
                                break
                    if not chosen_chip and ai_assistant.is_active and chip_texts:
                        ai_choice = ai_assistant.answer_question(last_question or "Select screening option", field_type="dropdown", options=chip_texts)
                        if ai_choice:
                            chosen_chip = next((c for c in visible_chips if c.inner_text().strip().lower() == ai_choice.lower()), None)

                    if not chosen_chip:
                        chosen_chip = visible_chips[0]

                if chosen_chip:
                    log.info(f"Turn {turn}: Clicking chip: '{chosen_chip.inner_text().strip()}'")
                    BrowserManager.safe_click(chosen_chip)
                    BrowserManager.human_delay(1.5, 2.5)
                    continue

            # 2. Text / Numeric Input in Chatbot
            inputs = drawer.locator("input[type='text'], input[type='number'], textarea").all()
            visible_inputs = [inp for inp in inputs if inp.is_visible() and inp.is_editable()]
            if visible_inputs:
                inp = visible_inputs[0]
                q_lower = last_question.lower()
                placeholder = (inp.get_attribute("placeholder") or "").lower()
                ctx = f"{q_lower} {placeholder}"

                val_to_type = ""
                if "experience" in ctx or "exp" in ctx or "year" in ctx:
                    val_to_type = str(settings.profile.years_of_experience)
                elif "notice" in ctx or "days" in ctx or "join" in ctx:
                    val_to_type = str(settings.profile.notice_period_days)
                elif "expected" in ctx or "ctc" in ctx or "salary" in ctx:
                    val_to_type = str(settings.profile.expected_salary_lpa)
                elif "current ctc" in ctx or "current salary" in ctx:
                    val_to_type = str(settings.profile.current_salary_lpa)
                elif "location" in ctx or "city" in ctx:
                    val_to_type = settings.profile.location or "Pune"
                elif ai_assistant.is_active and last_question:
                    val_to_type = ai_assistant.answer_question(last_question, field_type="text") or "Yes"
                else:
                    val_to_type = "Yes"

                log.info(f"Turn {turn}: Answering '{val_to_type}' into chatbot input...")
                BrowserManager.human_type(inp, val_to_type)
                BrowserManager.human_delay(0.5, 1.0)

                send_btn = drawer.locator("button.send-btn, button[aria-label*='Send' i], .sendMsg, .send-icon, button[type='submit']").first
                if send_btn.is_visible(timeout=1000):
                    BrowserManager.safe_click(send_btn)
                else:
                    inp.press("Enter")
                BrowserManager.human_delay(1.5, 2.5)
                continue

            # 3. Radio Buttons inside Drawer
            radios = drawer.locator("label:has-text('Yes'), input[value*='yes' i], input[type='radio']").all()
            for r in radios:
                if r.is_visible():
                    r.click()
                    BrowserManager.human_delay(0.5, 1.0)

            BrowserManager.human_delay(1.5, 2.5)

        if not drawer.is_visible(timeout=1500):
            return True

        return False
    except Exception as e:
        log.debug(f"Chatbot drawer exception: {e}")
        return False

def run_naukri_auto_apply(page: Page, limit: Optional[int] = None) -> int:
    """Scrapes jobs matching user configuration and auto-applies up to the specified limit."""
    import time

    # Verify session authentication upfront
    if not is_naukri_logged_in(page, navigate=True):
        log.warning("Naukri session is not actively authenticated. Attempting auto-login...")
        if not auto_login_naukri(page):
            log.error("[bold red]❌ Cannot auto-apply on Naukri: session is not authenticated. Please configure NAUKRI_USERNAME & NAUKRI_PASSWORD secrets or export AUTH_STORAGE_STATE.[/bold red]")
            return 0

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
