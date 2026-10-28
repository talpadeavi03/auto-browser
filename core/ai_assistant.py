import os
from typing import List, Optional
from config.config import settings
from core.logger import log

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

class AIAssistant:
    """
    Intelligent AI Form Assistant powered by Google Gemini.
    Answers non-standard screening questions on LinkedIn and Naukri
    accurately based on the candidate's actual profile and resume.
    """
    def __init__(self, api_key: Optional[str] = None):
        raw_key = api_key or os.getenv("GEMINI_API_KEY")
        if raw_key and ("your_gemini" in raw_key or "your_" in raw_key):
            raw_key = None
        self.api_key = raw_key
        self.client = None
        self._quota_exhausted = False
        if self.api_key and GENAI_AVAILABLE:
            try:
                self.client = genai.Client(api_key=self.api_key)
                log.info("[bold green]✓ Gemini AI Assistant initialized for smart form answering![/bold green]")
            except Exception as e:
                log.warning(f"Could not initialize Gemini Client: {e}")

    @property
    def is_active(self) -> bool:
        return self.client is not None and not self._quota_exhausted

    def get_candidate_context(self) -> str:
        """Constructs rich candidate background for prompt context."""
        return f"""
Candidate Background:
- Full Name: {settings.profile.first_name} {settings.profile.last_name}
- Email: {settings.profile.email}
- Phone: {settings.profile.phone}
- LinkedIn: {settings.profile.linkedin_url}
- GitHub: {settings.profile.github_url}
- Profession: Cloud & DevOps Engineer / Platform Engineer
- Headline: {settings.profile.headline}
- Degree: {settings.profile.degree}
- Primary Skills: AWS, Azure, GCP, Kubernetes, Docker, Terraform, CI/CD (GitHub Actions, GitLab CI, Jenkins), Linux Administration, Python, Helm, Ansible, DevSecOps, MLOps
- Total Experience: {settings.profile.years_of_experience} years
- Notice Period: {settings.profile.notice_period_days}{' days' if isinstance(settings.profile.notice_period_days, (int, float)) else ''} (Immediate / Quick joiner)
- Current Location: {settings.profile.current_location} (City: {settings.profile.city}, State: {settings.profile.state}, Country: {settings.profile.country})
- Current Salary: {settings.profile.current_salary_lpa} LPA
- Expected Salary: {settings.profile.expected_salary_lpa} LPA
- Visa / Sponsorship: Legally authorized to work, requires sponsorship = {settings.profile.require_visa_sponsorship}
- Comfortable working in: Pune, Bengaluru, Hybrid, or Remote
"""

    def _heuristic_answer(
        self,
        question: str,
        field_type: str = "text",
        options: Optional[List[str]] = None
    ) -> str:
        """
        Fast local deterministic answering heuristic when Gemini is inactive or rate-limited (429).
        Derives high-accuracy answers from the candidate profile.
        """
        q = (question or "").lower().strip()

        # Case 1: Dropdown or Radio options provided
        if options:
            clean_opts = [str(o).strip() for o in options if str(o).strip()]

            # Negative response required
            if any(k in q for k in ["sponsorship", "visa", "felony", "criminal", "misdemeanor", "convicted", "drug"]):
                for opt in clean_opts:
                    if opt.lower() in ["no", "none", "false", "never", "not required"]:
                        return opt

            # Affirmative response required
            if any(k in q for k in [
                "authorized", "eligible", "commute", "relocate", "hybrid", "remote", "shift",
                "comfortable", "willing", "agreement", "certif", "clearance", "background check"
            ]):
                for opt in clean_opts:
                    if opt.lower() in ["yes", "true", "i agree", "i am authorized"]:
                        return opt

            # Notice Period options
            if any(k in q for k in ["notice", "joining", "soon"]):
                for opt in clean_opts:
                    if any(w in opt.lower() for w in ["immediate", "0-15", "15", "1 month", "< 15", "less than"]):
                        return opt

            # Experience options
            if any(k in q for k in ["experience", "years"]):
                for opt in clean_opts:
                    if any(w in opt.lower() for w in ["3", "3-5", "2-4", "1-3"]):
                        return opt

            # Education options
            if any(k in q for k in ["education", "degree", "qualification"]):
                for opt in clean_opts:
                    if any(w in opt.lower() for w in ["bachelor", "engineering", "b.e", "b.tech", "graduate"]):
                        return opt

            # Gender
            if "gender" in q:
                for opt in clean_opts:
                    if "male" in opt.lower():
                        return opt

            # General affirmative fallback
            for opt in clean_opts:
                if opt.lower() in ["yes", "true"]:
                    return opt

            # Skip placeholders like "Select an option", "Choose..."
            valid = [o for o in clean_opts if not any(p in o.lower() for p in ["select", "choose", "please", "--"])]
            if valid:
                return valid[0]
            return clean_opts[0] if clean_opts else "Yes"

        # Case 2: Text or Number inputs
        if "notice" in q or "how soon" in q or "joining" in q:
            return "0" if ("day" in q or field_type == "number") else "Immediate Joiner"

        if "experience" in q or "years" in q or "duration" in q:
            try:
                exp_num = int(float(settings.profile.years_of_experience))
            except Exception:
                exp_num = 3
            return str(exp_num) if (field_type == "number" or "whole number" in q) else str(settings.profile.years_of_experience)

        if "current ctc" in q or "current salary" in q or "present ctc" in q:
            return str(settings.profile.current_salary_lpa)

        if "expected ctc" in q or "expected salary" in q:
            return str(settings.profile.expected_salary_lpa)

        if "sponsorship" in q or "visa" in q:
            return "Yes" if settings.profile.require_visa_sponsorship else "No"

        if "authorized" in q or "eligible" in q:
            return "Yes"

        if "github" in q:
            return settings.profile.github_url or "https://github.com/talpadeavi03"

        if "linkedin" in q:
            return settings.profile.linkedin_url or "https://www.linkedin.com/in/talpadeavi/"

        if "portfolio" in q or "website" in q:
            return settings.profile.github_url or "https://github.com/talpadeavi03"

        if "city" in q:
            return settings.profile.city or "Pune"

        if "state" in q:
            return settings.profile.state or "Maharashtra"

        if "pincode" in q or "postal" in q or "zip" in q:
            return settings.profile.postal_code or "411001"

        if "phone" in q or "mobile" in q:
            return settings.profile.phone or "8999285015"

        if "email" in q:
            return settings.profile.email or "talpadeavi0303@gmail.com"

        if "commute" in q or "relocate" in q or "shift" in q or "travel" in q or "comfortable" in q:
            return "Yes"

        if "felony" in q or "criminal" in q:
            return "No"

        if field_type == "radio":
            return "Yes"

        return "3" if field_type == "number" else "Yes"

    def answer_question(
        self,
        question: str,
        field_type: str = "text",
        options: Optional[List[str]] = None,
        job_context: str = ""
    ) -> str:
        """
        Uses Gemini to generate the optimal, truthful answer to a recruiter's screening question.
        Falls back to local heuristic answering on 429 quota exhaustion or API failure.
        """
        if not self.is_active:
            ans = self._heuristic_answer(question, field_type, options)
            log.info(f"[cyan]⚡ Heuristic answered:[/cyan] '{question}' -> [bold green]'{ans}'[/bold green]")
            return ans

        options_str = f"\nAvailable options to pick from: {options}" if options else ""
        system_instruction = (
            "You are an expert career agent assisting candidate Avinash Talpade in answering "
            "job application screening questions on LinkedIn and Naukri. "
            "Always be truthful to the candidate profile, confident, and professional. "
            "If the question asks for a number (years, days, salary), return ONLY the numeric value. "
            "If options are provided, return the EXACT text of the single best matching option. "
            "If open-ended text is required, write a concise, professional answer in 1-2 sentences."
        )

        prompt = f"""
{self.get_candidate_context()}

Recruiter Question: "{question}"
Field Type: {field_type}{options_str}
Optional Job Context: {job_context[:500]}

Provide ONLY the final answer to fill into the input box:
"""
        try:
            response = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.2,
                    max_output_tokens=150,
                )
            )
            answer = (response.text or "").strip()
            # Clean quotes if any
            if (answer.startswith('"') and answer.endswith('"')) or (answer.startswith("'") and answer.endswith("'")):
                answer = answer[1:-1].strip()

            log.info(f"[cyan]🤖 Gemini AI answered:[/cyan] '{question}' -> [bold green]'{answer}'[/bold green]")
            return answer
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower():
                log.warning("Gemini API Free-Tier daily quota exceeded (429 RESOURCE_EXHAUSTED). Activating instant local heuristic answering engine for remainder of session.")
                self._quota_exhausted = True
            else:
                log.warning(f"Gemini API call failed: {e}")

            ans = self._heuristic_answer(question, field_type, options)
            log.info(f"[cyan]⚡ Heuristic fallback answered:[/cyan] '{question}' -> [bold green]'{ans}'[/bold green]")
            return ans

    def solve_captcha_image(self, b64_png: str) -> str:
        """
        Uses Gemini Vision to read text from an image captcha.
        """
        if not self.is_active or not b64_png:
            return ""
        try:
            import base64
            if "," in b64_png:
                b64_png = b64_png.split(",")[1]
            img_bytes = base64.b64decode(b64_png)
            part = types.Part.from_bytes(data=img_bytes, mime_type="image/png")
            prompt = "Look at this image. What is the exact text or digits inside this captcha? Respond ONLY with the alphanumeric characters without spaces or punctuation."
            resp = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[part, prompt],
                config=types.GenerateContentConfig(temperature=0.0, max_output_tokens=20)
            )
            ans = (resp.text or "").strip()
            # Clean characters
            result = "".join(c for c in ans if c.isalnum())
            log.info(f"[cyan]🤖 Gemini AI solved image captcha:[/cyan] [bold green]'{result}'[/bold green]")
            return result
        except Exception as e:
            log.warning(f"Gemini captcha solver error: {e}")
            return ""

ai_assistant = AIAssistant()
