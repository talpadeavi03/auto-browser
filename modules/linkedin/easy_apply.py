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
from core.ai_matcher import ai_matcher
from modules.external.universal_apply import UniversalATSApplier

def apply_to_linkedin_easy_apply(page: Page, job_url: str, job_title: str, company: str, job_id: str = "", match_score: float = 0.0) -> str:
    """
    Automates the LinkedIn 'Easy Apply' multi-step flow for a job listing.
    Returns: 'APPLIED', 'ALREADY_APPLIED', 'NO_EASY_APPLY', 'SKIPPED_COMPLEX', or 'FAILED'.
    """
    if db.is_already_applied("linkedin", job_url, job_id):
        log.info(f"Skipping already applied job: {job_title} at {company}")
        return "ALREADY_APPLIED"

    try:
        score_tag = f" [AI Match: {match_score*100:.1f}%]" if match_score > 0 else ""
        log.info(f"[cyan]Navigating to LinkedIn job: {job_title} ({company}){score_tag}...[/cyan]")
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

        # Locate Easy Apply button (supports both English and regional/Bengali interface)
        easy_apply_selectors = [
            "button.jobs-apply-button",
            "button:has-text('Easy Apply')",
            "button:has-text('সহজে আবেদন জানান')",
            ".jobs-s-apply button:has-text('Easy Apply')",
            ".jobs-s-apply button:has-text('সহজে আবেদন জানান')",
            "div.jobs-apply-button--top-card button",
        ]

        apply_btn = None
        for sel in easy_apply_selectors:
            candidate = page.locator(sel).first
            if candidate.is_visible(timeout=1500):
                btn_text = candidate.inner_text().strip().lower()
                if any(x in btn_text for x in ["easy apply", "সহজে আবেদন"]):
                    apply_btn = candidate
                    break
                elif "apply" in btn_text and "easy" in btn_text:
                    apply_btn = candidate
                    break

        if not apply_btn:
            # Check for external Apply CTA on LinkedIn
            ext_apply = page.locator("button:has-text('Apply'), a:has-text('Apply')").first
            if ext_apply.is_visible(timeout=1500):
                log.info(f"External Apply detected for {job_title} ({company}). Launching Universal ATS Applier...")
                try:
                    with page.context.expect_page(timeout=6000) as new_page_info:
                        BrowserManager.safe_click(ext_apply)
                    ext_page = new_page_info.value
                    ext_page.wait_for_load_state("domcontentloaded")
                    res = UniversalATSApplier.apply(ext_page, ext_page.url, job_title, company, job_id, match_score=match_score)
                    ext_page.close()
                    return res
                except Exception as ext_err:
                    log.warning(f"Could not open external page ({ext_err}). Trying in current tab...")
                    ext_url = ext_apply.get_attribute("href") or page.url
                    return UniversalATSApplier.apply(page, ext_url, job_title, company, job_id, match_score=match_score)

            log.info(f"No Apply button available for {job_title}.")
            db.record_applied_job(
                platform="linkedin",
                job_id=job_id,
                job_title=job_title,
                company=company,
                job_url=job_url,
                status="NO_APPLY_BUTTON",
                notes="Could not locate apply button"
            )
            return "NO_APPLY_BUTTON"

        BrowserManager.safe_click(apply_btn)
        BrowserManager.human_delay(2.0, 3.5)

        # Modal / Form container detection (supports HTML5 dialog, classic modal, and modern drawer)
        wizard_active = False
        modal_candidates = [
            "div.jobs-easy-apply-modal",
            "div[role='dialog']",
            "dialog",
            "[data-view-name='job-application-modal']",
            "button:has-text('Submit application')",
            "button:has-text('Review')",
            "button:has-text('Next')",
        ]
        for sel in modal_candidates:
            try:
                candidate = page.locator(sel).first
                if candidate.is_visible(timeout=2000):
                    wizard_active = True
                    break
            except Exception:
                pass

        if not wizard_active:
            log.warning("Easy Apply form/modal did not appear.")
            return "FAILED"

        modal = page.locator("dialog, div.jobs-easy-apply-modal, div[role='dialog'], [data-view-name='job-application-modal'], form:has(button:has-text('Next')), body").first

        # Wizard Loop: Process up to 8 steps
        step_count = 0
        max_steps = 8

        while step_count < max_steps:
            step_count += 1
            log.info(f"[cyan]=== Processing Wizard Step {step_count} ===[/cyan]")
            BrowserManager.human_delay(1.0, 2.0)

            # Step A: Answer form fields on current step
            fill_current_step_fields(page, modal)

            # Step B: Check for 'Submit application' button (English, Bengali, and generic aria)
            submit_btn = page.locator("button:has-text('Submit application'), button:has-text('আবেদন জমা দিন'), button[aria-label*='Submit' i], button[aria-label*='জমা দিন']").first
            is_submit_visible = False
            try:
                if submit_btn.is_visible(timeout=1500):
                    is_submit_visible = True
            except Exception:
                pass

            if not is_submit_visible:
                # Scroll dialog down to reveal footer submit button if needed
                try:
                    modal.evaluate("el => el.scrollTo(0, el.scrollHeight)")
                    BrowserManager.human_delay(0.5, 1.0)
                    if submit_btn.is_visible(timeout=1500):
                        is_submit_visible = True
                except Exception:
                    pass

            if is_submit_visible:
                log.info("Reached final review step. Submitting application...")
                submit_btn.scroll_into_view_if_needed()
                BrowserManager.safe_click(submit_btn)
                BrowserManager.human_delay(3.0, 5.0)

                # Capture submission proof screenshot
                proof_path = "data/exports/proof_linkedin_applied.png"
                try:
                    page.screenshot(path=proof_path)
                    log.info(f"[bold green]Saved live LinkedIn application proof to: {proof_path}[/bold green]")
                except Exception:
                    pass

                # Close post-apply popup or 'Done' dialog if present and verify submission
                confirmed = False
                for _ in range(3):
                    try:
                        done_btn = page.locator("button:has-text('Done'), button:has-text('সম্পন্ন'), button[aria-label*='Dismiss' i]").first
                        if done_btn.is_visible(timeout=1500):
                            confirmed = True
                            BrowserManager.safe_click(done_btn)
                            break
                        if page.locator("text*='Application sent', text*='Application submitted', text*='was sent to', .artdeco-toast-item").first.is_visible(timeout=1500):
                            confirmed = True
                            break
                        if not modal.is_visible(timeout=1000):
                            confirmed = True
                            break
                    except Exception:
                        pass
                    BrowserManager.human_delay(0.8, 1.2)

                if confirmed:
                    status = "SUBMITTED"
                    note_details = f"Easy Apply submitted and verified | AI Match: {match_score*100:.1f}%" if match_score > 0 else "Completed Easy Apply"
                    log.info(f"[bold green]✓ Successfully applied to: {job_title} at {company} via Easy Apply![/bold green]")
                else:
                    status = "FAILED_UNCONFIRMED"
                    note_details = "Submit application was clicked but confirmation dialog did not appear"
                    log.warning(f"⚠️ Easy Apply unconfirmed for {job_title} at {company}")

                db.record_applied_job(
                    platform="linkedin",
                    job_id=job_id,
                    job_title=job_title,
                    company=company,
                    job_url=job_url,
                    status=status,
                    notes=note_details,
                    match_score=match_score
                )
                return status

            # Step C: Check for 'Review' button (English, Bengali, and generic aria)
            review_btn = page.locator("button:has-text('Review'), button:has-text('পর্যালোচনা'), button[aria-label*='Review' i], button[aria-label*='পর্যালোচনা']").first
            is_review_visible = False
            try:
                if review_btn.is_visible(timeout=1500):
                    is_review_visible = True
            except Exception:
                pass

            if is_review_visible:
                log.info(f"Found Review button on step {step_count}. Clicking Review...")
                BrowserManager.safe_click(review_btn)
                continue

            # Step D: Check for 'Next' button (English, Bengali, and generic aria)
            next_btn = page.locator("button:has-text('Next'), button:has-text('পরবর্তী'), button[aria-label*='Continue' i], button[aria-label*='Next' i], button[aria-label*='পরবর্তী']").first
            is_next_visible = False
            try:
                if next_btn.is_visible(timeout=1500):
                    is_next_visible = True
            except Exception:
                pass

            if is_next_visible:
                log.info(f"Found Next button on step {step_count}. Clicking Next...")
                BrowserManager.safe_click(next_btn)
                continue

            # If none of Next/Review/Submit are visible, check for errors or unknown blocking step
            error_msg = page.locator(".artdeco-inline-feedback--error, [aria-invalid='true']").first
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
    """Fills out standard questions on the active modal page with AI and smart heuristics."""
    try:
        # 1. Phone number field
        phone_inputs = modal.locator("input[id*='phoneNumber'], input[name*='phone' i], input[aria-label*='phone' i]").all()
        for p_inp in phone_inputs:
            if p_inp.is_visible() and not p_inp.input_value().strip():
                p_inp.scroll_into_view_if_needed()
                p_inp.fill(settings.profile.phone)

        # 2. Text & Numeric inputs (Years of experience, CTC, Notice period, Commute)
        text_inputs = modal.locator("input[type='text'], input[type='number'], textarea").all()
        for inp in text_inputs:
            if not inp.is_visible():
                continue
            
            # If already filled, skip
            if inp.input_value().strip():
                continue

            inp.scroll_into_view_if_needed()

            # Check label, aria-label, aria-labelledby, placeholder, or parent
            label_text = (inp.get_attribute("aria-label") or "").strip()
            if not label_text:
                lbl_id = inp.get_attribute("aria-labelledby") or ""
                if lbl_id:
                    lbl_elem = modal.locator(f"#{lbl_id}").first
                    if lbl_elem.is_visible():
                        label_text = lbl_elem.inner_text().strip()

            if not label_text:
                inp_id = inp.get_attribute("id") or ""
                if inp_id:
                    lbl_elem = modal.locator(f"label[for='{inp_id}']").first
                    if lbl_elem.is_visible():
                        label_text = lbl_elem.inner_text().strip()

            if not label_text:
                parent = inp.locator("xpath=../..").first
                if parent.is_visible():
                    label_text = parent.inner_text().strip()

            label_lower = label_text.lower()

            # Smart answering based on context
            if "how many years" in label_lower or "total experience" in label_lower or "experience" in label_lower:
                inp.fill(str(settings.profile.years_of_experience))
            elif "current ctc" in label_lower or "current salary" in label_lower:
                inp.fill(str(settings.profile.current_salary_lpa))
            elif "expected ctc" in label_lower or "expected salary" in label_lower:
                inp.fill(str(settings.profile.expected_salary_lpa))
            elif "how soon" in label_lower or "notice" in label_lower or "days" in label_lower or "যোগদান" in label_lower:
                val = str(settings.profile.notice_period_days)
                if "day" in label_lower or "দিন" in label_lower:
                    if "immediate" in val.lower():
                        inp.fill("0")
                    else:
                        digits = "".join(filter(str.isdigit, val))
                        inp.fill(digits or "0")
                else:
                    inp.fill(val)
            elif "travel time" in label_lower or "commute" in label_lower or "minutes" in label_lower:
                inp.fill("30")
            elif ai_assistant.is_active and label_text:
                # Use Gemini AI for custom/non-standard questions
                ai_val = ai_assistant.answer_question(label_text, field_type="text")
                if ai_val:
                    inp.fill(str(ai_val))
                else:
                    inp.fill("3")
            else:
                inp.fill("3")

        # 3. Radio options (Modern 2026 role='radio', fieldset, or custom choices)
        radio_groups = modal.locator("fieldset, [role='radiogroup']").all()
        for group in radio_groups:
            if not group.is_visible():
                continue
            group.scroll_into_view_if_needed()
            
            # Extract question text from previous element, legend, or group text
            question_text = group.evaluate('''el => {
                let prev = el.previousElementSibling;
                if (prev && prev.innerText.trim()) return prev.innerText.trim();
                let legend = el.querySelector('legend');
                if (legend && legend.innerText.trim()) return legend.innerText.trim();
                return el.innerText.trim();
            }''').lower()

            # Check if any radio in this group is already selected
            has_checked = group.locator("input[type='radio']:checked, div[role='radio'][aria-checked='true']").count() > 0
            if has_checked:
                continue

            # Check if this is a Resume selection group (LinkedIn presents saved resumes as radio cards)
            if any(w in question_text for w in ["resume", "cv", "choose a resume", "select resume", "upload resume"]):
                first_resume_opt = group.locator("div[role='radio'], input[type='radio'], label").first
                if first_resume_opt.is_visible():
                    try:
                        first_resume_opt.scroll_into_view_if_needed()
                        first_resume_opt.click()
                    except Exception:
                        pass
                    continue

            # Determine desired choice (Yes vs No or custom option)
            target_choice = "Yes"
            if "sponsorship" in question_text or "visa" in question_text:
                target_choice = "Yes" if settings.profile.require_visa_sponsorship else "No"
            elif "criminal" in question_text or "felony" in question_text:
                target_choice = "No"
            elif ai_assistant.is_active:
                # Sanitize question text
                clean_q = question_text.strip()
                if len(clean_q) >= 4 and clean_q.lower() not in ["pdf", "doc", "docx", "file", "upload"]:
                    options = [lbl.inner_text().strip() for lbl in group.locator("div[role='radio'], label, p").all() if lbl.inner_text().strip() in ["Yes", "No"]]
                    if options:
                        ai_choice = ai_assistant.answer_question(clean_q, field_type="radio", options=options)
                        if ai_choice:
                            target_choice = ai_choice

            # Click the matching radio or container
            target_elem = group.locator(f"div[role='radio']:has-text('{target_choice}'), label:has-text('{target_choice}'), p:has-text('{target_choice}')").first
            if target_elem.is_visible():
                target_elem.scroll_into_view_if_needed()
                target_elem.click()
            else:
                # Fallback click on radio input
                r_inp = group.locator(f"input[type='radio'][value*='{target_choice.lower()}']").first
                if r_inp.is_visible():
                    r_inp.scroll_into_view_if_needed()
                    r_inp.click()

        # 4. Resume upload if required and file input exists
        file_input = modal.locator("input[type='file']").first
        if file_input.is_visible() or file_input.count() > 0:
            resume_candidates = [
                Path(settings.profile.resume_path),
                Path("data/resumes/AT_26_AI.pdf"),
                Path("data/resumes/resume.pdf"),
                Path("resume.pdf"),
            ]
            resume_file = next((p for p in resume_candidates if p.exists() and p.is_file()), None)
            if resume_file:
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

            # If dropdown already has a valid pre-selected choice (like candidate email or +91 country code), keep it!
            cur_val = sel.evaluate("el => el.value")
            cur_text = sel.evaluate("el => el.options[el.selectedIndex]?.text || ''").strip().lower()
            if cur_val and not any(k in cur_text for k in ["select", "choose", "নির্বাচন"]):
                continue

            sel.scroll_into_view_if_needed()
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

def dismiss_modal(page: Page, modal: Optional[Locator] = None):
    """Safely closes modal and confirms discard so session remains clean."""
    try:
        close_btn = page.locator("button[aria-label*='Dismiss' i], button.artdeco-modal__dismiss, button[aria-label*='Close' i], button[aria-label*='বাতিল' i], dialog button[aria-label*='Dismiss' i]").first
        if close_btn.is_visible(timeout=1500):
            BrowserManager.safe_click(close_btn)
            BrowserManager.human_delay(1.0, 1.8)

            discard_btn = page.locator("button[data-control-name='discard_application_confirm_btn'], button:has-text('Discard'), button:has-text('বাতিল করুন')").first
            if discard_btn.is_visible(timeout=2000):
                BrowserManager.safe_click(discard_btn)
                BrowserManager.human_delay(1.0, 1.5)
    except Exception as e:
        log.debug(f"Dismiss modal handling: {e}")

def run_linkedin_easy_apply(page: Page, limit: Optional[int] = None) -> int:
    """Scrapes matching LinkedIn jobs and applies via Easy Apply up to the limit."""
    import time
    from modules.linkedin.scraper import is_linkedin_logged_in
    from core.auto_auth import auto_login_linkedin

    if not is_linkedin_logged_in(page, navigate=True):
        log.warning("LinkedIn session is not actively authenticated. Attempting auto-login...")
        if not auto_login_linkedin(page):
            log.error("[bold red]❌ Cannot auto-apply on LinkedIn: session is not authenticated. Please configure LINKEDIN_LI_AT or credentials in GitHub Secrets.[/bold red]")
            return 0

    max_apps = limit or settings.linkedin.max_applications_per_run
    max_inspected = max(max_apps * 3, 12)
    max_runtime_sec = 300 # 5 minutes hard safety timeout
    start_time = time.time()

    log.info(f"[bold cyan]Starting LinkedIn Easy Apply (Target: up to {max_apps} applications, max inspected: {max_inspected})...[/bold cyan]")

    applied_count = 0
    inspected_count = 0
    from modules.linkedin.scraper import scrape_linkedin_jobs

    stop_search = False
    for kw in settings.linkedin.search_keywords:
        if stop_search:
            break
        for loc in settings.linkedin.locations:
            if stop_search:
                break

            if applied_count >= max_apps or inspected_count >= max_inspected or (time.time() - start_time) > max_runtime_sec:
                stop_search = True
                break

            BrowserManager.human_delay(2.0, 3.5)
            jobs = scrape_linkedin_jobs(page, keyword=kw, location=loc, max_jobs=max_apps * 2)
            ranked_jobs = ai_matcher.filter_and_rank_jobs(jobs)
            for j in ranked_jobs:
                if applied_count >= max_apps or inspected_count >= max_inspected or (time.time() - start_time) > max_runtime_sec:
                    stop_search = True
                    break

                inspected_count += 1
                res = apply_to_linkedin_easy_apply(
                    page=page,
                    job_url=j["job_url"],
                    job_title=j["job_title"],
                    company=j["company"],
                    job_id=j.get("job_id", ""),
                    match_score=j.get("match_score", 0.0)
                )
                if res in ("APPLIED", "SUBMITTED"):
                    applied_count += 1
                BrowserManager.human_delay(2.5, 4.0)

    log.info(f"[bold green]✓ LinkedIn Easy Apply run complete. Total applied: {applied_count} (Inspected: {inspected_count})[/bold green]")
    try:
        db.record_profile_refresh("linkedin", f"Cloud Easy Apply session active ({applied_count} applied)")
    except Exception as ref_err:
        log.debug(f"Profile refresh record note: {ref_err}")
    return applied_count
