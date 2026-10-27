#!/usr/bin/env python3
"""
Model Context Protocol (MCP) Server for Job RPA (Naukri & LinkedIn).
Enables AI models to:
1. Search jobs across target positions (DevOps, MLOps, System, DevSecOps, Infrastructure, Cloud).
2. Read and understand full job descriptions and required skills.
3. Inspect LinkedIn Easy Apply modal questions step-by-step.
4. Reason and fill out screening answers accurately based on the candidate's resume/profile.
5. Apply directly to Naukri 1-Click jobs.
6. Boost candidate profile ranking on Naukri to #1 "Active Today".
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from mcp.server.mcpserver import MCPServer

from config.config import settings
from core.browser import get_browser, BrowserManager
from core.logger import log
from core.storage import db
from core.ai_assistant import ai_assistant
from modules.naukri.profile_updater import refresh_naukri_profile, is_naukri_logged_in
from modules.naukri.scraper import scrape_naukri_jobs
from modules.naukri.auto_apply import apply_to_naukri_job
from modules.linkedin.scraper import scrape_linkedin_jobs, is_linkedin_logged_in
from modules.linkedin.easy_apply import apply_to_linkedin_easy_apply
from modules.external.universal_apply import UniversalATSApplier
from modules.tracker.export import export_reports

mcp = MCPServer(
    name="AutoBrowser-Job-RPA",
    instructions=(
        "MCP Server for intelligent job application automation on LinkedIn and Naukri. "
        "Allows AI agents to search jobs, inspect detailed requirements, read and understand "
        "Easy Apply questions, provide context-aware answers, and submit applications."
    )
)

@mcp.tool()
def get_candidate_profile() -> Dict[str, Any]:
    """
    Returns the candidate's profile information, target roles, contact info,
    work authorization, and experience details used to answer job screening questions.
    """
    return {
        "candidate": {
            "first_name": settings.profile.first_name,
            "last_name": settings.profile.last_name,
            "full_name": f"{settings.profile.first_name} {settings.profile.last_name}",
            "email": settings.profile.email,
            "phone": settings.profile.phone,
            "current_location": settings.profile.current_location,
            "city": settings.profile.city,
            "state": settings.profile.state,
            "country": settings.profile.country,
            "postal_code": settings.profile.postal_code,
            "linkedin_url": settings.profile.linkedin_url,
            "github_url": settings.profile.github_url,
            "headline": settings.profile.headline,
            "summary": settings.profile.summary,
            "degree": settings.profile.degree,
            "years_of_experience": settings.profile.years_of_experience,
            "current_salary_lpa": settings.profile.current_salary_lpa,
            "expected_salary_lpa": settings.profile.expected_salary_lpa,
            "notice_period_days": settings.profile.notice_period_days,
            "require_visa_sponsorship": settings.profile.require_visa_sponsorship,
            "authorized_to_work": settings.profile.authorized_to_work,
            "resume_path": settings.profile.resume_path,
        },
        "target_positions": [
            "DevOps Engineer",
            "MLOps Engineer",
            "DevSecOps Engineer",
            "Cloud Engineer",
            "Infrastructure Engineer",
            "System Engineer",
        ],
        "target_locations": settings.linkedin.locations,
    }

@mcp.tool()
def search_jobs(
    platform: str,
    keyword: str,
    location: str = "India",
    max_results: int = 15
) -> Dict[str, Any]:
    """
    Searches for live jobs on LinkedIn or Naukri matching the specified keyword and location.
    
    Args:
        platform: 'linkedin' or 'naukri'
        keyword: Target role (e.g., 'devops', 'mlops', 'system', 'devsecops', 'infrastructure', 'cloud')
        location: Target city or region (e.g., 'Pune', 'Bengaluru', 'Remote', 'India')
        max_results: Maximum job listings to retrieve (default: 15)
    """
    platform = platform.lower().strip()
    with get_browser() as browser:
        page = browser.new_page()
        if platform == "naukri":
            jobs = scrape_naukri_jobs(page, keyword=keyword, location=location, max_pages=1)
            results = jobs[:max_results]
        elif platform == "linkedin":
            results = scrape_linkedin_jobs(page, keyword=keyword, location=location, max_jobs=max_results)
        else:
            return {"error": f"Unsupported platform: {platform}. Choose 'linkedin' or 'naukri'."}

    return {
        "platform": platform,
        "keyword": keyword,
        "location": location,
        "count": len(results),
        "jobs": results
    }

@mcp.tool()
def inspect_job_description(platform: str, job_url: str) -> Dict[str, Any]:
    """
    Navigates to a specific job listing URL and extracts the full job description,
    required skills, company information, and application type so the AI can evaluate match.
    
    Args:
        platform: 'linkedin' or 'naukri'
        job_url: Full URL of the job posting
    """
    with get_browser() as browser:
        page = browser.new_page()
        page.goto(job_url, timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)

        title = page.title()
        description_text = ""
        has_easy_apply = False
        has_naukri_apply = False

        if "linkedin.com" in job_url:
            # Check for description container
            desc_elem = page.locator(".jobs-description__content, .jobs-description-content, article, main").first
            if desc_elem.is_visible():
                description_text = desc_elem.inner_text().strip()
            
            # Check if Easy Apply is available
            ea_btn = page.locator("button.jobs-apply-button, button:has-text('Easy Apply')").first
            has_easy_apply = ea_btn.is_visible() and "easy apply" in ea_btn.inner_text().lower()

        elif "naukri.com" in job_url:
            desc_elem = page.locator("section.job-desc, div.dang-empty-desc, div.styles_jhc__header__Pcx2K ~ section").first
            if desc_elem.is_visible():
                description_text = desc_elem.inner_text().strip()
            else:
                body_elem = page.locator("main, article").first
                if body_elem.is_visible():
                    description_text = body_elem.inner_text().strip()

            apply_btn = page.locator("#apply-button, button.apply-button, button:has-text('Apply')").first
            has_naukri_apply = apply_btn.is_visible()

        return {
            "platform": platform,
            "job_url": job_url,
            "page_title": title,
            "has_easy_apply": has_easy_apply,
            "has_naukri_direct_apply": has_naukri_apply,
            "description_snippet": description_text[:3000],
            "full_description_length": len(description_text)
        }

@mcp.tool()
def linkedin_inspect_easy_apply_step(job_url: str) -> Dict[str, Any]:
    """
    Opens a LinkedIn job, clicks 'Easy Apply', and reads all questions/form fields on the current step.
    Returns structured question details (labels, input types, radio choices, dropdown options)
    so the AI model can understand the exact questions being asked.
    
    Args:
        job_url: LinkedIn job posting URL (e.g. 'https://www.linkedin.com/jobs/view/123456789/')
    """
    with get_browser() as browser:
        page = browser.new_page()
        page.goto(job_url, timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)

        # Check for Easy Apply button
        apply_btn = page.locator("button.jobs-apply-button, button:has-text('Easy Apply')").first
        if not apply_btn.is_visible():
            return {
                "status": "NO_EASY_APPLY",
                "message": "Easy Apply button not found on this job."
            }

        BrowserManager.safe_click(apply_btn)
        page.wait_for_timeout(2000)

        modal = page.locator("div.jobs-easy-apply-modal, div[role='dialog']:has-text('Easy Apply')").first
        if not modal.is_visible():
            return {"status": "MODAL_NOT_OPEN", "message": "Easy Apply modal failed to open."}

        # Inspect form fields on current step
        step_title = ""
        header = modal.locator("h3, h2").first
        if header.is_visible():
            step_title = header.inner_text().strip()

        fields = []

        # 1. Text & Numeric inputs
        for inp in modal.locator("input[type='text'], input[type='number']").all():
            if inp.is_visible():
                lbl = ""
                parent = inp.locator("xpath=../..").first
                if parent.is_visible():
                    lbl = parent.inner_text().strip().split("\n")[0]
                fields.append({
                    "type": "text_input",
                    "id": inp.get_attribute("id") or "",
                    "label": lbl,
                    "current_value": inp.input_value(),
                })

        # 2. Fieldsets / Radio questions
        for fs in modal.locator("fieldset").all():
            if fs.is_visible():
                legend = fs.locator("legend").first
                question = legend.inner_text().strip() if legend.is_visible() else fs.inner_text().split("\n")[0]
                options = [o.inner_text().strip() for o in fs.locator("label").all() if o.is_visible()]
                fields.append({
                    "type": "radio_group",
                    "question": question,
                    "options": options,
                })

        # 3. Dropdowns
        for sel in modal.locator("select").all():
            if sel.is_visible():
                lbl = ""
                parent = sel.locator("xpath=../..").first
                if parent.is_visible():
                    lbl = parent.inner_text().strip().split("\n")[0]
                opts = [o.inner_text().strip() for o in sel.locator("option").all()]
                fields.append({
                    "type": "select_dropdown",
                    "label": lbl,
                    "options": opts,
                })

        # Check available action buttons
        has_next = modal.locator("button:has-text('Next')").first.is_visible()
        has_review = modal.locator("button:has-text('Review')").first.is_visible()
        has_submit = modal.locator("button:has-text('Submit application')").first.is_visible()

        return {
            "status": "STEP_INSPECTED",
            "step_title": step_title,
            "fields_count": len(fields),
            "fields": fields,
            "actions": {
                "has_next": has_next,
                "has_review": has_review,
                "has_submit": has_submit
            }
        }

@mcp.tool()
def apply_linkedin_easy_apply_smart(
    job_url: str,
    job_title: str = "Target Position",
    company: str = "Hiring Company"
) -> Dict[str, Any]:
    """
    Executes an intelligent, multi-step Easy Apply on LinkedIn:
    Reads each page, answers standard screening questions (DevOps, Cloud, notice period, authorization),
    uploads the user's resume, and submits the application.
    
    Args:
        job_url: Direct URL to the LinkedIn job posting
        job_title: Title of the role
        company: Name of the company
    """
    with get_browser() as browser:
        page = browser.new_page()
        res = apply_to_linkedin_easy_apply(
            page=page,
            job_url=job_url,
            job_title=job_title,
            company=company
        )
        return {
            "status": res,
            "job_url": job_url,
            "job_title": job_title,
            "company": company
        }

@mcp.tool()
def apply_naukri_direct(
    job_url: str,
    job_title: str = "Target Position",
    company: str = "Hiring Company"
) -> Dict[str, Any]:
    """
    Applies directly to a 1-Click job on Naukri.com, answering basic screening questions
    using the candidate's profile data.
    
    Args:
        job_url: Direct URL to the Naukri job posting
        job_title: Title of the role
        company: Name of the company
    """
    with get_browser() as browser:
        page = browser.new_page()
        res = apply_to_naukri_job(
            page=page,
            job_url=job_url,
            job_title=job_title,
            company=company
        )
        return {
            "status": res,
            "job_url": job_url,
            "job_title": job_title,
            "company": company
        }

@mcp.tool()
def boost_naukri_profile() -> Dict[str, Any]:
    """
    Refreshes the candidate's Resume Headline timestamp on Naukri.com to trigger
    Naukri's freshness ranking, making the profile rank as 'Active Today' in recruiter searches.
    """
    with get_browser() as browser:
        page = browser.new_page()
        success = refresh_naukri_profile(page)
        return {
            "success": success,
            "action": "resume_headline_refresh",
            "message": "Naukri profile boosted to 'Active Today'" if success else "Failed to refresh profile"
        }

@mcp.tool()
def get_application_history(limit: int = 25) -> Dict[str, Any]:
    """
    Returns the recent history of applied and scraped jobs from the internal SQLite database.
    """
    stats = db.get_stats()
    return {
        "stats": stats,
        "database_path": str(db.db_path)
    }

@mcp.tool()
def ai_answer_screening_question(
    question: str,
    field_type: str = "text",
    options: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Uses Gemini AI and the candidate's actual resume/profile to generate the optimal, truthful
    answer to any recruiter's screening question (e.g. years of Kubernetes, Terraform experience, essay responses).
    
    Args:
        question: The exact question prompt asked on the job form
        field_type: 'text', 'number', 'radio', or 'dropdown'
        options: Optional list of available choices for radio or dropdown fields
    """
    if not ai_assistant.is_active:
        return {
            "status": "NO_API_KEY",
            "message": "GEMINI_API_KEY is not set. Add it in your .env file to enable Gemini answering."
        }
    ans = ai_assistant.answer_question(question, field_type=field_type, options=options)
    return {
        "status": "SUCCESS",
        "question": question,
        "field_type": field_type,
        "ai_generated_answer": ans
    }

@mcp.tool()
def generate_application_reports() -> Dict[str, str]:
    """
    Exports the complete job application tracking database to Excel (.xlsx) and CSV files.
    """
    files = export_reports()
    return files

@mcp.tool()
def apply_external_company_job(
    job_url: str,
    company: str,
    job_title: str
) -> Dict[str, Any]:
    """
    Autonomously navigates to ANY external company application page or ATS
    (Greenhouse, Lever, Workday, BambooHR, SmartRecruiters, Ashby, PyjamaHR, or company career portals),
    fills all candidate contact information, uploads candidate's PDF resume,
    uses Gemini AI to answer custom screening questions, and completes the application.

    Args:
        job_url: Direct URL to the external job application or career portal page
        company: Name of the company offering the role
        job_title: Title of the job position
    """
    with get_browser() as browser:
        page = browser.new_page()
        res = UniversalATSApplier.apply(
            page=page,
            job_url=job_url,
            job_title=job_title,
            company=company
        )
        return {
            "status": res,
            "job_url": job_url,
            "company": company,
            "job_title": job_title
        }

if __name__ == "__main__":
    # Runs standard I/O transport for MCP clients (Claude Desktop, Cursor, Antigravity, etc.)
    mcp.run()
