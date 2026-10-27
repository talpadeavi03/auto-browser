import os
import time
from typing import Optional
from pathlib import Path
from playwright.sync_api import Page, Locator
from config.config import settings
from core.browser import BrowserManager
from core.logger import log
from core.storage import db
from core.ai_assistant import ai_assistant

def apply_to_linkedin_easy_apply(page: Page, job_url: str, job_title: str, company: str, job_id: str = "") -> str:
    """
    Automates the LinkedIn 'Easy Apply' multi-step flow for a job listing.
    Returns: 'APPLIED', 'ALREADY_APPLIED', 'NO_EASY_APPLY', 'SKIPPED_COMPLEX', or 'FAILED'.
    """
    if db.is_already_applied("linkedin", job_url, job_id):
        log.info(f"Skipping already applied job: {job_title} at {company}")
        return "ALREADY_APPLIED"

    try:
        log.info(f"[cyan]Navigating to LinkedIn job: {job_title} ({company})...[/cyan]")
        page.goto(job_url, timeout=30000, wait_until="domcontentloaded")
        BrowserManager.human_delay(2.5, 4.0)

        # Check if already applied
        applied_badge = page.locator("span.artdeco-inline-feedback__message:has-text('Applied'), span:has-text('Applied on')").first
        if applied_badge.is_visible(timeout=1500):
            log.info(f"Already applied to {job_title} at {company}.")
            db.record_applied_job(
                platform="linkedin",
                job_id=job_id,
                job_title=job_title,
                company=company,
                job_url=job_url,
                status="ALREADY_APPLIED",
                notes="LinkedIn badge confirms already applied"
            )
            return "ALREADY_APPLIED"

        # Locate Easy Apply button
        easy_apply_selectors = [
            "button.jobs-apply-button",
            "button:has-text('Easy Apply')",
            ".jobs-s-apply button:has-text('Easy Apply')",
            "div.jobs-apply-button--top-card button",
        ]

        apply_btn = None
        for sel in easy_apply_selectors:
            candidate = page.locator(sel).first
            if candidate.is_visible(timeout=1500):
                # Verify it does not say just "Apply" (which redirects externally)
                btn_text = candidate.inner_text().strip()
                if "easy apply" in btn_text.lower():
                    apply_btn = candidate
                    break

        if not apply_btn:
            log.info(f"No Easy Apply button available for {job_title} (requires external application).")
            db.record_applied_job(
                platform="linkedin",
                job_id=job_id,
                job_title=job_title,
                company=company,
                job_url=job_url,
                status="NO_EASY_APPLY",
                notes="Requires external application"
            )
            return "NO_EASY_APPLY"

        BrowserManager.safe_click(apply_btn)
        BrowserManager.human_delay(2.0, 3.5)

        # Modal container
        modal = page.locator("div.jobs-easy-apply-modal, div[role='dialog']:has-text('Easy Apply')").first
        if not modal.is_visible(timeout=4000):
            log.warning("Easy Apply modal did not appear.")
            return "FAILED"

        # Wizard Loop: Process up to 8 steps
        step_count = 0
        max_steps = 8

        while step_count < max_steps:
            step_count += 1
            BrowserManager.human_delay(1.0, 2.0)

            # Step A: Answer form fields on current step
            fill_current_step_fields(page, modal)

            # Step B: Check for 'Submit application' button
            submit_btn = modal.locator("button:has-text('Submit application'), button[aria-label*='Submit application']").first
            if submit_btn.is_visible(timeout=1500):
                log.info("Reached final review step. Submitting application...")
                BrowserManager.safe_click(submit_btn)
                BrowserManager.human_delay(3.0, 5.0)

                # Close post-apply popup or 'Done' dialog if present
                done_btn = page.locator("button:has-text('Done'), button[aria-label='Dismiss']").first
                if done_btn.is_visible(timeout=3000):
                    BrowserManager.safe_click(done_btn)

                log.info(f"[bold green]✓ Successfully applied to: {job_title} at {company} via Easy Apply![/bold green]")
                db.record_applied_job(
                    platform="linkedin",
                    job_id=job_id,
                    job_title=job_title,
                    company=company,
                    job_url=job_url,
                    status="APPLIED",
                    notes="Completed Easy Apply"
                )
                return "APPLIED"

            # Step C: Check for 'Review' button
            review_btn = modal.locator("button:has-text('Review'), button[aria-label*='Review']").first
            if review_btn.is_visible(timeout=1500):
                BrowserManager.safe_click(review_btn)
                continue

            # Step D: Check for 'Next' button
            next_btn = modal.locator("button:has-text('Next'), button[aria-label*='Continue to next step']").first
            if next_btn.is_visible(timeout=1500):
                BrowserManager.safe_click(next_btn)
                continue

            # If none of Next/Review/Submit are visible, check for errors or unknown blocking step
            error_msg = modal.locator(".artdeco-inline-feedback--error").first
            if error_msg.is_visible(timeout=1000):
                log.warning(f"Unresolved mandatory field or screening quiz on step {step_count}: {error_msg.inner_text().strip()}")
                dismiss_modal(page, modal)
                db.record_applied_job(
                    platform="linkedin",
                    job_id=job_id,
                    job_title=job_title,
                    company=company,
                    job_url=job_url,
                    status="SKIPPED_COMPLEX",
                    notes="Mandatory unanswered screening questions"
                )
                return "SKIPPED_COMPLEX"

            break

        # If loop ended without submission
        log.warning(f"Exceeded max steps ({max_steps}) or encountered unsupported complex step.")
        dismiss_modal(page, modal)
        db.record_applied_job(
            platform="linkedin",
            job_id=job_id,
            job_title=job_title,
            company=company,
            job_url=job_url,
            status="SKIPPED_COMPLEX",
            notes="Wizard exceeded step limit"
        )
        return "SKIPPED_COMPLEX"

    except Exception as e:
        log.error(f"[red]Error during LinkedIn Easy Apply for '{job_title}': {e}[/red]")
        try:
            modal = page.locator("div.jobs-easy-apply-modal").first
            if modal.is_visible():
                dismiss_modal(page, modal)
        except Exception:
            pass

        db.record_applied_job(
            platform="linkedin",
            job_id=job_id,
            job_title=job_title,
            company=company,
            job_url=job_url,
            status="FAILED",
            notes=str(e)
        )
        return "FAILED"

def fill_current_step_fields(page: Page, modal: Locator):
    """Fills out standard questions on the active modal page."""
    try:
        # 1. Phone number field
        phone_inputs = modal.locator("input[id*='phoneNumber'], input[name*='phone' i]").all()
        for p_inp in phone_inputs:
            if p_inp.is_visible() and not p_inp.input_value().strip():
                p_inp.fill(settings.profile.phone)

        # 2. Numeric inputs (Years of experience, CTC, Notice period)
        text_inputs = modal.locator("input[type='text'], input[type='number']").all()
        for inp in text_inputs:
            if not inp.is_visible():
                continue
            
            # If already filled, skip
            if inp.input_value().strip():
                continue

            # Check label or aria-label
            lbl_id = inp.get_attribute("aria-labelledby") or ""
            label_text = ""
            if lbl_id:
                lbl_elem = modal.locator(f"#{lbl_id}").first
                if lbl_elem.is_visible():
                    label_text = lbl_elem.inner_text().lower()

            if not label_text:
                parent = inp.locator("xpath=../..").first
                if parent.is_visible():
                    label_text = parent.inner_text().lower()

            # Smart answering based on context
            if "how many years" in label_text or "experience" in label_text:
                inp.fill(str(settings.profile.years_of_experience))
            elif "notice" in label_text:
                inp.fill(str(settings.profile.notice_period_days))
            elif "salary" in label_text or "ctc" in label_text or "compensation" in label_text:
                inp.fill(str(settings.profile.expected_salary_lpa))
            elif ai_assistant.is_active and label_text:
                # Use Gemini AI for custom/non-standard questions
                ai_val = ai_assistant.answer_question(label_text, field_type="text")
                if ai_val:
                    inp.fill(ai_val)

        # 3. Radio options (Yes / No or custom choices)
        radio_groups = modal.locator("fieldset").all()
        for group in radio_groups:
            if not group.is_visible():
                continue
            grp_text = group.inner_text().lower()

            # If Gemini is active, let it choose the optimal option among labels
            options = [lbl.inner_text().strip() for lbl in group.locator("label").all() if lbl.is_visible()]
            if ai_assistant.is_active and options:
                best_choice = ai_assistant.answer_question(group.inner_text().split("\n")[0], field_type="radio", options=options)
                matched_lbl = group.locator(f"label:has-text('{best_choice}')").first
                if matched_lbl.is_visible():
                    try:
                        matched_lbl.click()
                        continue
                    except Exception:
                        pass

            # Fallback heuristic matching
            # Sponsorship questions -> usually No
            if "sponsorship" in grp_text or "visa" in grp_text:
                target_choice = "yes" if settings.profile.require_visa_sponsorship else "no"
            # Authorization / Legally permitted -> usually Yes
            elif "authorized" in grp_text or "legally" in grp_text or "clearance" in grp_text:
                target_choice = "yes" if settings.profile.authorized_to_work else "no"
            # Commute / comfortable with role -> Yes
            elif "comfortable" in grp_text or "commute" in grp_text or "relocate" in grp_text:
                target_choice = "yes"
            else:
                target_choice = "yes"

            choice_radio = group.locator(f"label:has-text('{target_choice.capitalize()}'), input[value*='{target_choice}' i]").first
            if choice_radio.is_visible():
                try:
                    choice_radio.click()
                except Exception:
                    pass

        # 4. Resume upload if required and file input exists
        file_input = modal.locator("input[type='file']").first
        if file_input.is_visible() or file_input.count() > 0:
            resume_file = Path(settings.profile.resume_path)
            if resume_file.exists():
                try:
                    file_input.set_input_files(str(resume_file))
                    BrowserManager.human_delay(1.5, 2.5)
                except Exception as upload_err:
                    log.debug(f"Resume upload note: {upload_err}")

        # 5. Dropdown selectors
        selects = modal.locator("select").all()
        for sel in selects:
            if not sel.is_visible():
                continue
            options = [o.inner_text().strip() for o in sel.locator("option").all() if o.inner_text().strip()]
            
            # Let Gemini pick the best dropdown option
            if ai_assistant.is_active and options:
                sel_lbl = sel.get_attribute("aria-label") or ""
                chosen_opt = ai_assistant.answer_question(sel_lbl or "Select the best option", field_type="dropdown", options=options)
                try:
                    sel.select_option(label=chosen_opt)
                    continue
                except Exception:
                    pass

            # Fallback heuristic
            opt_elements = sel.locator("option").all()
            if len(opt_elements) > 1:
                try:
                    val = opt_elements[1].get_attribute("value")
                    if val:
                        sel.select_option(value=val)
                except Exception:
                    pass

    except Exception as e:
        log.debug(f"Encountered minor error filling step: {e}")

def dismiss_modal(page: Page, modal: Locator):
    """Safely closes modal and confirms discard so session remains clean."""
    try:
        close_btn = modal.locator("button[aria-label='Dismiss'], button.artdeco-modal__dismiss").first
        if close_btn.is_visible():
            BrowserManager.safe_click(close_btn)
            BrowserManager.human_delay(1.0, 1.8)

            discard_btn = page.locator("button[data-control-name='discard_application_confirm_btn'], button:has-text('Discard')").first
            if discard_btn.is_visible(timeout=2000):
                BrowserManager.safe_click(discard_btn)
                BrowserManager.human_delay(1.0, 1.5)
    except Exception as e:
        log.debug(f"Dismiss modal handling: {e}")

def run_linkedin_easy_apply(page: Page, limit: Optional[int] = None) -> int:
    """Scrapes matching LinkedIn jobs and applies via Easy Apply up to the limit."""
    max_apps = limit or settings.linkedin.max_applications_per_run
    log.info(f"[bold cyan]Starting LinkedIn Easy Apply (Target: up to {max_apps} applications)...[/bold cyan]")

    applied_count = 0
    from modules.linkedin.scraper import scrape_linkedin_jobs

    for kw in settings.linkedin.search_keywords:
        for loc in settings.linkedin.locations:
            if applied_count >= max_apps:
                break

            jobs = scrape_linkedin_jobs(page, keyword=kw, location=loc, max_jobs=15)
            for j in jobs:
                if applied_count >= max_apps:
                    break

                res = apply_to_linkedin_easy_apply(
                    page=page,
                    job_url=j["job_url"],
                    job_title=j["job_title"],
                    company=j["company"],
                    job_id=j.get("job_id", "")
                )
                if res == "APPLIED":
                    applied_count += 1
                BrowserManager.human_delay(3.0, 6.0)

    log.info(f"[bold green]✓ LinkedIn Easy Apply run complete. Total applied: {applied_count}[/bold green]")
    return applied_count
