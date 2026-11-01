import urllib.parse
from typing import Dict, List, Optional
from playwright.sync_api import Page
from config.config import settings
from core.browser import BrowserManager
from core.logger import log
from core.storage import db
from core.ai_matcher import ai_matcher

def construct_ambitionbox_search_url(keyword: str, location: str) -> str:
    """Constructs a search URL on AmbitionBox (InfoEdge network) with keywords and location."""
    params = {
        "tag": keyword,
        "location": location,
    }
    return f"https://www.ambitionbox.com/jobs/search?{urllib.parse.urlencode(params)}"

def scrape_ambitionbox_jobs(page: Page, keyword: str, location: str, max_jobs: int = 15) -> List[Dict[str, str]]:
    """Scrapes matching job cards from AmbitionBox with AI semantic reranking."""
    search_url = construct_ambitionbox_search_url(keyword=keyword, location=location)
    log.info(f"[cyan]Searching AmbitionBox: '{keyword}' in '{location}' -> {search_url}[/cyan]")

    scraped_jobs = []
    try:
        try:
            page.goto(search_url, timeout=30000, wait_until="domcontentloaded")
            BrowserManager.human_delay(2.5, 4.0)
        except Exception as g_err:
            log.warning(f"Note navigating to AmbitionBox search: {g_err}")

        BrowserManager.human_scroll(page, steps=3, distance=450)
        BrowserManager.human_delay(1.5, 2.5)

        card_selectors = [
            "div.jobs-card",
            "div.job-listing-card",
            "div[data-job-id]",
            "div.content-wrapper:has(h2.title)",
            "div.job-card",
        ]

        cards = []
        for sel in card_selectors:
            elements = page.locator(sel).all()
            if elements:
                cards = elements
                break

        log.info(f"Found {len(cards)} AmbitionBox job listings for '{keyword}' in '{location}'.")

        seen_ids = set()
        for card in cards:
            if len(scraped_jobs) >= max_jobs:
                break
            try:
                # Job ID
                job_id = card.get_attribute("data-job-id") or card.get_attribute("data-id") or ""

                # Title & link
                title_elem = card.locator("h2.title a, a.title, h3.title a, h2 a, a[href*='/jobs/']").first
                if title_elem.count() == 0:
                    continue

                job_title = title_elem.inner_text().strip()
                if not job_title or len(job_title) > 120:
                    continue

                href = title_elem.get_attribute("href") or ""
                if href.startswith("http"):
                    clean_url = href.split("?")[0]
                elif href:
                    clean_url = f"https://www.ambitionbox.com{href}".split("?")[0]
                else:
                    clean_url = ""

                if not job_id and clean_url:
                    parts = [p for p in clean_url.split("-") if p]
                    if parts and parts[-1].isdigit():
                        job_id = parts[-1]

                if not clean_url or (job_id and job_id in seen_ids):
                    continue
                if job_id:
                    seen_ids.add(job_id)

                # Company
                comp_elem = card.locator("p.company-name, a.company-name, span.company-name, div.company-info p").first
                company = comp_elem.inner_text().strip() if comp_elem.count() > 0 else "AmbitionBox Partner"

                # Location
                loc_elem = card.locator("p.location, span.location, div.job-info-wrapper span:has-text('Pune'), div.job-info-wrapper span:has-text('India')").first
                loc = loc_elem.inner_text().strip() if loc_elem.count() > 0 else location

                # Experience & Salary
                exp_elem = card.locator("p.experience, span.exp, span:has-text('Yrs'), span:has-text('years')").first
                experience = exp_elem.inner_text().strip() if exp_elem.count() > 0 else ""

                sal_elem = card.locator("p.salary, span.salary, span:has-text('LPA'), span:has-text('₹')").first
                salary = sal_elem.inner_text().strip() if sal_elem.count() > 0 else ""

                # Snippet / Skills
                snip_elem = card.locator("div.skills-wrapper, div.description, p.job-desc").first
                snippet = snip_elem.inner_text().strip() if snip_elem.count() > 0 else ""

                # Cross-Encoder Semantic Compatibility Score
                match_score = ai_matcher.score_job(job_title=job_title, company=company, snippet=snippet)

                job_data = {
                    "platform": "ambitionbox",
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
                    platform="ambitionbox",
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
                log.debug(f"Error parsing AmbitionBox card: {card_err}")
                continue

    except Exception as e:
        log.error(f"[red]Error scraping AmbitionBox: {e}[/red]")

    log.info(f"[green]✓ Completed scraping {len(scraped_jobs)} jobs from AmbitionBox for '{keyword}'.[/green]")
    return scraped_jobs
