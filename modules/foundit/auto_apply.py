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

def apply_to_foundit_job(page: Page, job_url: str, job_title: str, company: str, job_id: str = "", match_score: float = 0.0) -> str:
    """
    Attempts to apply to a single Foundit (Monster) job posting.
    Returns: 'APPLIED', 'ALREADY_APPLIED', 'NO_APPLY_BUTTON', 'SKIPPED_COMPLEX', or 'FAILED'.
    """
    if db.is_already_applied("foundit", job_url, job_id):
        log.info(f"Skipping already recorded job: {job_title} at {company}")
        return "ALREADY_APPLIED"

    try:
        score_tag = f" [AI Match: {match_score*100:.1f}%]" if match_score > 0 else ""
        log.info(f"[cyan]Opening Foundit job: {job_title} ({company}){score_tag}...[/cyan]")
        page.goto(job_url, timeout=30000, wait_until="domcontentloaded")
        BrowserManager.human_delay(2.0, 3.5)

        # Check if already applied
        applied_indicators = [
            "text='Already Applied'",
            "span:has-text('Already Applied')",
            "button:has-text('Applied')",
            ".already-applied",
        ]
        for sel in applied_indicators:
            if page.locator(sel).first.is_visible(timeout=1500):
                log.info(f"Already applied to {job_title} on Foundit.")
                db.record_applied_job(
                    platform="foundit",
                    job_id=job_id,
                    job_title=job_title,
                    company=company,
                    job_url=job_url,
                    status="ALREADY_APPLIED",
                    notes="Detected Foundit applied indicator"
                )
                return "ALREADY_APPLIED"

        # Check for external company apply
        external_btn = page.locator("button:has-text('Apply on company site'), a:has-text('Apply on company site'), button:has-text('Apply via Employer')").first
        if external_btn.is_visible(timeout=1500):
            log.info(f"Foundit job redirects to external ATS: {company}. Launching Universal ATS Applier...")
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

        # Check for Foundit Quick Apply or Apply button
        apply_selectors = [
            "button.applyBtn",
            "button:has-text('Quick Apply')",
            "button:has-text('Apply Now')",
            "button:has-text('Apply')",
            "a.applyBtn",
            "#applyBtn",
            "div.applyBtnHolder button",
        ]
        apply_btn = None
        for sel in apply_selectors:
            cand = page.locator(sel).first
            if cand.is_visible(timeout=1500):
                apply_btn = cand
                break

        if not apply_btn:
            log.warning(f"No direct apply button found for Foundit listing: {job_title}.")
            db.record_applied_job(
                platform="foundit",
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

        # Check if modal or screening drawer appeared
        drawer = page.locator("div.applyModal, div.applyDrawer, div.modal-content, div[role='dialog']").first
        if drawer.is_visible(timeout=2500):
            log.info("Foundit screening form detected. Answering fields...")
            # 1. Inputs
            inputs = drawer.locator("input[type='text']:visible, input[type='number']:visible, textarea:visible").all()
            for inp in inputs:
                if inp.input_value().strip():
                    continue
                placeholder = (inp.get_attribute("placeholder") or "").lower()
                parent_text = inp.locator("xpath=..").inner_text().lower()
                combined = f"{placeholder} {parent_text}".strip()

                if "notice" in combined:
                    inp.fill("0" if "day" in combined else str(settings.profile.notice_period_days))
                elif "experience" in combined or "years" in combined:
                    inp.fill(str(settings.profile.years_of_experience))
                elif "ctc" in combined or "salary" in combined:
                    inp.fill(str(settings.profile.expected_salary_lpa))
                else:
                    ans = ai_assistant.answer_question(combined or "Enter details", field_type="text")
                    inp.fill(str(ans) if ans else "Yes")

            # 2. Selects
            for sel in drawer.locator("select:visible").all():
                opts = [o.inner_text().strip() for o in sel.locator("option").all() if o.inner_text().strip()]
                if opts:
                    ans = ai_assistant.answer_question("Select best option", field_type="dropdown", options=opts)
                    try:
                        sel.select_option(label=ans)
                    except Exception:
                        if len(opts) > 1:
                            sel.select_option(index=1)

            # 3. Submit
            sub_btn = drawer.locator("button:has-text('Submit and Apply'), button:has-text('Submit'), button:has-text('Confirm')").first
            if sub_btn.is_visible(timeout=1500):
                BrowserManager.safe_click(sub_btn)
                BrowserManager.human_delay(2.5, 4.0)

        proof_path = "data/exports/proof_foundit_applied.png"
        try:
            page.screenshot(path=proof_path)
            log.info(f"[bold green]Saved live Foundit application proof to: {proof_path}[/bold green]")
        except Exception:
            pass

        log.info(f"[bold green]✓ Successfully applied to {job_title} at {company} on Foundit![/bold green]")
        db.record_applied_job(
            platform="foundit",
            job_id=job_id,
            job_title=job_title,
            company=company,
            job_url=job_url,
            status="SUBMITTED",
            notes="Completed Foundit Apply flow",
            match_score=match_score
        )
        return "SUBMITTED"

    except Exception as e:
        log.error(f"[red]Error applying to Foundit job '{job_title}': {e}[/red]")
        db.record_applied_job(
            platform="foundit",
            job_id=job_id,
            job_title=job_title,
            company=company,
            job_url=job_url,
            status="FAILED",
            notes=str(e),
            match_score=match_score
        )
        return "FAILED"

def run_foundit_auto_apply(page: Page, limit: Optional[int] = None) -> int:
    """Scrapes jobs matching user configuration and auto-applies up to the specified limit on Foundit."""
    max_apps = limit or 5
    max_inspected = max(max_apps * 3, 12)
    max_runtime_sec = 300
    start_time = time.time()

    log.info(f"[bold cyan]Starting Foundit Auto-Apply (Target: up to {max_apps} applications, max inspected: {max_inspected})...[/bold cyan]")

    applied_count = 0
    inspected_count = 0
    from modules.foundit.scraper import scrape_foundit_jobs

    keywords = getattr(getattr(settings, "foundit", None), "search_keywords", settings.naukri.search_keywords)
    locations = getattr(getattr(settings, "foundit", None), "locations", ["Pune", "Bengaluru", "Remote", "India"])

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

            jobs = scrape_foundit_jobs(page, keyword=kw, location=loc, max_jobs=12)
            ranked_jobs = ai_matcher.filter_and_rank_jobs(jobs)

            for j in ranked_jobs:
                if applied_count >= max_apps or inspected_count >= max_inspected or (time.time() - start_time) > max_runtime_sec:
                    stop_search = True
                    break

                inspected_count += 1
                res = apply_to_foundit_job(
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

    log.info(f"[bold green]✓ Foundit Auto-Apply complete. Total applied: {applied_count} (Inspected: {inspected_count})[/bold green]")
    try:
        db.record_profile_refresh("foundit", f"Foundit Cloud Apply session active ({applied_count} applied)")
    except Exception as e:
        log.debug(f"Profile refresh note: {e}")
    return applied_count
