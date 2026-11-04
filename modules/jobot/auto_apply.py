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

def apply_to_jobot_job(page: Page, job_url: str, job_title: str, company: str, job_id: str = "", match_score: float = 0.0) -> str:
    """
    Attempts to apply to a Jobot job posting using Jobot's rapid apply flow or external ATS.
    Returns: 'APPLIED', 'ALREADY_APPLIED', 'NO_APPLY_BUTTON', 'SKIPPED_COMPLEX', or 'FAILED'.
    """
    if db.is_already_applied("jobot", job_url, job_id):
        log.info(f"Skipping already recorded job: {job_title} at {company}")
        return "ALREADY_APPLIED"

    try:
        score_tag = f" [AI Match: {match_score*100:.1f}%]" if match_score > 0 else ""
        log.info(f"[cyan]Opening Jobot job: {job_title} ({company}){score_tag}...[/cyan]")
        page.goto(job_url, timeout=30000, wait_until="domcontentloaded")
        BrowserManager.human_delay(2.0, 3.5)

        # Check if already applied
        applied_indicators = [
            "text='Application Submitted'",
            "span:has-text('Applied')",
            "div:has-text('You already applied')",
        ]
        for sel in applied_indicators:
            if page.locator(sel).first.is_visible(timeout=1500):
                log.info(f"Already applied to {job_title} on Jobot.")
                db.record_applied_job(
                    platform="jobot",
                    job_id=job_id,
                    job_title=job_title,
                    company=company,
                    job_url=job_url,
                    status="ALREADY_APPLIED",
                    notes="Detected Jobot applied indicator"
                )
                return "ALREADY_APPLIED"

        # Check for Apply button on Jobot page
        apply_selectors = [
            "button:has-text('Apply Now')",
            "button:has-text('Easy Apply')",
            "button:has-text('Quick Apply')",
            "button:has-text('Apply with 1-Click')",
            "a:has-text('Apply Now')",
            "button:has-text('Apply')",
        ]
        apply_btn = None
        for sel in apply_selectors:
            cand = page.locator(sel).first
            if cand.is_visible(timeout=1500):
                apply_btn = cand
                break

        if not apply_btn:
            log.warning(f"No direct apply button found for Jobot listing: {job_title}.")
            db.record_applied_job(
                platform="jobot",
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

        # 1. Resume upload in Jobot modal or drawer
        file_input = page.locator("input[type='file']").first
        if file_input.count() > 0:
            resume_file = Path(settings.profile.resume_path)
            if resume_file.exists():
                try:
                    file_input.set_input_files(str(resume_file))
                    BrowserManager.human_delay(1.5, 2.5)
                except Exception as e:
                    log.debug(f"Jobot resume upload note: {e}")

        # 2. Fill personal text fields
        inputs = page.locator("input[type='text']:visible, input[type='email']:visible, input[type='tel']:visible, input[type='number']:visible, textarea:visible").all()
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
            elif "salary" in combined or "compensation" in combined:
                inp.fill(str(settings.profile.expected_salary_lpa))
            elif "notice" in combined:
                inp.fill("Immediate")
            else:
                ans = ai_assistant.answer_question(combined or "Enter details", field_type="text")
                inp.fill(str(ans) if ans else "Yes")

        # 3. Handle selects
        for sel in page.locator("select:visible").all():
            opts = [o.inner_text().strip() for o in sel.locator("option").all() if o.inner_text().strip()]
            if opts:
                ans = ai_assistant.answer_question("Select option", field_type="dropdown", options=opts)
                try:
                    sel.select_option(label=ans)
                except Exception:
                    if len(opts) > 1:
                        sel.select_option(index=1)

        # 4. Check for Submit button
        submit_selectors = [
            "button:has-text('Submit Application')",
            "button:has-text('Submit')",
            "button:has-text('Complete Application')",
            "button[type='submit']",
        ]
        submit_btn = None
        for s_sel in submit_selectors:
            cand_s = page.locator(s_sel).first
            if cand_s.is_visible(timeout=1000):
                submit_btn = cand_s
                break

        if submit_btn:
            log.info("Submitting Jobot application...")
            BrowserManager.safe_click(submit_btn)
            BrowserManager.human_delay(3.0, 5.0)

            proof_path = "data/exports/proof_jobot_applied.png"
            try:
                page.screenshot(path=proof_path)
                log.info(f"[bold green]Saved live Jobot application proof to: {proof_path}[/bold green]")
            except Exception:
                pass

            log.info(f"[bold green]✓ Successfully applied to {job_title} on Jobot![/bold green]")
            db.record_applied_job(
                platform="jobot",
                job_id=job_id,
                job_title=job_title,
                company=company,
                job_url=job_url,
                status="SUBMITTED",
                notes="Completed Jobot application",
                match_score=match_score
            )
            return "SUBMITTED"

        # Check if external redirect occurred
        if "jobot.com" not in page.url:
            log.info("Jobot redirected to client career page. Handled via Universal ATS Applier...")
            return UniversalATSApplier.apply(page, page.url, job_title, company, job_id, match_score=match_score)

        db.record_applied_job(
            platform="jobot",
            job_id=job_id,
            job_title=job_title,
            company=company,
            job_url=job_url,
            status="SKIPPED_COMPLEX",
            notes="Form not submitted",
            match_score=match_score
        )
        return "SKIPPED_COMPLEX"

    except Exception as e:
        log.error(f"[red]Error applying to Jobot job '{job_title}': {e}[/red]")
        db.record_applied_job(
            platform="jobot",
            job_id=job_id,
            job_title=job_title,
            company=company,
            job_url=job_url,
            status="FAILED",
            notes=str(e),
            match_score=match_score
        )
        return "FAILED"

def run_jobot_auto_apply(page: Page, limit: Optional[int] = None) -> int:
    """Scrapes jobs matching user configuration and auto-applies up to the specified limit on Jobot."""
    max_apps = limit or 5
    max_inspected = max(max_apps * 3, 12)
    max_runtime_sec = 300
    start_time = time.time()

    log.info(f"[bold cyan]Starting Jobot Auto-Apply (Target: up to {max_apps} applications, max inspected: {max_inspected})...[/bold cyan]")

    applied_count = 0
    inspected_count = 0
    from modules.jobot.scraper import scrape_jobot_jobs

    keywords = getattr(getattr(settings, "jobot", None), "search_keywords", settings.naukri.search_keywords)
    locations = getattr(getattr(settings, "jobot", None), "locations", ["Remote", "India", "Pune", "Bengaluru"])

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

            jobs = scrape_jobot_jobs(page, keyword=kw, location=loc, max_jobs=12)
            ranked_jobs = ai_matcher.filter_and_rank_jobs(jobs)

            for j in ranked_jobs:
                if applied_count >= max_apps or inspected_count >= max_inspected or (time.time() - start_time) > max_runtime_sec:
                    stop_search = True
                    break

                inspected_count += 1
                res = apply_to_jobot_job(
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

    log.info(f"[bold green]✓ Jobot Auto-Apply complete. Total applied: {applied_count} (Inspected: {inspected_count})[/bold green]")
    try:
        db.record_profile_refresh("jobot", f"Jobot Cloud Apply session active ({applied_count} applied)")
    except Exception as e:
        log.debug(f"Profile refresh note: {e}")
    return applied_count
