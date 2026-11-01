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

def apply_to_indeed_job(page: Page, job_url: str, job_title: str, company: str, job_id: str = "", match_score: float = 0.0) -> str:
    """
    Attempts to apply to a single Indeed job posting via Indeed Apply or External ATS.
    Returns: 'APPLIED', 'ALREADY_APPLIED', 'NO_APPLY_BUTTON', 'SKIPPED_COMPLEX', or 'FAILED'.
    """
    if db.is_already_applied("indeed", job_url, job_id):
        log.info(f"Skipping already recorded job: {job_title} at {company}")
        return "ALREADY_APPLIED"

    try:
        score_tag = f" [AI Match: {match_score*100:.1f}%]" if match_score > 0 else ""
        log.info(f"[cyan]Opening Indeed job: {job_title} ({company}){score_tag}...[/cyan]")
        page.goto(job_url, timeout=30000, wait_until="domcontentloaded")
        BrowserManager.human_delay(2.0, 3.5)

        # Check if already applied
        applied_indicators = [
            "text='You applied'",
            "span:has-text('Applied')",
            "div:has-text('You have applied')",
            "button:has-text('Applied')",
        ]
        for sel in applied_indicators:
            if page.locator(sel).first.is_visible(timeout=1500):
                log.info(f"Already applied to {job_title} at {company}.")
                db.record_applied_job(
                    platform="indeed",
                    job_id=job_id,
                    job_title=job_title,
                    company=company,
                    job_url=job_url,
                    status="ALREADY_APPLIED",
                    notes="Detected Indeed applied badge"
                )
                return "ALREADY_APPLIED"

        # Check for External apply on company site
        external_btn = page.locator("button:has-text('Apply on company site'), a:has-text('Apply on company site'), button[aria-label*='Apply on company site' i]").first
        if external_btn.is_visible(timeout=1500):
            log.info(f"Job redirects to external employer ATS: {company}. Launching Universal ATS Applier...")
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

        # Check for Indeed Apply / Easily Apply button
        apply_btn_selectors = [
            "#indeedApplyButton",
            "button:has-text('Apply now')",
            "button:has-text('Easily apply')",
            "button[id*='indeedApply']",
            "div.ia-ApplyButton button",
            "button:has-text('Apply')",
        ]
        apply_btn = None
        for sel in apply_btn_selectors:
            cand = page.locator(sel).first
            if cand.is_visible(timeout=1500):
                apply_btn = cand
                break

        if not apply_btn:
            log.warning(f"No direct apply button found for Indeed listing: {job_title}.")
            db.record_applied_job(
                platform="indeed",
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

        # Wizard multi-step modal loop (up to 7 steps)
        step = 0
        max_steps = 7
        while step < max_steps:
            step += 1
            log.info(f"Indeed Apply: Processing step {step}...")
            BrowserManager.human_delay(1.5, 2.5)

            # 1. Resume upload if requested
            file_input = page.locator("input[type='file']").first
            if file_input.count() > 0:
                resume_file = Path(settings.profile.resume_path)
                if resume_file.exists():
                    try:
                        file_input.set_input_files(str(resume_file))
                        BrowserManager.human_delay(1.5, 2.5)
                    except Exception as e:
                        log.debug(f"Indeed resume upload note: {e}")

            # 2. Text and number inputs
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
                elif "full name" in combined or "name" in combined:
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
                    ans = ai_assistant.answer_question(combined or "Enter details", field_type="text")
                    inp.fill(str(ans) if ans else "Yes")

            # 3. Dropdowns
            selects = page.locator("select:visible").all()
            for sel in selects:
                options = [o.inner_text().strip() for o in sel.locator("option").all() if o.inner_text().strip()]
                if options:
                    ans = ai_assistant.answer_question("Select the best option", field_type="dropdown", options=options)
                    try:
                        sel.select_option(label=ans)
                    except Exception:
                        if len(options) > 1:
                            sel.select_option(index=1)

            # 4. Radios
            radios = page.locator("input[type='radio']:visible, div[role='radio']:visible").all()
            if radios:
                yes_opt = page.locator("label:has-text('Yes'), div[role='radio']:has-text('Yes'), input[value*='yes' i]").first
                if yes_opt.is_visible():
                    try:
                        yes_opt.click()
                    except Exception:
                        pass

            # 5. Check for Submit button
            submit_selectors = [
                "button:has-text('Submit your application')",
                "button:has-text('Submit')",
                "button[type='submit']:has-text('Submit')",
                "button:has-text('Apply now')",
            ]
            submit_btn = None
            for s_sel in submit_selectors:
                cand_s = page.locator(s_sel).first
                if cand_s.is_visible(timeout=1000):
                    submit_btn = cand_s
                    break

            if submit_btn:
                log.info("Reached Indeed review/submit step. Submitting application...")
                BrowserManager.safe_click(submit_btn)
                BrowserManager.human_delay(3.0, 5.0)

                proof_path = "data/exports/proof_indeed_applied.png"
                try:
                    page.screenshot(path=proof_path)
                    log.info(f"[bold green]Saved live Indeed application proof to: {proof_path}[/bold green]")
                except Exception:
                    pass

                log.info(f"[bold green]✓ Successfully applied to {job_title} at {company} via Indeed Apply![/bold green]")
                db.record_applied_job(
                    platform="indeed",
                    job_id=job_id,
                    job_title=job_title,
                    company=company,
                    job_url=job_url,
                    status="APPLIED",
                    notes="Completed Indeed Apply flow",
                    match_score=match_score
                )
                return "APPLIED"

            # 6. Check for Next / Continue / Review button
            next_selectors = [
                "button:has-text('Continue')",
                "button:has-text('Next')",
                "button:has-text('Review your application')",
                "button:has-text('Review')",
                "#ia-container button[type='submit']",
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

            # If no forward button is found
            break

        # Check for success screen
        success_msg = page.locator("*:has-text('Your application has been submitted'), *:has-text('Application submitted')").first
        if success_msg.is_visible(timeout=2000):
            db.record_applied_job(
                platform="indeed",
                job_id=job_id,
                job_title=job_title,
                company=company,
                job_url=job_url,
                status="APPLIED",
                notes="Indeed application confirmed",
                match_score=match_score
            )
            return "APPLIED"

        log.warning(f"Could not complete Indeed application for {job_title}.")
        db.record_applied_job(
            platform="indeed",
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
        log.error(f"[red]Error during Indeed apply for '{job_title}': {e}[/red]")
        db.record_applied_job(
            platform="indeed",
            job_id=job_id,
            job_title=job_title,
            company=company,
            job_url=job_url,
            status="FAILED",
            notes=str(e),
            match_score=match_score
        )
        return "FAILED"

def run_indeed_auto_apply(page: Page, limit: Optional[int] = None) -> int:
    """Scrapes jobs matching user configuration and auto-applies up to the specified limit on Indeed."""
    max_apps = limit or 5
    max_inspected = max(max_apps * 3, 12)
    max_runtime_sec = 300
    start_time = time.time()

    log.info(f"[bold cyan]Starting Indeed Auto-Apply (Target: up to {max_apps} applications, max inspected: {max_inspected})...[/bold cyan]")

    applied_count = 0
    inspected_count = 0
    from modules.indeed.scraper import scrape_indeed_jobs

    keywords = getattr(getattr(settings, "indeed", None), "search_keywords", settings.naukri.search_keywords)
    locations = getattr(getattr(settings, "indeed", None), "locations", ["Pune", "Bengaluru", "Remote", "India"])

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

            jobs = scrape_indeed_jobs(page, keyword=kw, location=loc, max_pages=1)
            # Filter and rank by AI compatibility
            ranked_jobs = ai_matcher.filter_and_rank_jobs(jobs)

            for j in ranked_jobs:
                if applied_count >= max_apps or inspected_count >= max_inspected or (time.time() - start_time) > max_runtime_sec:
                    stop_search = True
                    break

                inspected_count += 1
                res = apply_to_indeed_job(
                    page=page,
                    job_url=j["job_url"],
                    job_title=j["job_title"],
                    company=j["company"],
                    job_id=j.get("job_id", ""),
                    match_score=j.get("match_score", 0.0)
                )
                if res in ("APPLIED", "APPLIED_PENDING_CONFIRMATION"):
                    applied_count += 1
                BrowserManager.human_delay(2.5, 4.0)

    log.info(f"[bold green]✓ Indeed Auto-Apply complete. Total applied: {applied_count} (Inspected: {inspected_count})[/bold green]")
    try:
        db.record_profile_refresh("indeed", f"Indeed Cloud Apply session active ({applied_count} applied)")
    except Exception as e:
        log.debug(f"Profile refresh note: {e}")
    return applied_count
