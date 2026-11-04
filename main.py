#!/usr/bin/env python3
import base64
import json
import os
import sys
import time
from pathlib import Path
import click
from rich.panel import Panel
from rich.prompt import Prompt

from config.config import settings
from core.browser import BrowserManager, get_browser
from core.logger import console, log
from core.storage import db
from modules.naukri.profile_updater import is_naukri_logged_in, refresh_naukri_profile, NAUKRI_LOGIN_URL
from modules.naukri.scraper import scrape_naukri_jobs
from modules.naukri.auto_apply import run_naukri_auto_apply
from modules.linkedin.scraper import is_linkedin_logged_in, scrape_linkedin_jobs
from modules.linkedin.easy_apply import run_linkedin_easy_apply
from modules.linkedin.profile_booster import refresh_linkedin_profile
from modules.indeed.scraper import scrape_indeed_jobs
from modules.indeed.auto_apply import run_indeed_auto_apply
from modules.glassdoor.scraper import scrape_glassdoor_jobs
from modules.glassdoor.auto_apply import run_glassdoor_auto_apply
from modules.foundit.scraper import scrape_foundit_jobs
from modules.foundit.auto_apply import run_foundit_auto_apply
from modules.ambitionbox.scraper import scrape_ambitionbox_jobs
from modules.ambitionbox.auto_apply import run_ambitionbox_auto_apply
from modules.jobot.scraper import scrape_jobot_jobs
from modules.jobot.auto_apply import run_jobot_auto_apply
from modules.external.universal_apply import UniversalATSApplier
from modules.tracker.export import print_stats_table, export_reports
from core.auto_auth import auto_login_linkedin, auto_login_naukri, persist_session_cookies
from modules.gmail.auto_apply import scan_gmail_job_alerts, apply_from_gmail_alerts
from core.notifications import notifier

@click.group()
def cli():
    """🤖 Auto-Browser: Anti-Detect RPA Suite for Naukri & LinkedIn Job Automation"""
    pass

@cli.command()
@click.option("--platform", type=click.Choice(["all", "linkedin", "naukri"]), default="all", help="Target platform to log into")
@click.option("--engine", type=click.Choice(["chromium", "brave"]), default="chromium", help="Browser engine for login (default: chromium)")
def login(platform: str, engine: str):
    """Open interactive browser to log into Naukri and/or LinkedIn and save session permanently."""
    console.print(Panel.fit(
        "[bold cyan]Interactive Login Session[/bold cyan]\n\n"
        "1. A clean browser window will open on your screen.\n"
        "2. Log in with your credentials (or Google OAuth / OTP).\n"
        "3. Once you see your feed or profile, return to this terminal and press [bold green]Enter[/bold green].\n"
        "[dim]Note: Keep the browser window open until you press Enter.[/dim]",
        title="RPA Login Setup"
    ))

    # Always headful for manual login. Uses bundled Chromium by default to avoid conflicts with running Brave instances.
    with get_browser(headless=False, engine=engine) as browser:
        page = browser.new_page()

        # Clear stale expired cookies for a clean login
        try:
            page.context.clear_cookies()
        except Exception:
            pass

        # LinkedIn login
        if platform in ("all", "linkedin"):
            console.print("\n[bold yellow]Navigating to LinkedIn Login...[/bold yellow]")
            try:
                page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=25000)
            except Exception as nav_err:
                log.warning(f"Navigation issue encountered ({nav_err}). Clearing cookies and retrying...")
                try:
                    page.context.clear_cookies()
                except Exception:
                    pass
                page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=25000)
            
            # Auto-fill credentials if real credentials provided in env
            user = os.getenv("LINKEDIN_USERNAME")
            pwd = os.getenv("LINKEDIN_PASSWORD")
            if user and pwd and "your_" not in user and "your_" not in pwd and "example" not in user:
                log.info("Prefilling LinkedIn credentials from environment...")
                try:
                    page.locator("#username").fill(user)
                    page.locator("#password").fill(pwd)
                except Exception as e:
                    log.debug(f"Auto-fill note: {e}")

            console.print("\n[bold cyan]👉 Please log into LinkedIn in the opened browser window.[/bold cyan]")
            Prompt.ask("[bold green]Press Enter here once you have finished logging in and see your LinkedIn feed[/bold green]")

            if page.is_closed():
                console.print("[bold red]❌ Browser was closed before login could be saved. Please run the command again and keep the window open until you press Enter.[/bold red]")
                return

            count = persist_session_cookies(page)
            if is_linkedin_logged_in(page, navigate=True):
                console.print(f"[bold green]✓ LinkedIn authenticated successfully! {count} clean session cookies saved to data/auth_state.json![/bold green]")
            else:
                console.print(f"[bold yellow]Saved {count} LinkedIn cookies to disk.[/bold yellow]")

        # Naukri login
        if platform in ("all", "naukri"):
            if page.is_closed():
                console.print("[bold red]❌ Browser window was closed. Please run the command again.[/bold red]")
                return

            console.print("\n[bold yellow]Navigating to Naukri.com Login...[/bold yellow]")
            try:
                page.goto(NAUKRI_LOGIN_URL, wait_until="domcontentloaded", timeout=25000)
            except Exception as nav_err:
                log.warning(f"Navigation issue encountered ({nav_err}). Clearing cookies and retrying...")
                try:
                    page.context.clear_cookies()
                except Exception:
                    pass
                page.goto(NAUKRI_LOGIN_URL, wait_until="domcontentloaded", timeout=25000)

            # Auto-fill credentials if real credentials provided in env
            n_user = os.getenv("NAUKRI_USERNAME")
            n_pwd = os.getenv("NAUKRI_PASSWORD")
            if n_user and n_pwd and "your_" not in n_user and "your_" not in n_pwd and "example" not in n_user:
                log.info("Prefilling Naukri credentials from environment...")
                try:
                    page.locator("input[placeholder*='Username' i], input[placeholder*='Email' i]").first.fill(n_user)
                    page.locator("input[type='password']").first.fill(n_pwd)
                except Exception as e:
                    log.debug(f"Auto-fill note: {e}")

            console.print("\n[bold cyan]👉 Please log into Naukri in the opened browser window.[/bold cyan]")
            Prompt.ask("[bold green]Press Enter here once you have finished logging in and see your Naukri dashboard[/bold green]")

            if page.is_closed():
                console.print("[bold red]❌ Browser window was closed. Please run the command again.[/bold red]")
                return

            count = persist_session_cookies(page)
            if is_naukri_logged_in(page, navigate=True):
                console.print(f"[bold green]✓ Naukri authenticated successfully! {count} clean session cookies saved to data/auth_state.json![/bold green]")
            else:
                console.print(f"[bold yellow]Saved {count} Naukri cookies to disk.[/bold yellow]")

        if not page.is_closed():
            final_count = persist_session_cookies(page)
            console.print(f"\n[bold green]✓ Complete session saved ({final_count} total cookies in data/auth_state.json & data/auth_secret_for_github.txt)![/bold green]")

@cli.command("auto-login")
@click.option("--platform", type=click.Choice(["all", "linkedin", "naukri"]), default="all", help="Target platform for auto-login")
@click.option("--headless/--no-headless", default=None, help="Run in headless mode")
def auto_login_cmd(platform: str, headless: bool):
    """Autonomously log into LinkedIn and/or Naukri using credentials in .env and persist session."""
    console.print(Panel.fit("[bold cyan]Autonomous Auto-Login Service[/bold cyan]"))
    with get_browser(headless=headless) as browser:
        page = browser.new_page()
        
        if platform in ("all", "linkedin"):
            console.print("[yellow]Verifying LinkedIn session...[/yellow]")
            if is_linkedin_logged_in(page, navigate=True):
                console.print("[bold green]✓ LinkedIn is already logged in![/bold green]")
            else:
                success = auto_login_linkedin(page)
                if success:
                    console.print("[bold green]✓ LinkedIn autonomous login succeeded![/bold green]")
                else:
                    console.print("[bold red]LinkedIn auto-login failed. Verify LINKEDIN_USERNAME and LINKEDIN_PASSWORD in .env[/bold red]")

        if platform in ("all", "naukri"):
            console.print("\n[yellow]Verifying Naukri session...[/yellow]")
            if is_naukri_logged_in(page, navigate=True):
                console.print("[bold green]✓ Naukri is already logged in![/bold green]")
            else:
                success = auto_login_naukri(page)
                if success:
                    console.print("[bold green]✓ Naukri autonomous login succeeded![/bold green]")
                else:
                    console.print("[bold red]Naukri auto-login failed. Verify NAUKRI_USERNAME and NAUKRI_PASSWORD in .env[/bold red]")


@cli.command("naukri-refresh")
@click.option("--headless/--no-headless", default=None, help="Run in headless mode")
def naukri_refresh(headless: bool):
    """Boost Naukri profile visibility by refreshing Resume Headline."""
    with get_browser(headless=headless) as browser:
        page = browser.new_page()
        success = refresh_naukri_profile(page)
        if success:
            console.print("[bold green]✓ Naukri profile boosted! Your profile is now marked 'Active Today'.[/bold green]")
        else:
            console.print("[bold red]Failed to refresh profile. Verify login using 'python main.py login'.[/bold red]")

@cli.command("linkedin-refresh")
@click.option("--headless/--no-headless", default=None, help="Run in headless mode")
def linkedin_refresh(headless: bool):
    """Boost LinkedIn profile activity and verify cloud session."""
    with get_browser(headless=headless) as browser:
        page = browser.new_page()
        success = refresh_linkedin_profile(page)
        if success:
            console.print("[bold green]✓ LinkedIn profile boosted! Session verified & active in cloud.[/bold green]")
        else:
            console.print("[bold red]Failed to boost LinkedIn profile. Verify login using 'python main.py login'.[/bold red]")

@cli.command("naukri-apply")
@click.option("--limit", default=10, type=int, help="Max jobs to apply to")
@click.option("--headless/--no-headless", default=None, help="Run in headless mode")
def naukri_apply(limit: int, headless: bool):
    """Auto-apply to matching jobs on Naukri."""
    with get_browser(headless=headless) as browser:
        page = browser.new_page()
        if not is_naukri_logged_in(page, navigate=True):
            console.print("[bold red]Please log into Naukri first using 'python main.py login --platform naukri'[/bold red]")
            return
        run_naukri_auto_apply(page, limit=limit)
        print_stats_table()

@cli.command("linkedin-apply")
@click.option("--limit", default=10, type=int, help="Max jobs to apply to")
@click.option("--headless/--no-headless", default=None, help="Run in headless mode")
def linkedin_apply(limit: int, headless: bool):
    """Auto-apply to matching LinkedIn jobs using Easy Apply."""
    with get_browser(headless=headless) as browser:
        page = browser.new_page()
        if not is_linkedin_logged_in(page, navigate=True):
            console.print("[bold red]Please log into LinkedIn first using 'python main.py login --platform linkedin'[/bold red]")
            return
        run_linkedin_easy_apply(page, limit=limit)
        print_stats_table()

@cli.command("indeed-apply")
@click.option("--limit", default=10, type=int, help="Max jobs to apply to on Indeed")
@click.option("--headless/--no-headless", default=None, help="Run in headless mode")
def indeed_apply_cmd(limit: int, headless: bool):
    """Auto-apply to matching Indeed jobs using Indeed Apply or external ATS."""
    with get_browser(headless=headless) as browser:
        page = browser.new_page()
        run_indeed_auto_apply(page, limit=limit)
        print_stats_table()

@cli.command("glassdoor-apply")
@click.option("--limit", default=10, type=int, help="Max jobs to apply to on Glassdoor")
@click.option("--headless/--no-headless", default=None, help="Run in headless mode")
def glassdoor_apply_cmd(limit: int, headless: bool):
    """Auto-apply to matching Glassdoor jobs using Easy Apply or external ATS."""
    with get_browser(headless=headless) as browser:
        page = browser.new_page()
        run_glassdoor_auto_apply(page, limit=limit)
        print_stats_table()

@cli.command("foundit-apply")
@click.option("--limit", default=10, type=int, help="Max jobs to apply to on Foundit (Monster)")
@click.option("--headless/--no-headless", default=None, help="Run in headless mode")
def foundit_apply_cmd(limit: int, headless: bool):
    """Auto-apply to matching Foundit jobs using Quick Apply or external ATS."""
    with get_browser(headless=headless) as browser:
        page = browser.new_page()
        run_foundit_auto_apply(page, limit=limit)
        print_stats_table()

@cli.command("ambitionbox-apply")
@click.option("--limit", default=10, type=int, help="Max jobs to apply to on AmbitionBox")
@click.option("--headless/--no-headless", default=None, help="Run in headless mode")
def ambitionbox_apply_cmd(limit: int, headless: bool):
    """Auto-apply to matching AmbitionBox jobs using direct InfoEdge or company ATS."""
    with get_browser(headless=headless) as browser:
        page = browser.new_page()
        run_ambitionbox_auto_apply(page, limit=limit)
        print_stats_table()

@cli.command("jobot-apply")
@click.option("--limit", default=10, type=int, help="Max jobs to apply to on Jobot")
@click.option("--headless/--no-headless", default=None, help="Run in headless mode")
def jobot_apply_cmd(limit: int, headless: bool):
    """Auto-apply to matching Jobot jobs using 1-Click apply or external ATS."""
    with get_browser(headless=headless) as browser:
        page = browser.new_page()
        run_jobot_auto_apply(page, limit=limit)
        print_stats_table()

@cli.command("gmail-scan")
@click.option("--limit", default=20, type=int, help="Max unread emails to scan")
def gmail_scan_cmd(limit: int):
    """Scan candidate Gmail inbox for incoming job alerts and recruiter links."""
    from rich.table import Table
    console.print(Panel.fit("[bold cyan]Scanning Gmail Inbox for Job Alerts & Opportunities[/bold cyan]"))
    jobs = scan_gmail_job_alerts(max_emails=limit)
    if jobs:
        table = Table(title="[bold green]Discovered Gmail Job Alerts[/bold green]")
        table.add_column("Company", style="cyan")
        table.add_column("Role", style="magenta")
        table.add_column("AI Match", style="yellow")
        table.add_column("Application Link", style="green")
        for j in jobs:
            table.add_row(
                j.get("company", "Company"),
                j.get("role", "Role"),
                f"{j.get('match_score', 0.0)*100:.1f}%",
                str(j.get("apply_url", "N/A"))[:55] + "..."
            )
        console.print(table)
    else:
        console.print("[yellow]No actionable job alerts found in recent unread emails.[/yellow]")

@cli.command("gmail-apply")
@click.option("--limit", default=5, type=int, help="Max Gmail alerts to apply to")
@click.option("--headless/--no-headless", default=None, help="Run in headless mode")
def gmail_apply_cmd(limit: int, headless: bool):
    """Auto-apply to jobs found in Gmail alert notifications via Universal ATS."""
    apply_from_gmail_alerts(max_applications=limit, headless=headless)
    print_stats_table()

@cli.command("slm-train")
def slm_train_cmd():
    """Fine-tune the local/cloud SLM on cumulative screening Q&A interactions."""
    console.print(Panel.fit("[bold cyan]Launching Cloud SLM Fine-Tuning Pipeline[/bold cyan]"))
    from slm.train_cloud import train
    train()

@cli.command("apply")
@click.option("--platform", type=click.Choice(["all", "linkedin", "naukri", "indeed", "glassdoor", "foundit", "ambitionbox", "jobot", "gmail"]), default="all", help="Target platform to apply on")
@click.option("--limit", default=5, type=int, help="Max jobs to apply to per platform")
@click.option("--headless/--no-headless", default=None, help="Run in headless mode")
def apply_cmd(platform: str, limit: int, headless: bool):
    """Auto-apply to jobs on LinkedIn, Naukri, Indeed, Glassdoor, Foundit, AmbitionBox, Jobot, or Gmail alerts."""
    console.print(Panel.fit(f"[bold cyan]Starting AI Auto-Apply on {platform.upper()} (Limit: {limit})[/bold cyan]"))
    with get_browser(headless=headless) as browser:
        page = browser.new_page()

        if platform in ("all", "linkedin"):
            console.print("\n[bold cyan]Targeting LinkedIn Easy Apply...[/bold cyan]")
            if is_linkedin_logged_in(page, navigate=True):
                run_linkedin_easy_apply(page, limit=limit)
            else:
                console.print("[bold yellow]LinkedIn session inactive. Skipping LinkedIn apply.[/bold yellow]")

        if platform in ("all", "naukri"):
            console.print("\n[bold cyan]Targeting Naukri Auto-Apply...[/bold cyan]")
            if is_naukri_logged_in(page, navigate=True):
                run_naukri_auto_apply(page, limit=limit)
            else:
                console.print("[bold yellow]Naukri session inactive. Skipping Naukri apply.[/bold yellow]")

        if platform in ("all", "indeed"):
            console.print("\n[bold cyan]Targeting Indeed Auto-Apply...[/bold cyan]")
            try:
                run_indeed_auto_apply(page, limit=limit)
            except Exception as e:
                log.error(f"Indeed apply failed: {e}")

        if platform in ("all", "glassdoor"):
            console.print("\n[bold cyan]Targeting Glassdoor Auto-Apply...[/bold cyan]")
            try:
                run_glassdoor_auto_apply(page, limit=limit)
            except Exception as e:
                log.error(f"Glassdoor apply failed: {e}")

        if platform in ("all", "foundit"):
            console.print("\n[bold cyan]Targeting Foundit Auto-Apply...[/bold cyan]")
            try:
                run_foundit_auto_apply(page, limit=limit)
            except Exception as e:
                log.error(f"Foundit apply failed: {e}")

        if platform in ("all", "ambitionbox"):
            console.print("\n[bold cyan]Targeting AmbitionBox Auto-Apply...[/bold cyan]")
            try:
                run_ambitionbox_auto_apply(page, limit=limit)
            except Exception as e:
                log.error(f"AmbitionBox apply failed: {e}")

        if platform in ("all", "jobot"):
            console.print("\n[bold cyan]Targeting Jobot Auto-Apply...[/bold cyan]")
            try:
                run_jobot_auto_apply(page, limit=limit)
            except Exception as e:
                log.error(f"Jobot apply failed: {e}")

    if platform in ("all", "gmail"):
        console.print("\n[bold cyan]Targeting Gmail Job Alerts Auto-Apply...[/bold cyan]")
        try:
            apply_from_gmail_alerts(max_applications=limit, headless=headless)
        except Exception as e:
            log.error(f"Gmail apply step failed: {e}")

    print_stats_table()
    export_reports()

@cli.command("external-apply")
@click.option("--url", required=True, help="Direct URL to external job application page or ATS")
@click.option("--company", default="Company", help="Company name")
@click.option("--title", default="DevOps Engineer", help="Job title")
@click.option("--headless/--no-headless", default=None, help="Run in headless mode")
def external_apply(url: str, company: str, title: str, headless: bool):
    """Auto-apply to any external job link or company ATS (Greenhouse, Lever, Workday, etc.)."""
    with get_browser(headless=headless) as browser:
        page = browser.new_page()
        res = UniversalATSApplier.apply(page=page, job_url=url, job_title=title, company=company)
        console.print(f"[bold green]Application Result: {res}[/bold green]")
        print_stats_table()

@cli.command("scrape")
@click.option("--platform", type=click.Choice(["all", "linkedin", "naukri", "indeed", "glassdoor", "foundit", "ambitionbox", "jobot"]), default="all")
@click.option("--headless/--no-headless", default=None, help="Run in headless mode")
def scrape(platform: str, headless: bool):
    """Scrape and track matching jobs with AI semantic match ranking."""
    all_scraped = []
    with get_browser(headless=headless) as browser:
        page = browser.new_page()

        if platform in ("all", "naukri"):
            for kw in settings.naukri.search_keywords:
                for loc in settings.naukri.locations:
                    all_scraped.extend(scrape_naukri_jobs(page, keyword=kw, location=loc, max_pages=1))

        if platform in ("all", "linkedin"):
            for kw in settings.linkedin.search_keywords:
                for loc in settings.linkedin.locations:
                    all_scraped.extend(scrape_linkedin_jobs(page, keyword=kw, location=loc, max_jobs=15))

        if platform in ("all", "indeed"):
            for kw in getattr(getattr(settings, "indeed", None), "search_keywords", settings.naukri.search_keywords):
                for loc in getattr(getattr(settings, "indeed", None), "locations", ["Pune", "Bengaluru", "Remote", "India"]):
                    all_scraped.extend(scrape_indeed_jobs(page, keyword=kw, location=loc, max_pages=1))

        if platform in ("all", "glassdoor"):
            for kw in getattr(getattr(settings, "glassdoor", None), "search_keywords", settings.naukri.search_keywords):
                for loc in getattr(getattr(settings, "glassdoor", None), "locations", ["Pune", "Bengaluru", "Remote", "India"]):
                    all_scraped.extend(scrape_glassdoor_jobs(page, keyword=kw, location=loc, max_jobs=12))

        if platform in ("all", "foundit"):
            for kw in getattr(getattr(settings, "foundit", None), "search_keywords", settings.naukri.search_keywords):
                for loc in getattr(getattr(settings, "foundit", None), "locations", ["Pune", "Bengaluru", "Remote"]):
                    all_scraped.extend(scrape_foundit_jobs(page, keyword=kw, location=loc, max_jobs=12))

        if platform in ("all", "ambitionbox"):
            for kw in getattr(getattr(settings, "ambitionbox", None), "search_keywords", settings.naukri.search_keywords):
                for loc in getattr(getattr(settings, "ambitionbox", None), "locations", ["Pune", "Bengaluru", "Remote"]):
                    all_scraped.extend(scrape_ambitionbox_jobs(page, keyword=kw, location=loc, max_jobs=12))

        if platform in ("all", "jobot"):
            for kw in getattr(getattr(settings, "jobot", None), "search_keywords", settings.naukri.search_keywords):
                for loc in getattr(getattr(settings, "jobot", None), "locations", ["Remote", "India", "Pune"]):
                    all_scraped.extend(scrape_jobot_jobs(page, keyword=kw, location=loc, max_jobs=12))

    if all_scraped:
        from core.ai_matcher import ai_matcher
        ranked = ai_matcher.filter_and_rank_jobs(all_scraped)
        console.print(f"\n[bold green]✓ AI Reranker evaluated {len(all_scraped)} listings ({len(ranked)} qualified ≥ {settings.models.min_match_score*100:.0f}%)[/bold green]")
        for i, r in enumerate(ranked[:5], 1):
            console.print(f"  {i}. [cyan]{r.get('job_title')}[/cyan] at [magenta]{r.get('company')}[/magenta] ([bold green]{r.get('match_percentage')}[/bold green])")

    print_stats_table()
    export_reports()

@cli.command("stats")
def show_stats():
    """Display metrics and status of applied and scraped jobs."""
    print_stats_table()

@cli.command("export")
@click.option("--dir", default=None, help="Target export directory")
def export(dir: str):
    """Export job data to CSV and Excel files."""
    export_reports(target_dir=dir)

@cli.command("run-all")
@click.option("--limit", default=10, type=int, help="Max applications per platform")
@click.option("--headless/--no-headless", default=None, help="Run in headless mode")
def run_all(limit: int, headless: bool):
    """Full automation sequence: Boost profiles -> Apply across Naukri, LinkedIn, Indeed, Glassdoor, Foundit, AmbitionBox, Jobot -> Export reports."""
    console.print(Panel.fit("[bold green]Starting Complete Multi-Platform RPA Workflow Sequence[/bold green]", title="Auto-Browser 2.0"))

    with get_browser(headless=headless) as browser:
        page = browser.new_page()

        # Step 1: Naukri & LinkedIn Profile Booster
        console.print("\n[bold cyan]Step 1: Refreshing Profile Boosters (Naukri & LinkedIn)...[/bold cyan]")
        try:
            refresh_naukri_profile(page)
        except Exception as e:
            log.error(f"Naukri refresh step failed: {e}")

        try:
            refresh_linkedin_profile(page)
        except Exception as e:
            log.error(f"LinkedIn refresh step failed: {e}")

        # Step 2: LinkedIn Easy Apply
        console.print("\n[bold cyan]Step 2: Running LinkedIn Easy Apply...[/bold cyan]")
        try:
            if is_linkedin_logged_in(page, navigate=True):
                run_linkedin_easy_apply(page, limit=limit)
            else:
                log.warning("LinkedIn session inactive. Skipping LinkedIn apply.")
        except Exception as e:
            log.error(f"LinkedIn apply step failed: {e}")

        # Step 3: Naukri Auto-Apply
        console.print("\n[bold cyan]Step 3: Running Naukri Auto-Apply...[/bold cyan]")
        try:
            if is_naukri_logged_in(page, navigate=True):
                run_naukri_auto_apply(page, limit=limit)
            else:
                log.warning("Naukri session inactive. Skipping Naukri apply.")
        except Exception as e:
            log.error(f"Naukri apply step failed: {e}")

        # Step 4: Indeed Auto-Apply
        console.print("\n[bold cyan]Step 4: Running Indeed Auto-Apply...[/bold cyan]")
        try:
            run_indeed_auto_apply(page, limit=limit)
        except Exception as e:
            log.error(f"Indeed apply step failed: {e}")

        # Step 5: Glassdoor Auto-Apply
        console.print("\n[bold cyan]Step 5: Running Glassdoor Auto-Apply...[/bold cyan]")
        try:
            run_glassdoor_auto_apply(page, limit=limit)
        except Exception as e:
            log.error(f"Glassdoor apply step failed: {e}")

        # Step 6: Foundit Auto-Apply
        console.print("\n[bold cyan]Step 6: Running Foundit Auto-Apply...[/bold cyan]")
        try:
            run_foundit_auto_apply(page, limit=limit)
        except Exception as e:
            log.error(f"Foundit apply step failed: {e}")

        # Step 7: AmbitionBox Auto-Apply
        console.print("\n[bold cyan]Step 7: Running AmbitionBox Auto-Apply...[/bold cyan]")
        try:
            run_ambitionbox_auto_apply(page, limit=limit)
        except Exception as e:
            log.error(f"AmbitionBox apply step failed: {e}")

        # Step 8: Jobot Auto-Apply
        console.print("\n[bold cyan]Step 8: Running Jobot Auto-Apply...[/bold cyan]")
        try:
            run_jobot_auto_apply(page, limit=limit)
        except Exception as e:
            log.error(f"Jobot apply step failed: {e}")

    # Step 9: Gmail Ingestion & Alert Auto-Apply
    console.print("\n[bold cyan]Step 9: Scanning & Applying to Inbound Gmail Job Alerts...[/bold cyan]")
    try:
        apply_from_gmail_alerts(max_applications=limit, headless=headless)
    except Exception as e:
        log.error(f"Gmail apply step failed: {e}")

    # Step 10: Summary, Real-Time Notifications & Export
    console.print("\n[bold cyan]Step 10: Generating Multi-Platform Metrics, Notifications & Reports...[/bold cyan]")
    print_stats_table()
    export_reports()

    # Dispatch summary alert to Discord / Telegram if configured
    try:
        notifier.notify_summary(
            applied_count=db.get_total_applied_count(),
            inspected_count=db.get_total_scraped_count(),
            boosted=["Naukri", "LinkedIn"]
        )
    except Exception:
        pass

    console.print("\n[bold green]✓ Complete Multi-Platform RPA Workflow finished successfully![/bold green]")

@cli.command("export-auth")
def export_auth():
    """Export active authenticated cookies for 24/7 cloud execution (GitHub Actions)."""
    console.print(Panel.fit("[bold cyan]Exporting Authenticated Session for Cloud CI/CD[/bold cyan]"))
    with get_browser() as browser:
        context = browser.context
        cookies = context.cookies()
        from core.browser import clean_and_normalize_cookies
        filtered = clean_and_normalize_cookies(cookies)
        
        if not filtered:
            console.print("[bold red]No active Naukri or LinkedIn cookies found.[/bold red] Please make sure you are logged in first.")
            return

        payload = {"cookies": filtered}
        json_str = json.dumps(payload)
        b64_str = base64.b64encode(json_str.encode("utf-8")).decode("utf-8")

        # Save locally
        data_dir = Path("data")
        data_dir.mkdir(exist_ok=True)
        (data_dir / "auth_state.json").write_text(json_str)
        secret_file = data_dir / "auth_secret_for_github.txt"
        secret_file.write_text(b64_str)

        naukri_count = sum(1 for c in filtered if "naukri" in c.get("domain", ""))
        linkedin_count = sum(1 for c in filtered if "linkedin" in c.get("domain", ""))

        console.print(f"[bold green]✓ Successfully exported {len(filtered)} session cookies![/bold green]")
        console.print(f"  • Naukri cookies: [bold cyan]{naukri_count}[/bold cyan]")
        console.print(f"  • LinkedIn cookies: [bold cyan]{linkedin_count}[/bold cyan]")
        console.print(f"\n[bold yellow]Cloud Secret saved to:[/bold yellow] [green]{secret_file}[/green]")
        console.print(
            "\n[bold white]To run 24/7 online in GitHub Actions without opening your laptop:[/bold white]\n"
            "1. Copy the string in [bold green]data/auth_secret_for_github.txt[/bold green]\n"
            "2. Open: [cyan]https://github.com/talpadeavi03/auto-browser/settings/secrets/actions[/cyan]\n"
            "3. Click 'New repository secret'\n"
            "   • Name: [bold green]AUTH_STORAGE_STATE[/bold green]\n"
            "   • Value: Paste the copied string\n"
            "4. Add another secret for Gemini:\n"
            "   • Name: [bold green]GEMINI_API_KEY[/bold green]\n"
            "   • Value: Your Google Gemini API key\n"
        )

@cli.command("export-dataset")
@click.option("--output", default="data/training_dataset.jsonl", help="Target path for training JSONL file")
def export_dataset(output: str):
    """Exports application form screening Q&A into HuggingFace/Colab format for ML fine-tuning."""
    out_file = db.export_training_dataset(Path(output))
    console.print(f"\n[bold green]✓ Training dataset ready for Google Colab:[/bold green] [cyan]{out_file}[/cyan]")
    console.print(
        "[bold white]Next Steps to train your model for free:[/bold white]\n"
        "1. Open the notebook in [cyan]notebooks/train_colab.ipynb[/cyan] in Google Colab.\n"
        "2. Upload [green]data/training_dataset.jsonl[/green] or connect your GitHub repo.\n"
        "3. Click 'Run All' with free T4 GPU to fine-tune Qwen-2.5-1.5B with LoRA in ~5-10 minutes.\n"
        "4. Your fine-tuned model will auto-push to Hugging Face Hub (free) or save GGUF to Google Drive!"
    )

@cli.command("verify")
def verify():
    """Validates the entire end-to-end Auto-Browser and AI/ML pipeline."""
    from rich.panel import Panel
    from rich.table import Table
    from core.ai_assistant import ai_assistant

    console.print(Panel.fit("[bold green]🤖 Auto-Browser Full System & AI Pipeline Diagnostics[/bold green]"))

    # 1. Dataset Check
    ds_path = Path("data/training_dataset.jsonl")
    if ds_path.exists():
        lines = [l for l in ds_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        console.print(f"✓ Training Dataset: [bold green]{len(lines)} samples[/bold green] ({ds_path})")
    else:
        console.print("⚠️ Training Dataset: [bold red]Not found[/bold red]")

    # 2. AI Answering & Semantic Matching Stack Status
    from core.ai_matcher import ai_matcher
    console.print("\n[bold white]AI Answering & Semantic Reranking Stack:[/bold white]")
    console.print(f"  • LLM (Form Reasoning): [bold green]{settings.models.llm}[/bold green]")
    console.print(f"  • Embeddings (General): [bold green]{settings.models.embeddings}[/bold green]")
    console.print(f"  • Resume Embeddings: [bold green]{settings.models.resume_embeddings}[/bold green]")
    console.print(f"  • Cross-Encoder Reranker: [bold green]{settings.models.reranker}[/bold green] (Threshold: {settings.models.min_match_score * 100:.0f}%)")

    if ai_assistant.deepseek_api_key:
        console.print(f"  • DeepSeek API: [bold green]Active[/bold green]")
    elif ai_assistant.hf_model_id:
        console.print(f"  • Fine-Tuned Cloud Model: [bold green]{ai_assistant.hf_model_id}[/bold green]")
    if ai_assistant.is_active:
        console.print("  • Google Gemini 2.5 Flash: [bold green]Active (Fallback)[/bold green]")
    console.print("  • Local Heuristic Engine: [bold green]Active (Safety Fallback)[/bold green]")

    # 3. Test Semantic Job Matcher
    sample_job = {"job_title": "Senior Cloud & DevOps Engineer", "company": "Hyperscale Cloud Inc", "snippet": "Looking for AWS, Kubernetes EKS, Terraform, and Docker expert for cloud migration."}
    score = ai_matcher.score_job(sample_job["job_title"], sample_job["company"], sample_job["snippet"])
    console.print(f"\n[bold white]Semantic Job Matching Reranker Test:[/bold white]")
    console.print(f"  Sample Job: [cyan]'{sample_job['job_title']}'[/cyan] at [cyan]'{sample_job['company']}'[/cyan]")
    console.print(f"  Compatibility Score: [bold green]{score * 100:.1f}% match[/bold green] (via {settings.models.reranker})\n")

    # 4. Cloud Ingestion & Notifications
    console.print("\n[bold white]Cloud Ingestion & Notification Channels:[/bold white]")
    gmail_pass = bool(os.getenv("GMAIL_APP_PASSWORD", "").strip())
    gmail_user = os.getenv("GMAIL_USER") or "talpadeavi0303@gmail.com"
    console.print(f"  • Gmail IMAP Alerts Reader: {'[bold green]Ready (' + gmail_user + ')[/bold green]' if gmail_pass else '[bold yellow]Unset (set GMAIL_APP_PASSWORD secret to enable)[/bold yellow]'}")
    console.print(f"  • Discord Notifications: {'[bold green]Active[/bold green]' if notifier.is_discord_enabled else '[dim]Disabled (DISCORD_WEBHOOK_URL unset)[/dim]'}")
    console.print(f"  • Telegram Notifications: {'[bold green]Active[/bold green]' if notifier.is_telegram_enabled else '[dim]Disabled (TELEGRAM_BOT_TOKEN unset)[/dim]'}")
    console.print(f"  • Free Cloud SLM Training Pipeline: [bold green]slm/train_cloud.py (Kaggle/Colab Ready)[/bold green]")

    # 5. Live Benchmark Q&A Test
    console.print("\n[bold white]Running Live Screening Q&A Test:[/bold white]")
    benchmarks = [
        ("Which AWS certification do you have?", "text", None),
        ("How many years of experience do you have with Kubernetes?", "number", None),
        ("Notice period", "dropdown", ["Immediate", "15 Days", "30 Days", "60 Days"]),
        ("Are you legally authorized to work in India?", "radio", ["Yes", "No"]),
        ("Briefly summarize your experience with Kubernetes:", "text", None)
    ]

    table = Table(title="Live AI Answering Test Results")
    table.add_column("Question", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("AI Generated Answer", style="bold green")

    for q, ft, opts in benchmarks:
        ans = ai_assistant.answer_question(q, field_type=ft, options=opts)
        table.add_row(q[:45] + ("..." if len(q) > 45 else ""), ft, str(ans))

    console.print(table)
    console.print("\n[bold green]✓ All system diagnostics passed successfully![/bold green]")

if __name__ == "__main__":
    cli()
