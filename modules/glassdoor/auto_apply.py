import os
import time
from pathlib import Path
from typing import List, Optional
from playwright.sync_api import Page, Locator
from config.config import settings
from core.browser import BrowserManager
from core.logger import log
from core.storage import db
from core.ai_assistant import ai_assistant
from core.ai_matcher import ai_matcher
from modules.external.universal_apply import UniversalATSApplier

def apply_to_glassdoor_job(page: Page, job_url: str, job_title: str, company: str, job_id: str = "", match_score: float = 0.0) -> str:
    """
    Attempts to apply to a single Glassdoor job posting via Easy Apply or External ATS.
    Returns: 'APPLIED', 'ALREADY_APPLIED', 'NO_APPLY_BUTTON', 'SKIPPED_COMPLEX', or 'FAILED'.
    """
    if db.is_already_applied("glassdoor", job_url, job_id):
        log.info(f"Skipping already recorded job: {job_title} at {company}")
        return "ALREADY_APPLIED"

    try:
        score_tag = f" [AI Match: {match_score*100:.1f}%]" if match_score > 0 else ""
        log.info(f"[cyan]Opening Glassdoor job: {job_title} ({company}){score_tag}...[/cyan]")
        page.goto(job_url, timeout=30000, wait_until="domcontentloaded")
        BrowserManager.human_delay(2.0, 3.5)

        # Close any modal overlay
        try:
            close_btn = page.locator("button.CloseButton, button[aria-label='Close'], [data-test='modal-close']").first
            if close_btn.is_visible(timeout=1500):
                close_btn.click()
        except Exception:
            pass

        # Check if already applied
        applied_indicators = [
            "text='Applied'",
            "span:has-text('Applied')",
            "div:has-text('You applied on')",
            "button:has-text('Applied')",
        ]
        for sel in applied_indicators:
            if page.locator(sel).first.is_visible(timeout=1500):
                log.info(f"Already applied to {job_title} at {company}.")
                db.record_applied_job(
                    platform="glassdoor",
                    job_id=job_id,
                    job_title=job_title,
                    company=company,
                    job_url=job_url,
                    status="ALREADY_APPLIED",
                    notes="Detected Glassdoor applied indicator"
                )
                return "ALREADY_APPLIED"

        # Check for External apply on company site
        external_btn = page.locator("button[data-test='apply-button']:not(:has-text('Easy Apply')), a[data-test='apply-button'], button:has-text('Apply on Company Site'), a:has-text('Apply on Company Site'), button:has-text('Apply on employer site')").first
        if external_btn.is_visible(timeout=1500):
            log.info(f"Glassdoor job redirects to external company website: {company}. Launching Universal ATS Applier...")
            try:
                with page.context.expect_page(timeout=7000) as ext_info:
                    BrowserManager.safe_click(external_btn)
                ext_page = ext_info.value
                ext_page.wait_for_load_state("domcontentloaded", timeout=20000)
                res = UniversalATSApplier.apply(ext_page, ext_page.url, job_title, company, job_id, match_score=match_score)
                ext_page.close()
                return res
            except Exception as ext_err:
                log.warning(f"External popup handling ({ext_err}). Trying in current tab...")
                ext_url = external_btn.get_attribute("href") or page.url
                return UniversalATSApplier.apply(page, ext_url, job_title, company, job_id, match_score=match_score)

        # Check for Easy Apply button
        easy_apply_selectors = [
            "button[data-test='easy-apply-button']",
            "button:has-text('Easy Apply')",
            "button:has-text('Quick Apply')",
            "button[data-test='apply-button']:has-text('Easy Apply')",
            "button:has-text('Apply Now')",
        ]
        apply_btn = None
        for sel in easy_apply_selectors:
            cand = page.locator(sel).first
            if cand.is_visible(timeout=1500):
                apply_btn = cand
                break

        if not apply_btn:
            log.warning(f"No direct apply button found for Glassdoor listing: {job_title}.")
            db.record_applied_job(
                platform="glassdoor",
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

        # Multi-step apply modal
        step = 0
        max_steps = 6
        while step < max_steps:
            step += 1
            log.info(f"Glassdoor Apply: Step {step}...")
            BrowserManager.human_delay(1.5, 2.5)

            # 1. Resume upload
            file_input = page.locator("input[type='file']").first
            if file_input.count() > 0:
                resume_file = Path(settings.profile.resume_path)
                if resume_file.exists():
                    try:
                        file_input.set_input_files(str(resume_file))
                        BrowserManager.human_delay(1.5, 2.5)
                    except Exception as e:
                        log.debug(f"Glassdoor resume upload note: {e}")

            # 2. Text fields
            inputs = page.locator("input[type='text']:visible, input[type='number']:visible, input[type='tel']:visible, input[type='email']:visible, textarea:visible").all()
            for inp in inputs:
                if inp.input_value().strip():
                    continue
                lbl = (inp.get_attribute("aria-label") or inp.get_attribute("name") or inp.get_attribute("placeholder") or "").lower()
                parent = inp.locator("xpath=..")
                p_text = parent.inner_text().strip().lower() if parent.count() > 0 else ""
                combined = f"{lbl} {p_text}".strip()

                if "first name" in combined:
                    inp.fill(settings.profile.first_name)
                elif "last name" in combined:
                    inp.fill(settings.profile.last_name)
                elif "name" in combined:
                    inp.fill(f"{settings.profile.first_name} {settings.profile.last_name}")
                elif "email" in combined:
                    inp.fill(settings.profile.email)
                elif "phone" in combined or "mobile" in combined:
                    inp.fill(settings.profile.phone)
                elif "city" in combined or "location" in combined:
                    inp.fill(settings.profile.city)
                elif "notice" in combined or "days" in combined:
                    inp.fill("0" if "day" in combined else str(settings.profile.notice_period_days))
                elif "experience" in combined or "years" in combined:
                    inp.fill(str(settings.profile.years_of_experience))
                elif "salary" in combined or "ctc" in combined:
                    inp.fill(str(settings.profile.expected_salary_lpa))
                else:
                    ans = ai_assistant.answer_question(combined or "Enter answer", field_type="text")
                    inp.fill(str(ans) if ans else "Yes")

            # 3. Dropdowns
            selects = page.locator("select:visible").all()
            for sel in selects:
                options = [o.inner_text().strip() for o in sel.locator("option").all() if o.inner_text().strip()]
                if options:
                    ans = ai_assistant.answer_question("Select option", field_type="dropdown", options=options)
                    try:
                        sel.select_option(label=ans)
                    except Exception:
                        if len(options) > 1:
                            sel.select_option(index=1)

            # 4. Check for Submit button
            submit_selectors = [
                "button:has-text('Submit Application')",
                "button:has-text('Submit application')",
                "button:has-text('Submit')",
                "button[type='submit']:has-text('Submit')",
                "button:has-text('Send Application')",
            ]
            submit_btn = None
            for s_sel in submit_selectors:
                cand_s = page.locator(s_sel).first
                if cand_s.is_visible(timeout=1000):
                    submit_btn = cand_s
                    break

            if submit_btn:
                log.info("Reached Glassdoor submit step. Submitting application...")
                BrowserManager.safe_click(submit_btn)
                BrowserManager.human_delay(3.0, 5.0)

                proof_path = "data/exports/proof_glassdoor_applied.png"
                try:
                    page.screenshot(path=proof_path)
                    log.info(f"[bold green]Saved live Glassdoor application proof to: {proof_path}[/bold green]")
                except Exception:
                    pass

                log.info(f"[bold green]✓ Successfully applied to {job_title} at {company} on Glassdoor![/bold green]")
                db.record_applied_job(
                    platform="glassdoor",
                    job_id=job_id,
                    job_title=job_title,
                    company=company,
                    job_url=job_url,
                    status="SUBMITTED",
                    notes="Completed Glassdoor apply flow",
                    match_score=match_score
                )
                return "SUBMITTED"

            # 5. Check for Next / Continue / Review button
            next_selectors = [
                "button:has-text('Continue')",
                "button:has-text('Next')",
                "button:has-text('Review')",
                "button[type='submit']",
            ]
            next_btn = None
            for n_sel in next_selectors:
                cand_n = page.locator(n_sel).first
                if cand_n.is_visible(timeout=1000):
                    next_btn = cand_n
                    break

            if next_btn:
                BrowserManager.safe_click(next_btn)
                continue

            break

        # Check for success screen
        success_msg = page.locator("*:has-text('Your application has been submitted'), *:has-text('Application sent')").first
        if success_msg.is_visible(timeout=2000):
            db.record_applied_job(
                platform="glassdoor",
                job_id=job_id,
                job_title=job_title,
                company=company,
                job_url=job_url,
                status="SUBMITTED",
                notes="Glassdoor application confirmed",
                match_score=match_score
            )
            return "SUBMITTED"

        log.warning(f"Could not complete Glassdoor application for {job_title}.")
        db.record_applied_job(
            platform="glassdoor",
            job_id=job_id,
            job_title=job_title,
            company=company,
            job_url=job_url,
            status="SKIPPED_COMPLEX",
            notes="Wizard stopped before submit",
            match_score=match_score
        )
        return "SKIPPED_COMPLEX"

    except Exception as e:
        log.error(f"[red]Error during Glassdoor apply for '{job_title}': {e}[/red]")
        db.record_applied_job(
            platform="glassdoor",
            job_id=job_id,
            job_title=job_title,
            company=company,
            job_url=job_url,
            status="FAILED",
            notes=str(e),
            match_score=match_score
        )
        return "FAILED"

def run_glassdoor_auto_apply(page: Page, limit: Optional[int] = None) -> int:
    """Scrapes jobs matching user configuration and auto-applies up to the specified limit on Glassdoor."""
    max_apps = limit or 5
    max_inspected = max(max_apps * 3, 12)
    max_runtime_sec = 300
    start_time = time.time()

    log.info(f"[bold cyan]Starting Glassdoor Auto-Apply (Target: up to {max_apps} applications, max inspected: {max_inspected})...[/bold cyan]")

    applied_count = 0
    inspected_count = 0
    from modules.glassdoor.scraper import scrape_glassdoor_jobs

    keywords = getattr(getattr(settings, "glassdoor", None), "search_keywords", settings.naukri.search_keywords)
    locations = getattr(getattr(settings, "glassdoor", None), "locations", ["Pune", "Bengaluru", "Remote", "India"])

    stop_search = False
    for kw in keywords:
        if stop_search:
            break
        for loc in locations:
            if stop_search:
                break

            if applied_count >= max_apps or inspected_count >= max_inspected or (time.time() - start_time) > max_runtime_sec:
                stop_search = True
                break

            jobs = scrape_glassdoor_jobs(page, keyword=kw, location=loc, max_jobs=12)
            ranked_jobs = ai_matcher.filter_and_rank_jobs(jobs)

            for j in ranked_jobs:
                if applied_count >= max_apps or inspected_count >= max_inspected or (time.time() - start_time) > max_runtime_sec:
                    stop_search = True
                    break

                inspected_count += 1
                res = apply_to_glassdoor_job(
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

    log.info(f"[bold green]✓ Glassdoor Auto-Apply complete. Total applied: {applied_count} (Inspected: {inspected_count})[/bold green]")
    try:
        db.record_profile_refresh("glassdoor", f"Glassdoor Cloud Apply session active ({applied_count} applied)")
    except Exception as e:
        log.debug(f"Profile refresh note: {e}")
    return applied_count
