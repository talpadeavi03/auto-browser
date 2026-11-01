import urllib.parse
from typing import Dict, List, Optional
from playwright.sync_api import Page
from config.config import settings
from core.browser import BrowserManager
from core.logger import log
from core.storage import db
from core.ai_matcher import ai_matcher

def construct_indeed_search_url(keyword: str, location: str) -> str:
    """Constructs search URL on Indeed with keywords and location."""
    params = {
        "q": keyword,
        "l": location,
        "fromage": "14",  # Last 14 days
        "sort": "date",
    }
    return f"https://in.indeed.com/jobs?{urllib.parse.urlencode(params)}"

def scrape_indeed_jobs(page: Page, keyword: str, location: str, max_pages: int = 1) -> List[Dict[str, str]]:
    """Scrapes matching job cards from Indeed search results with AI semantic reranking."""
    search_url = construct_indeed_search_url(keyword=keyword, location=location)
    log.info(f"[cyan]Searching Indeed: '{keyword}' in '{location}' -> {search_url}[/cyan]")

    scraped_jobs = []
    try:
        try:
            page.goto(search_url, timeout=30000, wait_until="domcontentloaded")
            BrowserManager.human_delay(2.5, 4.0)
        except Exception as g_err:
            log.warning(f"Note navigating to Indeed search: {g_err}")

        # Human scroll down to trigger dynamic loading of job cards
        BrowserManager.human_scroll(page, steps=3, distance=400)
        BrowserManager.human_delay(1.5, 2.5)

        card_selectors = [
            "div.job_seen_beacon",
            "div[class*='job_seen_beacon' i]",
            "div[class*='cardOutline' i]",
            "div.jobCard_mainContent",
            "td.resultContent",
            "div[data-jk]",
            "li:has(div.job_seen_beacon)",
            "ul.css-zu9cdh li",
            "li:has(a[data-jk])",
            "div.slider_container div[class*='job' i]",
        ]

        cards = []
        for sel in card_selectors:
            elements = page.locator(sel).all()
            if elements:
                cards = elements
                break

        log.info(f"Found {len(cards)} Indeed job listings for '{keyword}' in '{location}'.")

        seen_ids = set()
        for card in cards:
            try:
                # Job ID
                job_id = card.get_attribute("data-jk") or ""
                if not job_id:
                    link_with_jk = card.locator("a[data-jk]").first
                    if link_with_jk.count() > 0:
                        job_id = link_with_jk.get_attribute("data-jk") or ""

                # Title & link
                title_elem = card.locator("h2.jobTitle span, h2.jobTitle a, a.jcs-JobTitle, a[data-jk], h2 a, a[class*='JobTitle' i], a").first
                if title_elem.count() == 0:
                    continue

                job_title = title_elem.inner_text().strip()
                if not job_title or len(job_title) > 150:
                    continue

                link_elem = card.locator("a[data-jk], h2.jobTitle a, a.jcs-JobTitle").first
                href = (link_elem.get_attribute("href") if link_elem.count() > 0 else "") or ""
                if not href and job_id:
                    clean_url = f"https://in.indeed.com/viewjob?jk={job_id}"
                elif href.startswith("http"):
                    clean_url = href.split("&")[0]
                elif href:
                    clean_url = f"https://in.indeed.com{href}".split("&")[0]
                else:
                    clean_url = f"https://in.indeed.com/viewjob?jk={job_id}" if job_id else ""

                if not job_id and clean_url and "jk=" in clean_url:
                    job_id = clean_url.split("jk=")[-1].split("&")[0]

                if not clean_url or (job_id and job_id in seen_ids):
                    continue
                if job_id:
                    seen_ids.add(job_id)

                # Company
                comp_elem = card.locator("span[data-testid='company-name'], span.companyName, span.css-63koeb").first
                company = comp_elem.inner_text().strip() if comp_elem.count() > 0 else "Unknown Employer"

                # Location
                loc_elem = card.locator("div[data-testid='text-location'], div.companyLocation").first
                loc = loc_elem.inner_text().strip() if loc_elem.count() > 0 else location

                # Salary
                sal_elem = card.locator("div.salary-snippet-container, div[data-testid='attribute_snippet_testid']").first
                salary = sal_elem.inner_text().strip() if sal_elem.count() > 0 else ""

                # Snippet
                snip_elem = card.locator("div.job-snippet, ul.job-snippet, div.css-9446fg").first
                snippet = snip_elem.inner_text().strip() if snip_elem.count() > 0 else ""

                # Cross-Encoder Semantic Compatibility Score
                match_score = ai_matcher.score_job(job_title=job_title, company=company, snippet=snippet)

                job_data = {
                    "platform": "indeed",
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
                    platform="indeed",
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
                log.debug(f"Error parsing Indeed card: {card_err}")
                continue

    except Exception as e:
        log.error(f"[red]Error scraping Indeed: {e}[/red]")

    log.info(f"[green]✓ Completed scraping {len(scraped_jobs)} jobs from Indeed for '{keyword}'.[/green]")
    return scraped_jobs
