import urllib.parse
from typing import Dict, List, Optional
from playwright.sync_api import Page
from config.config import settings
from core.browser import BrowserManager
from core.logger import log
from core.storage import db
from core.ai_matcher import ai_matcher

def construct_foundit_search_url(keyword: str, location: str) -> str:
    """Constructs a search URL on Foundit India (formerly Monster) with keywords and location."""
    params = {
        "query": keyword,
        "locations": location,
    }
    return f"https://www.foundit.in/srp/results?{urllib.parse.urlencode(params)}"

def scrape_foundit_jobs(page: Page, keyword: str, location: str, max_jobs: int = 15) -> List[Dict[str, str]]:
    """Scrapes matching job cards from Foundit search results with AI semantic reranking."""
    search_url = construct_foundit_search_url(keyword=keyword, location=location)
    log.info(f"[cyan]Searching Foundit: '{keyword}' in '{location}' -> {search_url}[/cyan]")

    scraped_jobs = []
    try:
        try:
            page.goto(search_url, timeout=30000, wait_until="domcontentloaded")
            BrowserManager.human_delay(2.5, 4.0)
        except Exception as g_err:
            log.warning(f"Note navigating to Foundit search: {g_err}")

        # Anti-detect human scroll down
        BrowserManager.human_scroll(page, steps=3, distance=450)
        BrowserManager.human_delay(1.5, 2.5)

        card_selectors = [
            "div.cardContainer",
            "div.srpResultCard",
            "div.job-card",
            "div[id^='job-card']",
            "div.srpCard",
            "div.card-body",
        ]

        cards = []
        for sel in card_selectors:
            elements = page.locator(sel).all()
            if elements:
                cards = elements
                break

        log.info(f"Found {len(cards)} Foundit job listings for '{keyword}' in '{location}'.")

        seen_ids = set()
        for card in cards:
            if len(scraped_jobs) >= max_jobs:
                break
            try:
                # Job ID
                job_id = card.get_attribute("id") or card.get_attribute("data-job-id") or ""

                # Title & link
                title_elem = card.locator("h3.jobTitle a, div.jobTitle a, a.cardTitle, a.title, h3 a").first
                if title_elem.count() == 0:
                    continue

                job_title = title_elem.inner_text().strip()
                if not job_title or len(job_title) > 120:
                    continue

                href = title_elem.get_attribute("href") or ""
                if not href and job_id:
                    clean_url = f"https://www.foundit.in/job/{job_id}"
                elif href.startswith("http"):
                    clean_url = href.split("?")[0]
                elif href:
                    clean_url = f"https://www.foundit.in{href}".split("?")[0]
                else:
                    clean_url = f"https://www.foundit.in/job/{job_id}" if job_id else ""

                if not job_id and clean_url:
                    parts = [p for p in clean_url.split("-") if p]
                    if parts and parts[-1].isdigit():
                        job_id = parts[-1]

                if not clean_url or (job_id and job_id in seen_ids):
                    continue
                if job_id:
                    seen_ids.add(job_id)

                # Company
                comp_elem = card.locator("div.companyName a, p.companyName, span.company, a.company").first
                company = comp_elem.inner_text().strip() if comp_elem.count() > 0 else "Unknown Employer"

                # Location
                loc_elem = card.locator("div.location, span.loc, p.cardLocation, div.details:has-text('location')").first
                loc = loc_elem.inner_text().strip() if loc_elem.count() > 0 else location

                # Experience & Salary
                exp_elem = card.locator("div.experience, span.exp, p.cardExp").first
                experience = exp_elem.inner_text().strip() if exp_elem.count() > 0 else ""

                sal_elem = card.locator("div.salary, span.salary, p.cardSalary").first
                salary = sal_elem.inner_text().strip() if sal_elem.count() > 0 else ""

                # Snippet / Skills
                snip_elem = card.locator("div.skillDetails, div.jobDescription, p.desc").first
                snippet = snip_elem.inner_text().strip() if snip_elem.count() > 0 else ""

                # Cross-Encoder Semantic Compatibility Score
                match_score = ai_matcher.score_job(job_title=job_title, company=company, snippet=snippet)

                job_data = {
                    "platform": "foundit",
                    "job_id": job_id,
                    "job_title": job_title,
                    "company": company,
                    "location": loc,
                    "experience": experience,
                    "salary": salary,
                    "snippet": snippet,
                    "job_url": clean_url,
                    "match_score": match_score
                }

                db.record_scraped_job(
                    platform="foundit",
                    job_id=job_id,
                    job_title=job_title,
                    company=company,
                    location=loc,
                    experience=experience,
                    salary=salary,
                    job_url=clean_url,
                    match_score=match_score,
                    snippet=snippet
                )

                scraped_jobs.append(job_data)
            except Exception as card_err:
                log.debug(f"Error parsing Foundit card: {card_err}")
                continue

    except Exception as e:
        log.error(f"[red]Error scraping Foundit: {e}[/red]")

    log.info(f"[green]✓ Completed scraping {len(scraped_jobs)} jobs from Foundit for '{keyword}'.[/green]")
    return scraped_jobs
