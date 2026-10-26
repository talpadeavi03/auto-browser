#!/usr/bin/env python3
import os
import sys
import time
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
from modules.tracker.export import print_stats_table, export_reports

@click.group()
def cli():
    """🤖 Auto-Browser: Anti-Detect RPA Suite for Naukri & LinkedIn Job Automation"""
    pass

@cli.command()
@click.option("--platform", type=click.Choice(["all", "linkedin", "naukri"]), default="all", help="Target platform to log into")
def login(platform: str):
    """Open interactive browser to log into Naukri and/or LinkedIn and save session permanently."""
    console.print(Panel.fit(
        "[bold cyan]Interactive Login Session[/bold cyan]\n"
        "A browser window will open. Please log into your accounts, solve any 2FA/OTPs,\n"
        "and your session will be saved permanently in [magenta]data/browser_profile[/magenta].",
        title="RPA Setup"
    ))

    # Always headful for manual login
    with get_browser(headless=False) as browser:
        page = browser.new_page()

        # LinkedIn login
        if platform in ("all", "linkedin"):
            console.print("\n[bold yellow]Navigating to LinkedIn...[/bold yellow]")
            page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
            
            # Auto-fill credentials if provided in env
            user = os.getenv("LINKEDIN_USERNAME")
            pwd = os.getenv("LINKEDIN_PASSWORD")
            if user and pwd:
                log.info("Prefilling LinkedIn credentials from environment...")
                try:
                    page.locator("#username").fill(user)
                    page.locator("#password").fill(pwd)
                    page.locator("button[type='submit']").click()
                except Exception as e:
                    log.debug(f"Auto-fill note: {e}")

            log.info("Waiting for LinkedIn login completion...")
            login_success = False
            for _ in range(90):  # Wait up to 3 minutes
                time.sleep(2)
                if is_linkedin_logged_in(page):
                    login_success = True
                    break

            if login_success:
                console.print("[bold green]✓ LinkedIn authenticated successfully! Session stored.[/bold green]")
            else:
                console.print("[bold red]LinkedIn login timeout or not completed.[/bold red]")

        # Naukri login
        if platform in ("all", "naukri"):
            console.print("\n[bold yellow]Navigating to Naukri.com...[/bold yellow]")
            page.goto(NAUKRI_LOGIN_URL, wait_until="domcontentloaded")

            # Auto-fill credentials if provided in env
            n_user = os.getenv("NAUKRI_USERNAME")
            n_pwd = os.getenv("NAUKRI_PASSWORD")
            if n_user and n_pwd:
                log.info("Prefilling Naukri credentials from environment...")
                try:
                    page.locator("input[placeholder*='Username' i], input[placeholder*='Email' i]").first.fill(n_user)
                    page.locator("input[type='password']").first.fill(n_pwd)
                    page.locator("button[type='submit']").first.click()
                except Exception as e:
                    log.debug(f"Auto-fill note: {e}")

            log.info("Waiting for Naukri login completion...")
            n_success = False
            for _ in range(90):
                time.sleep(2)
                if is_naukri_logged_in(page):
                    n_success = True
                    break

            if n_success:
                console.print("[bold green]✓ Naukri authenticated successfully! Session stored.[/bold green]")
            else:
                console.print("[bold red]Naukri login timeout or not completed.[/bold red]")

    console.print("\n[bold green]Login procedure completed! You can now run automated tasks.[/bold green]")

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

@cli.command("naukri-apply")
@click.option("--limit", default=10, type=int, help="Max jobs to apply to")
@click.option("--headless/--no-headless", default=None, help="Run in headless mode")
def naukri_apply(limit: int, headless: bool):
    """Auto-apply to matching jobs on Naukri."""
    with get_browser(headless=headless) as browser:
        page = browser.new_page()
        if not is_naukri_logged_in(page):
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
        if not is_linkedin_logged_in(page):
            console.print("[bold red]Please log into LinkedIn first using 'python main.py login --platform linkedin'[/bold red]")
            return
        run_linkedin_easy_apply(page, limit=limit)
        print_stats_table()

@cli.command("scrape")
@click.option("--platform", type=click.Choice(["all", "linkedin", "naukri"]), default="all")
@click.option("--headless/--no-headless", default=None, help="Run in headless mode")
def scrape(platform: str, headless: bool):
    """Scrape and track matching jobs without applying."""
    with get_browser(headless=headless) as browser:
        page = browser.new_page()

        if platform in ("all", "naukri"):
            for kw in settings.naukri.search_keywords:
                for loc in settings.naukri.locations:
                    scrape_naukri_jobs(page, keyword=kw, location=loc, max_pages=2)

        if platform in ("all", "linkedin"):
            for kw in settings.linkedin.search_keywords:
                for loc in settings.linkedin.locations:
                    scrape_linkedin_jobs(page, keyword=kw, location=loc, max_jobs=20)

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
    """Full automation sequence: Boost Naukri profile -> Apply on LinkedIn -> Apply on Naukri -> Export reports."""
    console.print(Panel.fit("[bold green]Starting Complete RPA Workflow Sequence[/bold green]", title="Auto-Browser"))

    with get_browser(headless=headless) as browser:
        page = browser.new_page()

        # Step 1: Naukri Profile Refresh
        console.print("\n[bold cyan]Step 1: Refreshing Naukri Profile Booster...[/bold cyan]")
        try:
            refresh_naukri_profile(page)
        except Exception as e:
            log.error(f"Naukri refresh step failed: {e}")

        # Step 2: LinkedIn Easy Apply
        console.print("\n[bold cyan]Step 2: Running LinkedIn Easy Apply...[/bold cyan]")
        try:
            if is_linkedin_logged_in(page):
                run_linkedin_easy_apply(page, limit=limit)
            else:
                log.warning("LinkedIn session inactive. Skipping LinkedIn apply.")
        except Exception as e:
            log.error(f"LinkedIn apply step failed: {e}")

        # Step 3: Naukri Auto-Apply
        console.print("\n[bold cyan]Step 3: Running Naukri Auto-Apply...[/bold cyan]")
        try:
            if is_naukri_logged_in(page):
                run_naukri_auto_apply(page, limit=limit)
            else:
                log.warning("Naukri session inactive. Skipping Naukri apply.")
        except Exception as e:
            log.error(f"Naukri apply step failed: {e}")

    # Step 4: Summary & Export
    console.print("\n[bold cyan]Step 4: Generating Metrics & Reports...[/bold cyan]")
    print_stats_table()
    export_reports()
    console.print("\n[bold green]✓ Complete RPA Workflow sequence finished successfully![/bold green]")

if __name__ == "__main__":
    cli()
