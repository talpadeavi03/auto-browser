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
        "[bold cyan]Interactive Login Session[/bold cyan]\n\n"
        "1. A browser window will open on your screen.\n"
        "2. Enter your credentials, solve any OTP/2FA or Captchas.\n"
        "3. Once you see your feed or profile, press [bold green]Enter[/bold green] in this terminal.\n"
        "[dim]The browser will stay completely still and will NOT refresh while you type.[/dim]",
        title="RPA Login Setup"
    ))

    # Always headful for manual login
    with get_browser(headless=False) as browser:
        page = browser.new_page()

        # LinkedIn login
        if platform in ("all", "linkedin"):
            console.print("\n[bold yellow]Navigating to LinkedIn Login...[/bold yellow]")
            page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
            
            # Auto-fill credentials if provided in env
            user = os.getenv("LINKEDIN_USERNAME")
            pwd = os.getenv("LINKEDIN_PASSWORD")
            if user and pwd:
                log.info("Prefilling LinkedIn credentials from environment...")
                try:
                    page.locator("#username").fill(user)
                    page.locator("#password").fill(pwd)
                except Exception as e:
                    log.debug(f"Auto-fill note: {e}")

            console.print("\n[bold cyan]👉 Please log into LinkedIn in the opened Brave window.[/bold cyan]")
            Prompt.ask("[bold green]Press Enter here once you have finished logging in and see your LinkedIn feed[/bold green]")

            if is_linkedin_logged_in(page, navigate=True):
                console.print("[bold green]✓ LinkedIn authenticated successfully! Session stored.[/bold green]")
            else:
                console.print("[bold yellow]LinkedIn session cookies have been saved to disk.[/bold yellow]")

        # Naukri login
        if platform in ("all", "naukri"):
            console.print("\n[bold yellow]Navigating to Naukri.com Login...[/bold yellow]")
            page.goto(NAUKRI_LOGIN_URL, wait_until="domcontentloaded")

            # Auto-fill credentials if provided in env
            n_user = os.getenv("NAUKRI_USERNAME")
            n_pwd = os.getenv("NAUKRI_PASSWORD")
            if n_user and n_pwd:
                log.info("Prefilling Naukri credentials from environment...")
                try:
                    page.locator("input[placeholder*='Username' i], input[placeholder*='Email' i]").first.fill(n_user)
                    page.locator("input[type='password']").first.fill(n_pwd)
                except Exception as e:
                    log.debug(f"Auto-fill note: {e}")

            console.print("\n[bold cyan]👉 Please log into Naukri in the opened Brave window.[/bold cyan]")
            Prompt.ask("[bold green]Press Enter here once you have finished logging in and see your Naukri dashboard[/bold green]")

            if is_naukri_logged_in(page, navigate=True):
                console.print("[bold green]✓ Naukri authenticated successfully! Session stored.[/bold green]")
            else:
                console.print("[bold yellow]Naukri session cookies have been saved to disk.[/bold yellow]")

    console.print("\n[bold green]Login procedure completed! Session saved in data/browser_profile.[/bold green]")

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

    # Step 4: Summary & Export
    console.print("\n[bold cyan]Step 4: Generating Metrics & Reports...[/bold cyan]")
    print_stats_table()
    export_reports()
    console.print("\n[bold green]✓ Complete RPA Workflow sequence finished successfully![/bold green]")

@cli.command("export-auth")
def export_auth():
    """Export active authenticated cookies for 24/7 cloud execution (GitHub Actions)."""
    console.print(Panel.fit("[bold cyan]Exporting Authenticated Session for Cloud CI/CD[/bold cyan]"))
    with get_browser() as browser:
        context = browser.context
        cookies = context.cookies()
        filtered = [c for c in cookies if any(d in c.get("domain", "") for d in ["naukri.com", "linkedin.com"])]
        
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

if __name__ == "__main__":
    cli()
