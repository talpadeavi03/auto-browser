import urllib.parse
from typing import Dict, List, Optional
from playwright.sync_api import Page
from config.config import settings
from core.browser import BrowserManager
from core.logger import log
from core.storage import db

def construct_naukri_search_url(keyword: str, location: str, experience_years: Optional[int] = None) -> str:
    """Constructs a search URL on Naukri with keywords, location, and experience filter."""
    kw_slug = keyword.lower().strip().replace(" ", "-")
    loc_slug = location.lower().strip().replace(" ", "-").replace("/", "")
    base_url = f"https://www.naukri.com/{kw_slug}-jobs-in-{loc_slug}"

    params = {
        "k": keyword,
        "l": location,
    }
    if experience_years is not None:
        try:
            params["experience"] = str(int(float(experience_years)))
        except (ValueError, TypeError):
            pass

    return f"{base_url}?{urllib.parse.urlencode(params)}"

def scrape_naukri_jobs(page: Page, keyword: str, location: str, max_pages: int = 2) -> List[Dict[str, str]]:
    """Scrapes job postings from Naukri search results."""
    search_url = construct_naukri_search_url(
        keyword=keyword,
        location=location,
        experience_years=settings.naukri.experience_years
    )
    log.info(f"[cyan]Searching Naukri: '{keyword}' in '{location}' -> {search_url}[/cyan]")

    scraped_jobs = []
    try:
        page.goto(search_url, timeout=30000, wait_until="domcontentloaded")
        BrowserManager.human_delay(2.5, 4.0)

        for page_num in range(1, max_pages + 1):
            log.info(f"Scraping Naukri page {page_num} for '{keyword}'...")
            BrowserManager.human_scroll(page, steps=4, distance=450)
            BrowserManager.human_delay(1.5, 2.5)

            # Job tuple wrappers
            card_selectors = [
                "div.srp-jobtuple-wrapper",
                "article.jobTuple",
                "div.cust-job-tuple",
            ]

            cards = []
            for sel in card_selectors:
                elements = page.locator(sel).all()
                if elements:
                    cards = elements
                    break

            log.info(f"Found {len(cards)} job listings on page {page_num}.")

            for card in cards:
                try:
                    title_elem = card.locator("a.title").first
                    if not title_elem.is_visible():
                        continue

                    job_title = title_elem.inner_text().strip()
                    job_url = title_elem.get_attribute("href") or ""
                    if not job_url:
                        continue

                    # Extract company
                    company = "Unknown"
                    comp_elem = card.locator("a.comp-name, .comp-name").first
                    if comp_elem.is_visible():
                        company = comp_elem.inner_text().strip()

                    # Experience
                    exp = ""
                    exp_elem = card.locator("span.exp-wrap, span.exp, li.experience").first
                    if exp_elem.is_visible():
                        exp = exp_elem.inner_text().strip()

                    # Salary
                    sal = ""
                    sal_elem = card.locator("span.sal-wrap, span.sal, li.salary").first
                    if sal_elem.is_visible():
                        sal = sal_elem.inner_text().strip()

                    # Location
                    loc = location
                    loc_elem = card.locator("span.loc-wrap, span.loc, li.location").first
                    if loc_elem.is_visible():
                        loc = loc_elem.inner_text().strip()

                    # Job ID from URL if present
                    job_id = ""
                    if "job-listings-" in job_url:
                        parts = job_url.split("job-listings-")[-1].split("?")[0]
                        job_id = parts

                    # Job snippet & Skill tags
                    snippet = ""
                    try:
                        desc_elem = card.locator("span.job-desc, .job-desc, .job-description").first
                        if desc_elem.is_visible():
                            snippet = desc_elem.inner_text().strip()
                        tags_elems = card.locator("ul.tags-gt li, .tags-gt li, .tag-li").all()
                        if tags_elems:
                            tag_texts = [t.inner_text().strip() for t in tags_elems if t.inner_text().strip()]
                            if tag_texts:
                                snippet = f"{snippet} | Skills: {', '.join(tag_texts[:5])}" if snippet else f"Skills: {', '.join(tag_texts[:5])}"
                    except Exception:
                        pass

                    job_data = {
                        "platform": "naukri",
                        "job_id": job_id,
                        "job_title": job_title,
                        "company": company,
                        "location": loc,
                        "experience": exp,
                        "salary": sal,
                        "job_url": job_url,
                        "snippet": snippet,
                    }

                    # Store in SQLite
                    db.record_scraped_job(
                        platform="naukri",
                        job_id=job_id,
                        job_title=job_title,
                        company=company,
                        location=loc,
                        experience=exp,
                        salary=sal,
                        job_url=job_url,
                        snippet=snippet
                    )

                    scraped_jobs.append(job_data)
                except Exception as card_err:
                    log.debug(f"Error parsing job card: {card_err}")
                    continue

            # Pagination: Click next if not on final page
            if page_num < max_pages:
                next_btn_selectors = [
                    "a.fright.fs14.btn-secondary:has-text('Next')",
                    "a:has-text('Next')",
                    "div.pagination a:has-text('Next')",
                ]
                next_btn = None
                for n_sel in next_btn_selectors:
                    cand = page.locator(n_sel).first
                    if cand.is_visible():
                        next_btn = cand
                        break

                if next_btn:
                    BrowserManager.safe_click(next_btn)
                    BrowserManager.human_delay(2.5, 4.0)
                else:
                    log.info("No further pages found.")
                    break

    except Exception as e:
        log.error(f"[red]Error scraping Naukri: {e}[/red]")

    log.info(f"[green]✓ Completed scraping {len(scraped_jobs)} jobs from Naukri for '{keyword}'.[/green]")
    return scraped_jobs
