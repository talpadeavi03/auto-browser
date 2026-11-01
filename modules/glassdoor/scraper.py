import urllib.parse
from typing import Dict, List, Optional
from playwright.sync_api import Page
from config.config import settings
from core.browser import BrowserManager
from core.logger import log
from core.storage import db
from core.ai_matcher import ai_matcher

def construct_glassdoor_search_url(keyword: str, location: str) -> str:
    """Constructs a search URL on Glassdoor India with keywords and location."""
    params = {
        "sc.keyword": keyword,
        "locT": "C",
        "locKeyword": location,
        "fromAge": "14",
    }
    return f"https://www.glassdoor.co.in/Job/jobs.htm?{urllib.parse.urlencode(params)}"

def scrape_glassdoor_jobs(page: Page, keyword: str, location: str, max_jobs: int = 15) -> List[Dict[str, str]]:
    """Scrapes matching job cards from Glassdoor search results with AI semantic reranking."""
    search_url = construct_glassdoor_search_url(keyword=keyword, location=location)
    log.info(f"[cyan]Searching Glassdoor: '{keyword}' in '{location}' -> {search_url}[/cyan]")

    scraped_jobs = []
    try:
        try:
            page.goto(search_url, timeout=30000, wait_until="domcontentloaded")
            BrowserManager.human_delay(2.5, 4.0)
        except Exception as g_err:
            log.warning(f"Note navigating to Glassdoor search: {g_err}")

        # Close any sign-in overlay popup if Glassdoor presents it
        try:
            close_btn = page.locator("button.CloseButton, button[aria-label='Close'], button.modal_closeIcon, [data-test='modal-close']").first
            if close_btn.is_visible(timeout=2000):
                close_btn.click()
                BrowserManager.human_delay(1.0, 1.8)
        except Exception:
            pass

        BrowserManager.human_scroll(page, steps=3, distance=400)
        BrowserManager.human_delay(1.5, 2.5)

        card_selectors = [
            "li[data-test='jobListing']",
            "div.jobListing",
            "article.jobCard",
            "div.JobCard_jobCardContainer___h2pQ",
            "div[data-jobid]",
            "li.JobsList_jobListItem__wl4dg",
        ]

        cards = []
        for sel in card_selectors:
            elements = page.locator(sel).all()
            if elements:
                cards = elements
                break

        log.info(f"Found {len(cards)} Glassdoor job listings for '{keyword}' in '{location}'.")

        seen_ids = set()
        for card in cards:
            if len(scraped_jobs) >= max_jobs:
                break
            try:
                # Job ID
                job_id = card.get_attribute("data-jobid") or card.get_attribute("data-id") or ""

                # Title & link
                title_elem = card.locator("a[data-test='job-title'], a.JobCard_jobTitle___daas, a.job-title, h3 a, a.jobTitle").first
                if title_elem.count() == 0:
                    continue

                job_title = title_elem.inner_text().strip()
                if not job_title or len(job_title) > 120:
                    continue

                href = title_elem.get_attribute("href") or ""
                if not href and job_id:
                    clean_url = f"https://www.glassdoor.co.in/job-listing/?jl={job_id}"
                elif href.startswith("http"):
                    clean_url = href.split("?")[0]
                elif href:
                    clean_url = f"https://www.glassdoor.co.in{href}".split("?")[0]
                else:
                    clean_url = f"https://www.glassdoor.co.in/job-listing/?jl={job_id}" if job_id else ""

                if not job_id and clean_url and "jl=" in clean_url:
                    job_id = clean_url.split("jl=")[-1].split("&")[0]

                if not clean_url or (job_id and job_id in seen_ids):
                    continue
                if job_id:
                    seen_ids.add(job_id)

                # Company
                comp_elem = card.locator("span[data-test='employer-short-name'], div.EmployerProfile_employerName__, div.JobCard_employerName__, span.employerName").first
                company = comp_elem.inner_text().strip() if comp_elem.count() > 0 else "Unknown Employer"

                # Location
                loc_elem = card.locator("div[data-test='emp-location'], div.JobCard_location__, span.loc").first
                loc = loc_elem.inner_text().strip() if loc_elem.count() > 0 else location

                # Salary
                sal_elem = card.locator("div[data-test='detailSalary'], span[data-test='detailSalary']").first
                salary = sal_elem.inner_text().strip() if sal_elem.count() > 0 else ""

                # Snippet
                snip_elem = card.locator("div.JobCard_jobDescriptionSnippet__, div[data-test='descSnippet']").first
                snippet = snip_elem.inner_text().strip() if snip_elem.count() > 0 else ""

                # Cross-Encoder Semantic Compatibility Score
                match_score = ai_matcher.score_job(job_title=job_title, company=company, snippet=snippet)

                job_data = {
                    "platform": "glassdoor",
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
                    platform="glassdoor",
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
                log.debug(f"Error parsing Glassdoor card: {card_err}")
                continue

    except Exception as e:
        log.error(f"[red]Error scraping Glassdoor: {e}[/red]")

    log.info(f"[green]✓ Completed scraping {len(scraped_jobs)} jobs from Glassdoor for '{keyword}'.[/green]")
    return scraped_jobs
