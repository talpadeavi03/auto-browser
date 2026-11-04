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

def apply_to_ambitionbox_job(page: Page, job_url: str, job_title: str, company: str, job_id: str = "", match_score: float = 0.0) -> str:
    """
    Attempts to apply to an AmbitionBox job posting (often backed by InfoEdge/Naukri or company ATS).
    Returns: 'APPLIED', 'ALREADY_APPLIED', 'NO_APPLY_BUTTON', 'SKIPPED_COMPLEX', or 'FAILED'.
    """
    if db.is_already_applied("ambitionbox", job_url, job_id):
        log.info(f"Skipping already recorded job: {job_title} at {company}")
        return "ALREADY_APPLIED"

    try:
        score_tag = f" [AI Match: {match_score*100:.1f}%]" if match_score > 0 else ""
        log.info(f"[cyan]Opening AmbitionBox job: {job_title} ({company}){score_tag}...[/cyan]")
        page.goto(job_url, timeout=30000, wait_until="domcontentloaded")
        BrowserManager.human_delay(2.0, 3.5)

        # Check if already applied
        applied_indicators = [
            "text='Already Applied'",
            "span:has-text('Applied')",
            "button:has-text('Applied')",
        ]
        for sel in applied_indicators:
            if page.locator(sel).first.is_visible(timeout=1500):
                log.info(f"Already applied to {job_title} on AmbitionBox.")
                db.record_applied_job(
                    platform="ambitionbox",
                    job_id=job_id,
                    job_title=job_title,
                    company=company,
                    job_url=job_url,
                    status="ALREADY_APPLIED",
                    notes="Detected AmbitionBox applied badge"
                )
                return "ALREADY_APPLIED"

        # Check for Apply button
        apply_selectors = [
            "button:has-text('Apply on Naukri')",
            "a:has-text('Apply on Naukri')",
            "button:has-text('Apply on company site')",
            "a:has-text('Apply on company site')",
            "button:has-text('Apply Now')",
            "a:has-text('Apply Now')",
            "button:has-text('Apply')",
            "a:has-text('Apply')",
        ]
        apply_btn = None
        for sel in apply_selectors:
            cand = page.locator(sel).first
            if cand.is_visible(timeout=1500):
                apply_btn = cand
                break

        if not apply_btn:
            log.warning(f"No direct apply button found for AmbitionBox listing: {job_title}.")
            db.record_applied_job(
                platform="ambitionbox",
                job_id=job_id,
                job_title=job_title,
                company=company,
                job_url=job_url,
                status="NO_APPLY_BUTTON",
                notes="Could not locate standard apply button"
            )
            return "NO_APPLY_BUTTON"

        # Check if button links to external or popup
        btn_text = apply_btn.inner_text().strip().lower()
        if "naukri" in btn_text or "company" in btn_text or apply_btn.get_attribute("target") == "_blank":
            log.info(f"AmbitionBox redirects to external / Naukri portal. Handled via Universal ATS Applier...")
            try:
                with page.context.expect_page(timeout=7000) as ext_info:
                    BrowserManager.safe_click(apply_btn)
                ext_page = ext_info.value
                ext_page.wait_for_load_state("domcontentloaded", timeout=20000)
                res = UniversalATSApplier.apply(ext_page, ext_page.url, job_title, company, job_id, match_score=match_score)
                ext_page.close()
                return res
            except Exception as ext_err:
                log.warning(f"Popup handle note ({ext_err}). Trying in current tab...")
                ext_url = apply_btn.get_attribute("href") or page.url
                return UniversalATSApplier.apply(page, ext_url, job_title, company, job_id, match_score=match_score)

        BrowserManager.safe_click(apply_btn)
        BrowserManager.human_delay(2.5, 4.0)

        # In-page application confirmation or screening
        drawer = page.locator("div.apply-modal, div.modal-dialog, div[role='dialog']").first
        if drawer.is_visible(timeout=2000):
            sub_btn = drawer.locator("button:has-text('Submit'), button:has-text('Confirm'), button:has-text('Apply')").first
            if sub_btn.is_visible():
                BrowserManager.safe_click(sub_btn)
                BrowserManager.human_delay(2.0, 3.5)

        proof_path = "data/exports/proof_ambitionbox_applied.png"
        try:
            page.screenshot(path=proof_path)
            log.info(f"[bold green]Saved live AmbitionBox application proof to: {proof_path}[/bold green]")
        except Exception:
            pass

        log.info(f"[bold green]✓ Successfully applied to {job_title} at {company} on AmbitionBox![/bold green]")
        db.record_applied_job(
            platform="ambitionbox",
            job_id=job_id,
            job_title=job_title,
            company=company,
            job_url=job_url,
            status="APPLIED",
            notes="Completed AmbitionBox apply",
            match_score=match_score
        )
        return "APPLIED"

    except Exception as e:
        log.error(f"[red]Error applying to AmbitionBox job '{job_title}': {e}[/red]")
        db.record_applied_job(
            platform="ambitionbox",
            job_id=job_id,
            job_title=job_title,
            company=company,
            job_url=job_url,
            status="FAILED",
            notes=str(e),
            match_score=match_score
        )
        return "FAILED"

def run_ambitionbox_auto_apply(page: Page, limit: Optional[int] = None) -> int:
    """Scrapes jobs matching user configuration and auto-applies up to the specified limit on AmbitionBox."""
    max_apps = limit or 5
    max_inspected = max(max_apps * 3, 12)
    max_runtime_sec = 300
    start_time = time.time()

    log.info(f"[bold cyan]Starting AmbitionBox Auto-Apply (Target: up to {max_apps} applications, max inspected: {max_inspected})...[/bold cyan]")

    applied_count = 0
    inspected_count = 0
    from modules.ambitionbox.scraper import scrape_ambitionbox_jobs

    keywords = getattr(getattr(settings, "ambitionbox", None), "search_keywords", settings.naukri.search_keywords)
    locations = getattr(getattr(settings, "ambitionbox", None), "locations", ["Pune", "Bengaluru", "Remote", "India"])

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

            jobs = scrape_ambitionbox_jobs(page, keyword=kw, location=loc, max_jobs=12)
            ranked_jobs = ai_matcher.filter_and_rank_jobs(jobs)

            for j in ranked_jobs:
                if applied_count >= max_apps or inspected_count >= max_inspected or (time.time() - start_time) > max_runtime_sec:
                    stop_search = True
                    break

                inspected_count += 1
                res = apply_to_ambitionbox_job(
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

    log.info(f"[bold green]✓ AmbitionBox Auto-Apply complete. Total applied: {applied_count} (Inspected: {inspected_count})[/bold green]")
    try:
        db.record_profile_refresh("ambitionbox", f"AmbitionBox Cloud Apply session active ({applied_count} applied)")
    except Exception as e:
        log.debug(f"Profile refresh note: {e}")
    return applied_count
