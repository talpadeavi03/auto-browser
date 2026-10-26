import time
import schedule
from datetime import datetime
from config.config import settings
from core.browser import get_browser
from core.logger import log, console
from modules.naukri.profile_updater import refresh_naukri_profile, is_naukri_logged_in
from modules.naukri.auto_apply import run_naukri_auto_apply
from modules.linkedin.easy_apply import run_linkedin_easy_apply
from modules.linkedin.scraper import is_linkedin_logged_in
from modules.tracker.export import export_reports

def job_naukri_refresh():
    log.info("⏰ [Scheduled Task] Starting scheduled Naukri profile boost...")
    try:
        with get_browser(headless=True) as browser:
            page = browser.new_page()
            refresh_naukri_profile(page)
    except Exception as e:
        log.error(f"Scheduled Naukri refresh failed: {e}")

def job_daily_applications():
    log.info("⏰ [Scheduled Task] Starting scheduled daily application cycle...")
    try:
        with get_browser(headless=True) as browser:
            page = browser.new_page()
            if is_linkedin_logged_in(page):
                run_linkedin_easy_apply(page, limit=10)
            if is_naukri_logged_in(page):
                run_naukri_auto_apply(page, limit=10)
        export_reports()
    except Exception as e:
        log.error(f"Scheduled application cycle failed: {e}")

def start_scheduler():
    """Starts the background scheduler loop."""
    console.print("[bold green]Starting Auto-Browser RPA Background Scheduler...[/bold green]")
    console.print(f"• Naukri Profile Boost: Every {settings.naukri.profile_refresh.interval_hours} hours")
    console.print("• Daily Job Applications: Every day at 09:30 AM & 03:30 PM")

    # Schedule Naukri profile boost every N hours
    hours = settings.naukri.profile_refresh.interval_hours
    schedule.every(hours).hours.do(job_naukri_refresh)

    # Schedule job applications twice a day
    schedule.every().day.at("09:30").do(job_daily_applications)
    schedule.every().day.at("15:30").do(job_daily_applications)

    # Initial run of profile booster on start
    job_naukri_refresh()

    console.print("[cyan]Scheduler running. Press Ctrl+C to exit.[/cyan]")
    while True:
        schedule.run_pending()
        time.sleep(30)

if __name__ == "__main__":
    start_scheduler()
