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
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.client = None
        if self.api_key and GENAI_AVAILABLE:
            try:
                self.client = genai.Client(api_key=self.api_key)
                log.info("[bold green]✓ Gemini AI Assistant initialized for smart form answering![/bold green]")
            except Exception as e:
                log.warning(f"Could not initialize Gemini Client: {e}")

    @property
    def is_active(self) -> bool:
        return self.client is not None

    def get_candidate_context(self) -> str:
        """Constructs rich candidate background for prompt context."""
        return f"""
Candidate Background:
- Full Name: {settings.profile.first_name} {settings.profile.last_name}
- Profession: Cloud & DevOps Engineer / Platform Engineer
- Primary Skills: AWS, Azure, GCP, Kubernetes, Docker, Terraform, CI/CD (GitHub Actions, GitLab CI, Jenkins), Linux Administration, Python, Helm, Ansible, DevSecOps, MLOps
- Total Experience: {settings.profile.years_of_experience} years
- Notice Period: {settings.profile.notice_period_days} days (Immediate / Quick joiner)
- Current Location: {settings.profile.current_location}
- Current Salary: {settings.profile.current_salary_lpa} LPA
- Expected Salary: {settings.profile.expected_salary_lpa} LPA
- Visa / Sponsorship: Legally authorized to work, requires sponsorship = {settings.profile.require_visa_sponsorship}
- Comfortable working in: Pune, Bengaluru, Hybrid, or Remote
"""

    def answer_question(
        self,
        question: str,
        field_type: str = "text",
        options: Optional[List[str]] = None,
        job_context: str = ""
    ) -> str:
        """
        Uses Gemini to generate the optimal, truthful answer to a recruiter's screening question.
        """
        if not self.is_active:
            return ""

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
            log.warning(f"Gemini API call failed: {e}")
            return ""

ai_assistant = AIAssistant()
