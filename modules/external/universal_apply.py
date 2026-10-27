import time
from pathlib import Path
from typing import Dict, List, Optional
from playwright.sync_api import Page, Locator, TimeoutError as PlaywrightTimeoutError

from config.config import settings
from core.browser import BrowserManager
from core.logger import log
from core.storage import db
from core.ai_assistant import ai_assistant

class UniversalATSApplier:
    """
    Intelligent Autonomous Form-Filling Engine for External ATS platforms:
    Greenhouse, Lever, Workday, BambooHR, SmartRecruiters, Ashby, PyjamaHR,
    and custom corporate career portals.
    """

    @classmethod
    def apply(cls, page: Page, job_url: str, job_title: str, company: str, job_id: str = "") -> str:
        """
        Navigates to an external job application page, fills all fields,
        attaches candidate resume, answers screening questions with Gemini, and submits.
        """
        if db.is_already_applied("external", job_url, job_id):
            log.info(f"Skipping already applied external job: {job_title} at {company}")
            return "ALREADY_APPLIED"

        log.info(f"[bold cyan]Launching Universal ATS Applier for '{job_title}' at '{company}'...[/bold cyan]")
        try:
            page.goto(job_url, timeout=35000, wait_until="domcontentloaded")
            BrowserManager.human_delay(2.5, 4.0)

            # Step 1: If on a landing page, locate and click the 'Apply' / 'Apply Now' CTA button
            cls._click_apply_cta_if_present(page)

            # Step 2: Handle multi-page application wizard
            max_pages = 6
            page_index = 0
            submitted = False

            while page_index < max_pages:
                page_index += 1
                BrowserManager.human_delay(1.5, 2.5)

                # A. Upload Resume
                cls._upload_resume(page)

                # B. Fill text, numbers, email, phone, links
                cls._fill_inputs(page)

                # C. Handle dropdowns / selects
                cls._fill_selects(page)

                # D. Handle radio groups and consent checkboxes
                cls._fill_radios_and_checkboxes(page)

                # E. Check for Submit button
                submit_selectors = [
                    "button:has-text('Submit Application')",
                    "button:has-text('Submit application')",
                    "button:has-text('Submit')",
                    "button:has-text('Send Application')",
                    "button[type='submit']",
                    "input[type='submit']",
                    "button:has-text('Complete Application')",
                ]
                submit_btn = None
                for sel in submit_selectors:
                    cand = page.locator(sel).first
                    if cand.is_visible(timeout=1000):
                        # Ensure it's not a generic search submit
                        t = cand.inner_text().strip().lower()
                        if any(w in t for w in ["submit", "apply", "send"]):
                            submit_btn = cand
                            break

                # F. Check for Next / Continue button if not on final submit
                next_selectors = [
                    "button:has-text('Save & Continue')",
                    "button:has-text('Save and Continue')",
                    "button:has-text('Next Step')",
                    "button:has-text('Next')",
                    "button:has-text('Continue')",
                    "button[aria-label*='Continue' i]",
                ]
                next_btn = None
                if not submit_btn:
                    for n_sel in next_selectors:
                        cand_n = page.locator(n_sel).first
                        if cand_n.is_visible(timeout=1000):
                            next_btn = cand_n
                            break

                if submit_btn and not next_btn:
                    log.info(f"[green]Final application step reached. Clicking Submit Application for '{company}'...[/green]")
                    BrowserManager.safe_click(submit_btn)
                    BrowserManager.human_delay(4.0, 6.0)
                    submitted = True
                    break

                if next_btn:
                    log.info(f"Advancing to next wizard step (Step {page_index})...")
                    BrowserManager.safe_click(next_btn)
                    continue

                # If neither submit nor next button found, might be a single page form with submit already attempted
                break

            # Step 3: Verify confirmation indicators
            confirmation_selectors = [
                "text='Application submitted'",
                "text='Thank you for applying'",
                "text='Your application was sent'",
                "text='Application received'",
                "text='Thanks for applying'",
                "div[class*='success' i]",
            ]
            confirmed = False
            for c_sel in confirmation_selectors:
                if page.locator(c_sel).first.is_visible(timeout=2500):
                    confirmed = True
                    break

            status = "APPLIED" if (submitted or confirmed) else "APPLIED_PENDING_CONFIRMATION"
            log.info(f"[bold green]✓ External application completed: {job_title} at {company} (Status: {status})[/bold green]")

            db.record_applied_job(
                platform="external",
                job_id=job_id or str(hash(job_url)),
                job_title=job_title,
                company=company,
                job_url=job_url,
                status=status,
                notes=f"Universal ATS Applier automated submission (confirmed={confirmed})"
            )
            return status

        except Exception as e:
            log.error(f"[red]Error during external ATS apply for '{job_title}' at '{company}': {e}[/red]")
            db.record_applied_job(
                platform="external",
                job_id=job_id or str(hash(job_url)),
                job_title=job_title,
                company=company,
                job_url=job_url,
                status="FAILED",
                notes=str(e)[:250]
            )
            return "FAILED"

    @classmethod
    def _click_apply_cta_if_present(cls, page: Page):
        """Clicks landing page 'Apply' button to open the form if not already visible."""
        # If inputs already exist, no need to click CTA
        if page.locator("input[type='email'], input[name*='name' i]").first.is_visible(timeout=1000):
            return

        cta_selectors = [
            "a:has-text('Apply for this job')",
            "button:has-text('Apply for this job')",
            "a:has-text('Apply Now')",
            "button:has-text('Apply Now')",
            "a[href*='#apply']",
            "a:has-text('Apply')",
            "button:has-text('Apply')",
        ]
        for sel in cta_selectors:
            cand = page.locator(sel).first
            if cand.is_visible(timeout=1200):
                log.info(f"Clicking landing CTA: {cand.inner_text().strip()}")
                BrowserManager.safe_click(cand)
                BrowserManager.human_delay(2.0, 3.5)
                break

    @classmethod
    def _upload_resume(cls, page: Page):
        """Attaches the candidate's PDF resume to any file upload inputs."""
        resume_file = Path(settings.profile.resume_path)
        if not resume_file.exists():
            return

        file_inputs = page.locator("input[type='file']").all()
        for f_inp in file_inputs:
            try:
                # Check if file is already uploaded
                f_inp.set_input_files(str(resume_file))
                log.info(f"[green]✓ Attached resume ({resume_file.name}) to external ATS application![/green]")
                BrowserManager.human_delay(1.5, 2.5)
            except Exception as e:
                log.debug(f"Resume upload element skip: {e}")

    @classmethod
    def _fill_inputs(cls, page: Page):
        """Fills out standard contact, personal, and screening input fields."""
        inputs = page.locator("input[type='text'], input[type='email'], input[type='tel'], input[type='number'], textarea").all()

        for inp in inputs:
            if not inp.is_visible():
                continue

            current_val = inp.input_value().strip()
            if current_val:
                continue

            # Identify field by label, placeholder, name, id, or aria-label
            identifier = cls._get_field_label(inp).lower()
            name_attr = (inp.get_attribute("name") or "").lower()
            id_attr = (inp.get_attribute("id") or "").lower()
            placeholder = (inp.get_attribute("placeholder") or "").lower()
            field_context = f"{identifier} {name_attr} {id_attr} {placeholder}".strip()

            # First Name
            if any(k in field_context for k in ["first name", "given name", "fname"]):
                inp.fill(settings.profile.first_name)
            # Last Name
            elif any(k in field_context for k in ["last name", "family name", "surname", "lname"]):
                inp.fill(settings.profile.last_name)
            # Full Name
            elif any(k in field_context for k in ["full name", "your name", "candidate name"]):
                inp.fill(f"{settings.profile.first_name} {settings.profile.last_name}")
            # Email
            elif any(k in field_context for k in ["email", "e-mail"]):
                inp.fill(settings.profile.email)
            # Phone
            elif any(k in field_context for k in ["phone", "mobile", "contact number", "telephone"]):
                inp.fill(settings.profile.phone)
            # LinkedIn
            elif "linkedin" in field_context:
                inp.fill(settings.profile.linkedin_url)
            # GitHub / Website / Portfolio
            elif any(k in field_context for k in ["github", "git", "portfolio", "website", "url"]):
                inp.fill(settings.profile.github_url)
            # Location / City / State / Country
            elif "city" in field_context:
                inp.fill(settings.profile.city)
            elif "state" in field_context:
                inp.fill(settings.profile.state)
            elif "country" in field_context:
                inp.fill(settings.profile.country)
            elif any(k in field_context for k in ["postal", "zip"]):
                inp.fill(settings.profile.postal_code)
            elif any(k in field_context for k in ["address", "current location", "residence"]):
                inp.fill(settings.profile.current_location)
            # Salary / CTC
            elif any(k in field_context for k in ["current salary", "current ctc"]):
                inp.fill(str(settings.profile.current_salary_lpa))
            elif any(k in field_context for k in ["expected salary", "expected ctc", "desired compensation", "salary expectation"]):
                inp.fill(str(settings.profile.expected_salary_lpa))
            # Notice Period
            elif any(k in field_context for k in ["notice period", "how soon can you start", "joining"]):
                inp.fill(str(settings.profile.notice_period_days))
            # Experience Years
            elif any(k in field_context for k in ["years of experience", "total experience", "how many years"]):
                inp.fill(str(settings.profile.years_of_experience))
            # Headline / Summary
            elif any(k in field_context for k in ["headline", "summary", "about you", "cover letter"]):
                inp.fill(settings.profile.summary)
            # Custom Question -> Call Gemini AI
            elif ai_assistant.is_active and len(identifier) > 5:
                ans = ai_assistant.answer_question(identifier, field_type="text")
                if ans:
                    inp.fill(ans)

    @classmethod
    def _fill_selects(cls, page: Page):
        """Handles dropdown selectors for countries, experience, or notice periods."""
        selects = page.locator("select").all()
        for sel in selects:
            if not sel.is_visible():
                continue

            lbl = cls._get_field_label(sel).lower()
            options = [o.inner_text().strip() for o in sel.locator("option").all() if o.inner_text().strip()]
            if not options:
                continue

            # Country dropdown
            if "country" in lbl or "nationality" in lbl:
                for opt in options:
                    if "india" in opt.lower():
                        try:
                            sel.select_option(label=opt)
                            break
                        except Exception:
                            pass
                continue

            # Notice Period
            if "notice" in lbl:
                for opt in options:
                    if any(w in opt.lower() for w in ["immediate", "15", "0"]):
                        try:
                            sel.select_option(label=opt)
                            break
                        except Exception:
                            pass
                continue

            # Gender
            if "gender" in lbl:
                for opt in options:
                    if opt.lower() == settings.profile.gender.lower():
                        try:
                            sel.select_option(label=opt)
                            break
                        except Exception:
                            pass
                continue

            # Use Gemini AI to choose the best matching option
            if ai_assistant.is_active and options:
                choice = ai_assistant.answer_question(lbl or "Select matching option", field_type="dropdown", options=options)
                try:
                    sel.select_option(label=choice)
                    continue
                except Exception:
                    pass

            # Fallback to second option (first option is often placeholder)
            if len(options) > 1:
                try:
                    sel.select_option(index=1)
                except Exception:
                    pass

    @classmethod
    def _fill_radios_and_checkboxes(cls, page: Page):
        """Handles checkboxes (consent/terms) and radio button groups."""
        # Checkboxes: Consent, Terms, Privacy Policy
        checkboxes = page.locator("input[type='checkbox']").all()
        for cb in checkboxes:
            if not cb.is_visible():
                continue
            lbl = cls._get_field_label(cb).lower()
            if any(w in lbl for w in ["agree", "consent", "terms", "privacy", "authorize", "acknowledge"]):
                try:
                    if not cb.is_checked():
                        cb.check()
                except Exception:
                    pass

        # Radio button fieldsets
        fieldsets = page.locator("fieldset").all()
        for fs in fieldsets:
            if not fs.is_visible():
                continue
            fs_text = fs.inner_text().lower()
            legend = fs.locator("legend").first
            prompt_text = legend.inner_text().strip() if legend.is_visible() else fs_text.split("\n")[0]

            # Authorization to work
            if any(w in fs_text for w in ["authorized", "legally permitted", "right to work"]):
                cls._select_radio_choice(fs, "yes" if settings.profile.authorized_to_work else "no")
            # Visa Sponsorship
            elif any(w in fs_text for w in ["sponsorship", "visa"]):
                cls._select_radio_choice(fs, "yes" if settings.profile.require_visa_sponsorship else "no")
            # Willing to relocate / commute / remote
            elif any(w in fs_text for w in ["relocate", "commute", "travel", "comfortable"]):
                cls._select_radio_choice(fs, "yes")
            # Gemini AI selection for complex radio queries
            elif ai_assistant.is_active:
                options = [lbl.inner_text().strip() for lbl in fs.locator("label").all() if lbl.is_visible()]
                if options:
                    choice = ai_assistant.answer_question(prompt_text, field_type="radio", options=options)
                    cls._select_radio_choice(fs, choice)

    @classmethod
    def _select_radio_choice(cls, container: Locator, target_text: str):
        """Clicks the matching radio button label or input."""
        try:
            target_lbl = container.locator(f"label:has-text('{target_text}'), input[value*='{target_text}' i]").first
            if target_lbl.is_visible():
                target_lbl.click()
        except Exception:
            pass

    @classmethod
    def _get_field_label(cls, element: Locator) -> str:
        """Finds the text label associated with an input or select element."""
        try:
            elem_id = element.get_attribute("id")
            if elem_id:
                lbl = element.page.locator(f"label[for='{elem_id}']").first
                if lbl.is_visible():
                    return lbl.inner_text().strip()

            aria_label = element.get_attribute("aria-label")
            if aria_label:
                return aria_label.strip()

            placeholder = element.get_attribute("placeholder")
            if placeholder:
                return placeholder.strip()

            parent = element.locator("xpath=..").first
            if parent.is_visible():
                return parent.inner_text().strip()
        except Exception:
            pass
        return ""
