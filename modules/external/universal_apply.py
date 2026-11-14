import time
import base64
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
    Greenhouse, Lever, Workday, Keka, BambooHR, SmartRecruiters, Ashby, PyjamaHR,
    and custom corporate career portals.
    """

    @classmethod
    def apply(cls, page: Page, job_url: str, job_title: str, company: str, job_id: str = "", match_score: float = 0.0) -> str:
        """
        Navigates to an external job application page, fills all fields,
        attaches candidate resume, answers screening questions with AI/MCP heuristics, and submits.
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

            # Step 2: Handle multi-page or single-page application wizard
            max_pages = 6
            page_index = 0
            submitted = False

            while page_index < max_pages:
                page_index += 1
                BrowserManager.human_delay(1.5, 2.5)

                # Collect page and any embedded ATS frames (e.g., Greenhouse, Lever, Workday embed)
                contexts = [page]
                for f in page.frames:
                    if f != page.main_frame and not f.is_detached:
                        f_url = f.url.lower()
                        if any(k in f_url for k in ["greenhouse", "lever", "workday", "bamboohr", "smartrecruiters", "jobvite", "ashby", "apply"]):
                            contexts.append(f)

                for ctx in contexts:
                    try:
                        # A. Upload Resume
                        cls._upload_resume(ctx)

                        # B. Fill text, numbers, email, phone, links, education, experience
                        cls._fill_inputs(ctx)

                        # C. Handle dropdowns / selects
                        cls._fill_selects(ctx)

                        # D. Handle radio groups and consent checkboxes
                        cls._fill_radios_and_checkboxes(ctx)
                    except Exception as ctx_err:
                        log.debug(f"Context processing note: {ctx_err}")

                # E. Solve image/text Captcha if present
                cls._solve_captcha_if_present(page)

                # F. Check for Submit button across contexts
                submit_selectors = [
                    "button[type='submit']",
                    "input[type='submit']",
                    "button:has-text('Submit Application')",
                    "button:has-text('Submit application')",
                    "button:has-text('Submit')",
                    "button:has-text('Send Application')",
                    "button:has-text('Apply Now')",
                    "button:has-text('Apply now')",
                    "button:has-text('Review and Submit')",
                    "button:has-text('Complete Application')",
                    "button[aria-label*='Submit' i]",
                    "button[data-automation-id='bottom-navigation-submit-button']",
                    "button[data-qa*='submit']",
                    "a:has-text('Submit')",
                    "button:has-text('Apply')",
                ]
                submit_btn = None
                for ctx in contexts:
                    for sel in submit_selectors:
                        try:
                            cand = ctx.locator(sel).first
                            if cand.is_visible(timeout=800):
                                t = cand.inner_text().strip().lower()
                                if any(w in t for w in ["submit", "send", "complete", "apply now"]):
                                    submit_btn = cand
                                    break
                                elif t == "apply":
                                    submit_btn = cand
                                    break
                        except Exception:
                            pass
                    if submit_btn:
                        break

                # G. Check for Next / Continue button if not on final submit
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
                    for ctx in contexts:
                        for n_sel in next_selectors:
                            try:
                                cand_n = ctx.locator(n_sel).first
                                if cand_n.is_visible(timeout=800):
                                    next_btn = cand_n
                                    break
                            except Exception:
                                pass
                        if next_btn:
                            break

                if submit_btn:
                    log.info(f"[green]Final application step reached. Clicking Submit Application for '{company}'...[/green]")
                    
                    # Take snapshot before submission
                    try:
                        proof_path = Path("data/exports/proof_external_applied.png")
                        proof_path.parent.mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(proof_path), full_page=False)
                    except Exception:
                        pass

                    BrowserManager.safe_click(submit_btn)
                    BrowserManager.human_delay(4.0, 6.0)
                    submitted = True
                    break

                if next_btn:
                    log.info(f"Advancing to next wizard step (Step {page_index})...")
                    BrowserManager.safe_click(next_btn)
                    continue

                break

            # Step 3: Verify confirmation indicators
            confirmation_selectors = [
                "text='Application submitted'",
                "text='Thank you for applying'",
                "text='Your application was sent'",
                "text='Application received'",
                "text='Thanks for applying'",
                "text='Successfully applied'",
                "text='We received your application'",
                "text='Application submitted successfully'",
                "text='Thank you for your interest'",
                "text='Your application has been received'",
                "text='Application Complete'",
                "text='Application successfully submitted'",
                ".application-submitted",
                ".submission-success",
                "[data-qa='application-success']",
                "div[class*='success' i]",
            ]
            confirmed = False
            for c_sel in confirmation_selectors:
                try:
                    if page.locator(c_sel).first.is_visible(timeout=2500):
                        confirmed = True
                        break
                except Exception:
                    pass

            current_url = page.url.lower()
            url_confirmed = any(k in current_url for k in ["/success", "/thank", "/confirm", "/applied", "/completed", "/submitted", "/done"])

            if confirmed or url_confirmed:
                status = "SUBMITTED"
                notes = f"Universal ATS Applier automated submission (confirmed={confirmed or url_confirmed})"
                log.info(f"[bold green]✓ External application verified & submitted: {job_title} at {company}[/bold green]")
            elif submitted:
                status = "FAILED_UNCONFIRMED"
                notes = "Submit button was clicked but ATS portal did not return a confirmation screen or success URL"
                log.warning(f"⚠️ External application unconfirmed: {job_title} at {company} (Status: {status})")
            else:
                status = "FAILED"
                notes = "Could not locate final submit button or complete external ATS form"
                log.warning(f"❌ External application failed: {job_title} at {company} ({notes})")

            # Save post-submit screenshot proof
            try:
                proof_path = Path("data/exports/proof_external_applied.png")
                page.screenshot(path=str(proof_path), full_page=False)
            except Exception:
                pass

            db.record_applied_job(
                platform="external",
                job_id=job_id or str(hash(job_url)),
                job_title=job_title,
                company=company,
                job_url=job_url,
                status=status,
                notes=notes,
                match_score=match_score
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
    def _upload_resume(cls, context):
        """Attaches the candidate's PDF resume to any file upload inputs."""
        resume_candidates = [
            Path(settings.profile.resume_path),
            Path("data/resumes/AT_26_AI.pdf"),
            Path("data/resumes/resume.pdf"),
            Path("resume.pdf"),
        ]
        resume_file = next((p for p in resume_candidates if p.exists() and p.is_file()), None)
        if not resume_file:
            return

        file_inputs = context.locator("input[type='file']").all()
        for f_inp in file_inputs:
            try:
                f_inp.set_input_files(str(resume_file))
                log.info(f"[green]✓ Attached resume ({resume_file.name}) to external ATS application![/green]")
                BrowserManager.human_delay(1.5, 2.5)
            except Exception as e:
                log.debug(f"Resume upload element skip: {e}")

    @classmethod
    def _safe_fill(cls, inp: Locator, val: str, label: str = "", field_type: str = "text") -> bool:
        """Safely fills an input field with timeout protection and editability checks, and records interaction."""
        try:
            if not inp.is_visible(timeout=500):
                return False
            if inp.get_attribute("readonly") is not None or not inp.is_editable():
                return False
            inp.fill(str(val), timeout=2500)
            if label and len(label) > 2:
                db.record_interaction(
                    platform="external",
                    question=label,
                    answer=str(val),
                    field_type=field_type,
                    source="universal_ats_applier"
                )
            return True
        except Exception as e:
            log.debug(f"Could not fill element: {e}")
            return False

    @classmethod
    def _fill_inputs(cls, page: Page):
        """Fills out standard contact, personal, education, experience, and screening input fields."""
        inputs = page.locator("input[type='text'], input[type='email'], input[type='tel'], input[type='number'], textarea").all()

        for inp in inputs:
            if not inp.is_visible():
                continue

            # Skip readonly or non-editable elements immediately to prevent 30s timeout
            if inp.get_attribute("readonly") is not None or not inp.is_editable():
                continue

            current_val = ""
            try:
                current_val = inp.input_value().strip()
            except Exception:
                pass
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
                cls._safe_fill(inp, settings.profile.first_name)
            # Last Name
            elif any(k in field_context for k in ["last name", "family name", "surname", "lname"]):
                cls._safe_fill(inp, settings.profile.last_name)
            # Middle Name
            elif "middle" in field_context:
                cls._safe_fill(inp, "")
            # Full Name
            elif any(k in field_context for k in ["full name", "your name", "candidate name"]):
                cls._safe_fill(inp, f"{settings.profile.first_name} {settings.profile.last_name}")
            # Email
            elif any(k in field_context for k in ["email", "e-mail"]):
                cls._safe_fill(inp, settings.profile.email)
            # Phone / Mobile
            elif any(k in field_context for k in ["phone", "mobile", "contact number", "telephone"]):
                cls._safe_fill(inp, settings.profile.phone)
            # LinkedIn
            elif "linkedin" in field_context:
                cls._safe_fill(inp, settings.profile.linkedin_url)
            # GitHub / Website / Portfolio
            elif any(k in field_context for k in ["github", "git", "portfolio", "website"]):
                cls._safe_fill(inp, settings.profile.github_url)
            # City / State / Country / Postal
            elif "city" in field_context:
                cls._safe_fill(inp, settings.profile.city)
            elif "state" in field_context:
                cls._safe_fill(inp, settings.profile.state)
            elif "country" in field_context:
                cls._safe_fill(inp, settings.profile.country)
            elif any(k in field_context for k in ["postal", "zip"]):
                cls._safe_fill(inp, settings.profile.postal_code)
            elif any(k in field_context for k in ["address", "current location", "residence"]):
                cls._safe_fill(inp, settings.profile.current_location)
            # Salary / CTC
            elif any(k in field_context for k in ["current salary", "current ctc"]):
                # If numeric only field or standard text
                val = str(settings.profile.current_salary_lpa)
                if "annual" in field_context or "amount" in field_context:
                    # Provide in Lakhs format e.g. 450000 or 4.5
                    cls._safe_fill(inp, "450000" if "00" in placeholder else val)
                else:
                    cls._safe_fill(inp, val)
            elif any(k in field_context for k in ["expected salary", "expected ctc", "desired compensation", "salary expectation"]):
                val = str(settings.profile.expected_salary_lpa)
                if "annual" in field_context or "amount" in field_context:
                    cls._safe_fill(inp, "850000" if "00" in placeholder else val)
                else:
                    cls._safe_fill(inp, val)
            # Notice Period / Availability (must NOT match date of joining)
            elif any(k in field_context for k in ["notice period", "availability", "available to join", "days to join", "how soon can you start"]):
                if "date" in field_context or "dob" in field_context:
                    continue
                val = str(settings.profile.notice_period_days)
                if "day" in field_context or "availability" in field_context:
                    if "immediate" in val.lower():
                        cls._safe_fill(inp, "0")
                    else:
                        digits = "".join(filter(str.isdigit, val))
                        cls._safe_fill(inp, digits or "0")
                else:
                    cls._safe_fill(inp, val)
            # Total Experience Years
            elif any(k in field_context for k in ["years of experience", "total experience", "how many years", "workexperience.years"]):
                cls._safe_fill(inp, str(settings.profile.years_of_experience))
            # Relevant Experience
            elif any(k in field_context for k in ["relevant exp", "devops exp", "cloud exp"]):
                cls._safe_fill(inp, str(settings.profile.years_of_experience))
            # Education Details
            elif any(k in field_context for k in ["degree", "course", "qualification"]):
                cls._safe_fill(inp, getattr(settings.profile, "degree", "Bachelor of Engineering"))
            elif any(k in field_context for k in ["branch", "specialization", "major", "field of study"]):
                cls._safe_fill(inp, getattr(settings.profile, "branch", "Information Technology"))
            elif any(k in field_context for k in ["university", "college", "institute", "school"]):
                cls._safe_fill(inp, getattr(settings.profile, "university", "Savitribai Phule Pune University"))
            # Experience / Company Details
            elif any(k in field_context for k in ["company name", "current company", "employer", "organization"]):
                cls._safe_fill(inp, getattr(settings.profile, "current_company", "Cloud Solutions Inc."))
            elif any(k in field_context for k in ["designation", "job title", "role title"]):
                cls._safe_fill(inp, getattr(settings.profile, "current_designation", "DevOps Engineer"))
            # Skills
            elif any(k in field_context for k in ["skill", "skills"]):
                cls._safe_fill(inp, getattr(settings.profile, "skills", "AWS, Kubernetes, Terraform, Docker, CI/CD, Python"))
            # Certifications
            elif any(k in field_context for k in ["certification", "certifications", "which aws"]):
                cls._safe_fill(inp, getattr(settings.profile, "certifications", "AWS Certified Solutions Architect - Associate"))
            # Migration tools & servers migrated
            elif any(k in field_context for k in ["tools have you used for migration", "migration tools"]):
                cls._safe_fill(inp, "AWS DMS, AWS MGN, Terraform, Ansible, Docker")
            elif any(k in field_context for k in ["how many server", "servers or database", "migrated"]):
                cls._safe_fill(inp, "25")
            # Headline / Summary
            elif any(k in field_context for k in ["headline", "summary", "about you", "cover letter"]):
                cls._safe_fill(inp, settings.profile.summary)
            # Custom Question -> Call Gemini AI Assistant
            elif ai_assistant.is_active and len(identifier) > 5:
                ans = ai_assistant.answer_question(identifier, field_type="text")
                if ans:
                    cls._safe_fill(inp, ans)

    @classmethod
    def _fill_selects(cls, page: Page):
        """Handles dropdown selectors for countries, experience, or notice periods."""
        selects = page.locator("select").all()
        for sel in selects:
            if not sel.is_visible():
                continue

            lbl = cls._get_field_label(sel).lower()
            name_attr = (sel.get_attribute("name") or "").lower()
            sel_context = f"{lbl} {name_attr}".strip()

            options = [o.inner_text().strip() for o in sel.locator("option").all() if o.inner_text().strip()]
            if not options:
                continue

            # Country dropdown
            if "country" in sel_context or "nationality" in sel_context:
                for opt in options:
                    if "india" in opt.lower() or "+91" in opt:
                        try:
                            sel.select_option(label=opt)
                            break
                        except Exception:
                            pass
                continue

            # Currency
            if "currency" in sel_context:
                for opt in options:
                    if "inr" in opt.lower() or "rs" in opt.lower() or "₹" in opt:
                        try:
                            sel.select_option(label=opt)
                            break
                        except Exception:
                            pass
                continue

            # Salary Period
            if "period" in sel_context:
                for opt in options:
                    if "annual" in opt.lower() or "year" in opt.lower():
                        try:
                            sel.select_option(label=opt)
                            break
                        except Exception:
                            pass
                continue

            # Preferred Location
            if "location" in sel_context:
                for opt in options:
                    if "pune" in opt.lower() or "any" in opt.lower() or "remote" in opt.lower():
                        try:
                            sel.select_option(label=opt)
                            break
                        except Exception:
                            pass
                continue

            # Notice Period
            if "notice" in sel_context:
                for opt in options:
                    if any(w in opt.lower() for w in ["immediate", "15", "0"]):
                        try:
                            sel.select_option(label=opt)
                            break
                        except Exception:
                            pass
                continue

            # Gender
            if "gender" in sel_context:
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
        """Handles checkboxes (consent/terms, currently working, Yes/No options) and radio button groups."""
        # 1. Checkboxes
        checkboxes = page.locator("input[type='checkbox']").all()
        for cb in checkboxes:
            if not cb.is_visible():
                continue
            lbl = cls._get_field_label(cb).lower()
            name_attr = (cb.get_attribute("name") or "").lower()
            id_attr = (cb.get_attribute("id") or "").lower()
            parent_text = ""
            try:
                parent_text = cb.locator("xpath=../..").inner_text().lower()
            except Exception:
                pass
            cb_context = f"{lbl} {name_attr} {id_attr} {parent_text}".strip()

            # "Currently working here" checkbox
            if any(w in cb_context for w in ["iscurrentlyworking", "currently working", "current job"]):
                try:
                    if not cb.is_checked():
                        cb.check()
                except Exception:
                    pass
                continue

            # Consent / Terms / Privacy
            if any(w in cb_context for w in ["agree", "consent", "terms", "privacy", "authorize", "acknowledge", "candidateconsent"]):
                try:
                    if not cb.is_checked():
                        cb.check()
                except Exception:
                    pass
                continue

            # Yes/No screening checkbox options (Option 0 or "Yes")
            if "option 0" in name_attr or parent_text == "yes" or lbl == "yes":
                try:
                    if not cb.is_checked():
                        cb.check()
                except Exception:
                    pass
                continue

        # 2. Radio button fieldsets
        fieldsets = page.locator("fieldset").all()
        for fs in fieldsets:
            if not fs.is_visible():
                continue
            fs_text = fs.inner_text().lower()
            legend = fs.locator("legend").first
            prompt_text = legend.inner_text().strip() if legend.is_visible() else fs_text.split("\n")[0]

            # Resume selection / attachment radio group
            if any(w in fs_text for w in ["resume", "curriculum vitae", "attach cv", "upload resume", "cv"]):
                first_opt = fs.locator("input[type='radio'], label, [role='radio']").first
                if first_opt.is_visible():
                    try:
                        first_opt.click()
                    except Exception:
                        pass
                continue

            # Authorization to work
            if any(w in fs_text for w in ["authorized", "legally permitted", "right to work"]):
                cls._select_radio_choice(fs, "yes" if settings.profile.authorized_to_work else "no")
            # Visa Sponsorship
            elif any(w in fs_text for w in ["sponsorship", "visa"]):
                cls._select_radio_choice(fs, "yes" if settings.profile.require_visa_sponsorship else "no")
            # Willing to relocate / commute / remote / Pune location
            elif any(w in fs_text for w in ["relocate", "commute", "travel", "comfortable", "pune", "fine working"]):
                cls._select_radio_choice(fs, "yes")
            # Migration experience
            elif "migration" in fs_text:
                cls._select_radio_choice(fs, "yes")
            # Gemini AI selection for complex radio queries
            elif ai_assistant.is_active:
                # Sanitize prompt text: ignore file extensions or empty legends
                clean_prompt = prompt_text.strip()
                if len(clean_prompt) < 4 or clean_prompt.lower() in ["pdf", "doc", "docx", "file", "upload", "attachment", "yes", "no"]:
                    continue

                options = [lbl.inner_text().strip() for lbl in fs.locator("label, [role='radio']").all() if lbl.is_visible() and len(lbl.inner_text().strip()) >= 2]
                if options:
                    choice = ai_assistant.answer_question(clean_prompt, field_type="radio", options=options)
                    if choice:
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
    def _solve_captcha_if_present(cls, page: Page):
        """Solves alphanumeric image captchas using Gemini Vision or canvas inspection."""
        captcha_inp = page.locator("input#captcha, input[name*='captcha' i], input[placeholder*='captcha' i]").first
        if not captcha_inp.is_visible(timeout=1000):
            return

        current_val = captcha_inp.input_value().strip()
        if current_val:
            return

        log.info("[cyan]Detected Captcha input field. Extracting captcha image...[/cyan]")
        try:
            # Extract image base64 via canvas
            src = page.evaluate("""() => {
                const img = document.querySelector('#imgCaptcha, img[src*="captcha" i], img[alt*="captcha" i]');
                if (!img) return '';
                const canvas = document.createElement('canvas');
                canvas.width = img.naturalWidth || img.width;
                canvas.height = img.naturalHeight || img.height;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0);
                return canvas.toDataURL('image/png');
            }""")

            if src and "base64," in src:
                # Solve using Gemini AI Vision
                if ai_assistant.is_active:
                    solution = ai_assistant.solve_captcha_image(src)
                    if solution:
                        cls._safe_fill(captcha_inp, solution)
                        log.info(f"[green]✓ Captcha solved with Gemini Vision: {solution}[/green]")
                        return
        except Exception as e:
            log.debug(f"Captcha extraction failed: {e}")

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
