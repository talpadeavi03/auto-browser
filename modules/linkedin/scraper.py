import os
import urllib.parse
from typing import Dict, List, Optional
from playwright.sync_api import Page
from config.config import settings
from core.browser import BrowserManager
from core.logger import log
from core.storage import db
from core.auto_auth import auto_login_linkedin

EXP_MAP = {
    "internship": "1",
    "entry level": "2",
    "associate": "3",
    "mid-senior level": "4",
    "director": "5",
    "executive": "6",
}

DATE_MAP = {
    "past_24h": "r86400",
    "past_week": "r604800",
    "past_month": "r2592000",
}

def construct_linkedin_search_url(
    keyword: str,
    location: str,
    easy_apply_only: bool = True,
    date_posted: str = "past_week",
    experience_levels: Optional[List[str]] = None
) -> str:
    """Constructs LinkedIn Jobs search URL with targeted filters."""
    params = {
        "keywords": keyword,
        "location": location,
        "sortBy": "R", # Most relevant
    }

    if easy_apply_only:
        params["f_AL"] = "true"

    if date_posted in DATE_MAP:
        params["f_TPR"] = DATE_MAP[date_posted]

    if experience_levels:
        exp_codes = [EXP_MAP[e.lower()] for e in experience_levels if e.lower() in EXP_MAP]
        if exp_codes:
            params["f_E"] = ",".join(exp_codes)

    return f"https://www.linkedin.com/jobs/search/?{urllib.parse.urlencode(params)}"

def ensure_linkedin_english(page: Page):
    """Guarantees user's LinkedIn account site language preference is permanently English."""
    try:
        lang = page.locator("html").get_attribute("lang") or ""
        if lang and not lang.startswith("en"):
            log.info("[yellow]Detected non-English LinkedIn language. Auto-switching account to English (en_US)...[/yellow]")
            page.goto("https://www.linkedin.com/mypreferences/d/settings/language", wait_until="networkidle", timeout=25000)
            select = page.locator("select").first
            if select.is_visible():
                cur_val = select.evaluate("el => el.value")
                if cur_val != "en_US":
                    select.scroll_into_view_if_needed()
                    select.select_option("en_US")
                    page.wait_for_timeout(3000)
            log.info("[green]✓ Successfully switched and persisted LinkedIn language to English (en_US)![/green]")
    except Exception as e:
        log.debug(f"Language auto-switch note: {e}")

def is_linkedin_logged_in(page: Page, navigate: bool = False) -> bool:
    """Verifies whether user is actively authenticated on LinkedIn and enforces English."""
    try:
        if navigate:
            try:
                page.goto("https://www.linkedin.com/feed/", timeout=20000, wait_until="domcontentloaded")
                BrowserManager.human_delay(1.5, 2.5)
            except Exception as nav_err:
                log.warning(f"Initial feed check ({nav_err}). Navigating to login/feed verification...")
                try:
                    if not os.getenv("LINKEDIN_LI_AT"):
                        page.context.clear_cookies()
                    page.goto("https://www.linkedin.com/login", timeout=20000, wait_until="domcontentloaded")
                    BrowserManager.human_delay(1.5, 2.5)
                except Exception as l_err:
                    log.error(f"Failed to navigate to LinkedIn login: {l_err}")
                    return False

        current_url = page.url.lower()
        if any(x in current_url for x in ["login", "checkpoint", "authwall", "uas/login"]):
            log.warning(f"LinkedIn session inactive: page redirected to authwall/login URL: {page.url}")
            log.info("Checking for autonomous auto-login credentials...")
            if auto_login_linkedin(page):
                ensure_linkedin_english(page)
                return True
            return False

        if any(x in current_url for x in ["/feed", "/mynetwork", "/jobs", "/in/", "/mypreferences"]):
            ensure_linkedin_english(page)
            return True

        auth_indicators = [
            ".global-nav__me-photo",
            "img.global-nav__me-photo",
            "div.feed-identity-module",
            "nav.global-nav",
            "header.global-nav",
        ]
        for sel in auth_indicators:
            if page.locator(sel).first.is_visible(timeout=1500):
                ensure_linkedin_english(page)
                return True

        is_auth = ("linkedin.com" in current_url) and not any(x in current_url for x in ["login", "checkpoint", "authwall"])
        if is_auth:
            ensure_linkedin_english(page)
            return True
        
        # Last resort: try auto-login
        if auto_login_linkedin(page):
            ensure_linkedin_english(page)
            return True

        log.warning(f"LinkedIn session verification failed: Current URL is '{page.url}' (no auth indicator visible)")
        return False
    except Exception as e:
        log.warning(f"Error checking LinkedIn login status: {e}")
        return False

def scrape_linkedin_jobs(page: Page, keyword: str, location: str, max_jobs: int = 25) -> List[Dict[str, str]]:
    """Scrapes job cards from LinkedIn search results."""
    search_url = construct_linkedin_search_url(
        keyword=keyword,
        location=location,
        easy_apply_only=settings.linkedin.easy_apply_only,
        date_posted=settings.linkedin.date_posted,
        experience_levels=settings.linkedin.experience_levels
    )

    log.info(f"[cyan]Searching LinkedIn: '{keyword}' in '{location}' -> {search_url}[/cyan]")
    scraped = []

    try:
        page.goto(search_url, timeout=30000, wait_until="domcontentloaded")
        BrowserManager.human_delay(2.5, 4.0)

        # Scroll down incrementally to trigger dynamic listing load
        for _ in range(5):
            BrowserManager.human_scroll(page, steps=2, distance=500)
            BrowserManager.human_delay(1.0, 2.0)

        # Target job card containers (classic and modern search-results)
        job_card_selectors = [
            ".jobs-search__results-list li",
            ".job-search-card",
            ".base-search-card",
            "div[data-job-id]",
            "li.jobs-search-results__list-item",
            "div.job-card-container",
            "div.job-card-job-posting-card-wrapper",
            ".scaffold-layout__list-item",
        ]

        cards = []
        for sel in job_card_selectors:
            elements = page.locator(sel).all()
            if elements:
                cards = elements
                break

        log.info(f"Found {len(cards)} LinkedIn job cards in view.")

        # Fallback for direct job links if container cards not found
        if not cards:
            links = page.locator("a[href*='/jobs/view/']").all()
            log.info(f"Checking direct job links fallback: found {len(links)} links.")
            seen_ids = set()
            for l in links:
                if len(scraped) >= max_jobs:
                    break
                try:
                    title = l.inner_text().strip()
                    if not title or len(title) > 100:
                        continue
                    href = l.get_attribute("href") or ""
                    clean_url = href.split("?")[0]
                    parts = [p for p in clean_url.split("/") if p]
                    j_id = parts[-1] if parts else ""
                    if not j_id or j_id in seen_ids:
                        continue
                    seen_ids.add(j_id)

                    job_data = {
                        "platform": "linkedin",
                        "job_id": j_id,
                        "job_title": title,
                        "company": "LinkedIn Listing",
                        "location": location,
                        "job_url": clean_url,
                    }
                    db.record_scraped_job(
                        platform="linkedin",
                        job_id=j_id,
                        job_title=title,
                        company="LinkedIn Listing",
                        location=location,
                        job_url=clean_url
                    )
                    scraped.append(job_data)
                except Exception as fb_err:
                    log.debug(f"Fallback link parse error: {fb_err}")

        for card in cards:
            if len(scraped) >= max_jobs:
                break

            try:
                # Job ID
                job_id = card.get_attribute("data-occludable-job-id") or ""
                if not job_id:
                    urn = card.get_attribute("data-entity-urn") or card.get_attribute("data-job-id") or ""
                    job_id = urn.split(":")[-1] if urn else ""

                # Title & link
                title_elem = card.locator("h3, .base-search-card__title, a.job-card-list__title--link, a.job-card-container__link, .artdeco-entity-lockup__title a, a[href*='/jobs/view/']").first
                if not title_elem.count() > 0:
                    continue

                job_title = title_elem.inner_text().strip()
                if not job_title:
                    continue

                link_elem = card.locator("a[href*='/jobs/view/']").first
                href = (link_elem.get_attribute("href") if link_elem.count() > 0 else "") or (title_elem.get_attribute("href") if title_elem.count() > 0 else "") or ""
                clean_url = href.split("?")[0] if href else ""
                if not clean_url and job_id:
                    clean_url = f"https://www.linkedin.com/jobs/view/{job_id}/"
                elif clean_url and not job_id:
                    parts = [p for p in clean_url.split("-") if p]
                    if parts and parts[-1].isdigit():
                        job_id = parts[-1]

                # Company
                comp_elem = card.locator("h4, .base-search-card__subtitle, .artdeco-entity-lockup__subtitle, .job-card-container__primary-description").first
                company = comp_elem.inner_text().strip() if comp_elem.count() > 0 else "Unknown"

                # Location
                loc_elem = card.locator(".job-search-card__location, .job-card-container__metadata-item, .artdeco-entity-lockup__caption").first
                loc = loc_elem.inner_text().strip() if loc_elem.count() > 0 else location

                job_data = {
                    "platform": "linkedin",
                    "job_id": job_id,
                    "job_title": job_title,
                    "company": company,
                    "location": loc,
                    "job_url": clean_url,
                }

                db.record_scraped_job(
                    platform="linkedin",
                    job_id=job_id,
                    job_title=job_title,
                    company=company,
                    location=loc,
                    job_url=clean_url
                )

                scraped.append(job_data)
            except Exception as card_err:
                log.debug(f"Error parsing LinkedIn job card: {card_err}")
                continue

    except Exception as e:
        log.error(f"[red]Error while scraping LinkedIn: {e}[/red]")

    log.info(f"[green]✓ Completed LinkedIn scrape: {len(scraped)} jobs retrieved for '{keyword}'.[/green]")
    return scraped
