import time
from typing import Any, Dict, List, Optional
from playwright.sync_api import Page

from core.browser import BrowserManager, get_browser
from core.logger import log
from core.storage import db
from core.ai_matcher import ai_matcher
from modules.external.universal_apply import UniversalATSApplier
from modules.gmail.imap_reader import GmailIMAPReader
from modules.gmail.job_extractor import JobExtractor

def scan_gmail_job_alerts(max_emails: int = 15) -> List[Dict[str, Any]]:
    """
    Connects to Gmail via secure SSL IMAP, scans unread emails, and extracts job postings with application links.
    Returns list of discovered job records.
    """
    reader = GmailIMAPReader()
    if not reader.connect():
        log.warning("Could not connect to Gmail IMAP. Ensure GMAIL_APP_PASSWORD secret is set.")
        return []

    discovered = []
    try:
        unread_ids = reader.list_unread_emails(max_results=max_emails)
        log.info(f"Scanning {len(unread_ids)} unread Gmail messages for job opportunities...")

        for msg_id in unread_ids:
            email_data = reader.fetch_email(msg_id, mark_as_read=True)
            if not email_data:
                continue

            subject = email_data.get("subject", "")
            sender = email_data.get("sender", "")
            body_text = email_data.get("body_text", "")

            if not JobExtractor.is_job_alert(subject, sender, body_text):
                continue

            extracted = JobExtractor.extract(email_data)
            apply_url = extracted.get("apply_url")
            if not apply_url:
                log.debug(f"No direct application URL found in job alert: '{subject}'")
                continue

            # Evaluate AI Semantic Match
            role = extracted.get("role", "Cloud / DevOps Engineer")
            company = extracted.get("company", "Company")
            match_score = ai_matcher.calculate_match_score(
                job_title=role,
                job_description=f"{role} at {company}. {subject}\n{extracted.get('body_snippet', '')}"
            )
            extracted["match_score"] = match_score

            log.info(f"✨ Found Gmail Job Alert: [cyan]{role}[/cyan] at [bold]{company}[/bold] (AI Match: {match_score*100:.1f}%)")
            log.info(f"   URL: {apply_url[:70]}...")
            discovered.append(extracted)

    finally:
        reader.close()

    return discovered

def apply_from_gmail_alerts(max_applications: int = 5, headless: Optional[bool] = None) -> List[Dict[str, Any]]:
    """
    Scans Gmail inbox for incoming job alerts, extracts application links,
    and autonomously applies using Universal ATS and Playwright stealth.
    """
    log.info("[bold cyan]📬 Starting Autonomous Gmail Job Ingestion & Auto-Apply Worker...[/bold cyan]")
    discovered_jobs = scan_gmail_job_alerts(max_emails=25)
    if not discovered_jobs:
        log.info("No actionable job alerts found in Gmail inbox.")
        return []

    applied_results = []
    with get_browser(headless=headless) as browser:
        page = browser.new_page()

        for job in discovered_jobs:
            if len(applied_results) >= max_applications:
                break

            role = job.get("role", "Cloud / DevOps Engineer")
            company = job.get("company", "Company")
            url = job.get("apply_url", "")
            platform = job.get("platform", "external")
            match_score = job.get("match_score", 0.0)

            if db.is_already_applied(platform=platform, job_url=url):
                log.info(f"Skipping already applied Gmail alert: {role} at {company}")
                continue

            log.info(f"\n[bold magenta]🚀 Processing Gmail Alert Application ({len(applied_results)+1}/{max_applications}):[/bold magenta]")
            log.info(f"Role: {role} | Company: {company} | Platform: {platform}")

            try:
                # Apply using Universal ATS Applier
                status = UniversalATSApplier.apply(
                    page=page,
                    job_url=url,
                    job_title=role,
                    company=company,
                    job_id=f"gmail_{int(time.time())}",
                    match_score=match_score
                )

                job["status"] = status
                applied_results.append(job)
                BrowserManager.human_delay(2.5, 4.0)

            except Exception as e:
                log.error(f"Error applying to Gmail alert job '{role}': {e}")
                db.record_applied_job(
                    platform="gmail_alert",
                    job_title=role,
                    company=company,
                    job_url=url,
                    status="FAILED",
                    notes=str(e)[:300],
                    match_score=match_score
                )

    log.info(f"✓ Gmail Alert Processing Complete. Total applications processed: {len(applied_results)}")
    return applied_results
