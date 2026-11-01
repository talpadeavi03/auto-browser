import urllib.parse
from typing import Dict, List, Optional
from playwright.sync_api import Page
from config.config import settings
from core.browser import BrowserManager
from core.logger import log
from core.storage import db
from core.ai_matcher import ai_matcher

def construct_jobot_search_url(keyword: str, location: str) -> str:
    """Constructs a search URL on Jobot with keywords and location."""
    params = {
        "q": keyword,
        "l": location,
    }
    return f"https://jobot.com/jobs?{urllib.parse.urlencode(params)}"

def scrape_jobot_jobs(page: Page, keyword: str, location: str, max_jobs: int = 15) -> List[Dict[str, str]]:
    """Scrapes matching job cards from Jobot with AI semantic reranking."""
    search_url = construct_jobot_search_url(keyword=keyword, location=location)
    log.info(f"[cyan]Searching Jobot: '{keyword}' in '{location}' -> {search_url}[/cyan]")

    scraped_jobs = []
    try:
        try:
            page.goto(search_url, timeout=30000, wait_until="domcontentloaded")
            BrowserManager.human_delay(2.5, 4.0)
        except Exception as g_err:
            log.warning(f"Note navigating to Jobot search: {g_err}")

        BrowserManager.human_scroll(page, steps=3, distance=450)
        BrowserManager.human_delay(1.5, 2.5)

        card_selectors = [
            "div.job-card",
            "div.job-listing",
            "div[class*='JobCard']",
            "article.job",
            "a[href^='/jobs/']",
        ]

        cards = []
        for sel in card_selectors:
            elements = page.locator(sel).all()
            if elements:
                cards = elements
                break

        log.info(f"Found {len(cards)} Jobot job listings for '{keyword}'.")

        seen_ids = set()
        for card in cards:
            if len(scraped_jobs) >= max_jobs:
                break
            try:
                # If the element itself is a link
                tag_name = card.evaluate("el => el.tagName.toLowerCase()")
                link_elem = card if tag_name == "a" else card.locator("a[href*='/jobs/'], a.job-title-link, h2 a, h3 a").first
                if link_elem.count() == 0:
                    continue

                href = link_elem.get_attribute("href") or ""
                if not href:
                    continue

                clean_url = f"https://jobot.com{href}".split("?")[0] if href.startswith("/") else href.split("?")[0]

                # Extract Job ID
                parts = [p for p in clean_url.split("/") if p]
                job_id = parts[-1] if parts else ""

                if not clean_url or (job_id and job_id in seen_ids):
                    continue
                if job_id:
                    seen_ids.add(job_id)

                # Title
                title_elem = card.locator("h2, h3, a.job-title-link, .title").first
                job_title = title_elem.inner_text().strip() if title_elem.count() > 0 else (link_elem.inner_text().strip() or keyword)
                if len(job_title) > 120:
                    job_title = job_title[:120]

                # Company
                comp_elem = card.locator("div.company, span.company, .company-name").first
                company = comp_elem.inner_text().strip() if comp_elem.count() > 0 else "Jobot Client"

                # Location
                loc_elem = card.locator("span.location, div.location, .loc").first
                loc = loc_elem.inner_text().strip() if loc_elem.count() > 0 else location

                # Salary
                sal_elem = card.locator("span.salary, div.salary, .pay").first
                salary = sal_elem.inner_text().strip() if sal_elem.count() > 0 else ""

                # Snippet
                snip_elem = card.locator("div.description, p.summary, .snippet").first
                snippet = snip_elem.inner_text().strip() if snip_elem.count() > 0 else ""

                # Cross-Encoder Semantic Compatibility Score
                match_score = ai_matcher.score_job(job_title=job_title, company=company, snippet=snippet)

                job_data = {
                    "platform": "jobot",
                    "job_id": job_id,
                    "job_title": job_title,
                    "company": company,
                    "location": loc,
                    "salary": salary,
                    "snippet": snippet,
                    "job_url": clean_url,
                    "match_score": match_score
                }

                db.record_scraped_job(
                    platform="jobot",
                    job_id=job_id,
                    job_title=job_title,
                    company=company,
                    location=loc,
                    salary=salary,
                    job_url=clean_url,
                    match_score=match_score,
                    snippet=snippet
                )

                scraped_jobs.append(job_data)
            except Exception as card_err:
                log.debug(f"Error parsing Jobot card: {card_err}")
                continue

    except Exception as e:
        log.error(f"[red]Error scraping Jobot: {e}[/red]")

    log.info(f"[green]✓ Completed scraping {len(scraped_jobs)} jobs from Jobot for '{keyword}'.[/green]")
    return scraped_jobs
