import os
import json
from pathlib import Path
from typing import List, Optional
from config.config import settings
from core.logger import log

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

class AIAssistant:
    """
    Intelligent AI Form Assistant.
    Supports:
    1. Fine-Tuned Domain Model (Hugging Face Inference API / Local LoRA / Ollama)
    2. Google Gemini (gemini-2.5-flash)
    3. Fast Deterministic Heuristics
    Automatically saves screening interactions to jobs.db for continuous training.
    """
    def __init__(self, api_key: Optional[str] = None):
        raw_key = api_key or os.getenv("GEMINI_API_KEY")
        if raw_key and ("your_gemini" in raw_key or "your_" in raw_key):
            raw_key = None
        self.api_key = raw_key
        self.client = None
        self._quota_exhausted = False

        # DeepSeek LLM Configuration (DeepSeek-V4.1-Flash-1017)
        self.deepseek_model = getattr(settings.models, "llm", "deepseek-ai/DeepSeek-V4.1-Flash-1017")
        self.deepseek_api_key = getattr(settings.models, "deepseek_api_key", None) or os.getenv("DEEPSEEK_API_KEY")
        self.deepseek_base_url = getattr(settings.models, "deepseek_base_url", "https://api.deepseek.com/v1")

        # Fine-Tuned Model Configuration (Trained on Colab)
        self.hf_model_id = os.getenv("HF_MODEL_ID")
        self.hf_token = os.getenv("HF_TOKEN")
        self.ollama_model = os.getenv("OLLAMA_MODEL")
        self.ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.local_model_path = os.getenv("LOCAL_MODEL_PATH", "data/trained_model")

        if self.deepseek_api_key:
            log.info(f"[bold green]✓ DeepSeek LLM active:[/bold green] {self.deepseek_model}")
        if self.hf_model_id:
            log.info(f"[bold green]✓ Fine-Tuned Cloud Model configured:[/bold green] {self.hf_model_id}")
        elif Path(self.local_model_path).exists():
            log.info(f"[bold green]✓ Local Fine-Tuned Model found at:[/bold green] {self.local_model_path}")
        elif self.ollama_model:
            log.info(f"[bold green]✓ Ollama Model configured:[/bold green] {self.ollama_model}")

        if self.api_key and GENAI_AVAILABLE:
            try:
                self.client = genai.Client(api_key=self.api_key)
                log.info("[bold green]✓ Gemini AI Assistant initialized for smart form answering![/bold green]")
            except Exception as e:
                log.warning(f"Could not initialize Gemini Client: {e}")

    @property
    def has_deepseek(self) -> bool:
        """Returns True if DeepSeek API key or HF routing is configured."""
        return bool(self.deepseek_api_key)

    @property
    def has_fine_tuned_model(self) -> bool:
        """Returns True if a fine-tuned model (HF, Ollama, or Local) is configured."""
        return bool(self.hf_model_id or self.ollama_model or Path(self.local_model_path).exists())

    @property
    def is_active(self) -> bool:
        return self.client is not None and not self._quota_exhausted

    def _query_deepseek(
        self,
        question: str,
        field_type: str = "text",
        options: Optional[List[str]] = None,
        job_context: str = ""
    ) -> Optional[str]:
        """Queries DeepSeek-V4.1-Flash for high-speed screening question reasoning."""
        if not REQUESTS_AVAILABLE or not self.deepseek_api_key:
            return None

        opts_str = f"\nAvailable options to pick from: {options}" if options else ""
        system_msg = (
            "You are an expert autonomous job application agent for candidate Avinash Talpade, "
            "a DevOps and Cloud Engineer with 3.6 years experience. "
            "Always be truthful to candidate profile. If asked for a number, return ONLY digits. "
            "If options are provided, select EXACT option text. Keep open answers concise (1-2 sentences)."
            f"\n{self.get_candidate_context()}"
        )
        user_msg = f"Recruiter Question: '{question}'\nField Type: {field_type}{opts_str}\nJob Context: {job_context[:300]}\nProvide ONLY the direct answer:"

        headers = {
            "Authorization": f"Bearer {self.deepseek_api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.deepseek_model,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg}
            ],
            "temperature": 0.1,
            "max_tokens": 100
        }

        try:
            api_url = f"{self.deepseek_base_url.rstrip('/')}/chat/completions"
            resp = requests.post(api_url, headers=headers, json=payload, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", "").strip()
                    if content:
                        if (content.startswith('"') and content.endswith('"')) or (content.startswith("'") and content.endswith("'")):
                            content = content[1:-1].strip()
                        return content
        except Exception as e:
            log.debug(f"DeepSeek API call failed: {e}")

        return None

    def _query_fine_tuned_model(
        self,
        question: str,
        field_type: str = "text",
        options: Optional[List[str]] = None,
        job_context: str = ""
    ) -> Optional[str]:
        """Queries fine-tuned model via Hugging Face Serverless API or Ollama."""
        if not REQUESTS_AVAILABLE:
            return None

        opts_str = f"\nAvailable Options: {', '.join(options)}" if options else ""
        system_instruction = (
            "You are an expert AI autonomous job application agent for candidate Avinash Talpade, "
            "a DevOps and Cloud Engineer with 3.6 years experience. Answer recruiter screening questions "
            "accurately, professionally, and truthfully according to the candidate profile."
        )
        user_prompt = f"Recruiter Question: '{question}'\nField Type: {field_type}{opts_str}"

        # 1. Try Hugging Face Serverless Inference API (Free)
        if self.hf_model_id:
            try:
                headers = {}
                if self.hf_token:
                    headers["Authorization"] = f"Bearer {self.hf_token}"
                
                # Format into ChatML prompt used during fine-tuning
                formatted_prompt = (
                    f"<|im_start|>system\n{system_instruction}<|im_end|>\n"
                    f"<|im_start|>user\n{user_prompt}<|im_end|>\n"
                    f"<|im_start|>assistant\n"
                )
                
                api_url = f"https://api-inference.huggingface.co/models/{self.hf_model_id}"
                payload = {
                    "inputs": formatted_prompt,
                    "parameters": {
                        "max_new_tokens": 60,
                        "temperature": 0.1,
                        "return_full_text": False
                    }
                }
                res = requests.post(api_url, headers=headers, json=payload, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    if isinstance(data, list) and len(data) > 0:
                        gen_text = data[0].get("generated_text", "").strip()
                        if "<|im_end|>" in gen_text:
                            gen_text = gen_text.split("<|im_end|>")[0].strip()
                        if gen_text:
                            return gen_text
            except Exception as e:
                log.debug(f"HF Inference API call failed: {e}")

        # 2. Try Local Ollama
        if self.ollama_model:
            try:
                resp = requests.post(
                    f"{self.ollama_host}/api/generate",
                    json={
                        "model": self.ollama_model,
                        "system": system_instruction,
                        "prompt": user_prompt,
                        "stream": False,
                        "options": {"temperature": 0.1, "num_predict": 60}
                    },
                    timeout=10
                )
                if resp.status_code == 200:
                    ans = resp.json().get("response", "").strip()
                    if ans:
                        return ans
            except Exception as e:
                log.debug(f"Ollama call failed: {e}")

        return None

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
- Notice Period: 0 days (Immediate joiner (0 days) / Immediate)
- Current Location: {settings.profile.current_location} (City: {settings.profile.city}, State: {settings.profile.state}, Country: {settings.profile.country})
- Current Salary: 4.5 LPA (₹4,50,000 INR per year)
- Expected Salary: 7.5 LPA (₹7,50,000 INR per year)
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
        # Check for open-ended summary questions first
        if any(w in q for w in ["summarize", "describe", "overview", "explain", "detail"]):
            if "kubernetes" in q or "k8s" in q or "eks" in q:
                return "Experienced in architecting and managing production Kubernetes and AWS EKS clusters with Helm, ingress controllers, RBAC, and auto-scaling."
            if "ci/cd" in q or "pipeline" in q:
                return "Built automated CI/CD pipelines using GitHub Actions and GitLab CI for linting, security scanning, container builds, and zero-downtime deployment."
            if "terraform" in q or "iac" in q:
                return "Authored modular, reusable Terraform code for provisioning VPCs, EKS clusters, IAM roles, and RDS databases."
            if "cloud" in q or "aws" in q:
                return "Extensive experience designing, securing, and automating scalable cloud infrastructure on AWS using Terraform, Docker, and Kubernetes."
            return "Passionate DevOps Engineer with 3.6 years of hands-on experience in AWS, Kubernetes, Terraform, Docker, and CI/CD automation."

        if "availability" in q or "available to join" in q or "available" in q:
            return "Immediate"

        if "notice" in q or "how soon" in q or "joining" in q:
            if "day" in q or field_type == "number":
                return "0"
            return "Immediate joiner (0 days)"

        if "experience" in q or "years" in q or "duration" in q:
            try:
                exp_num = int(float(settings.profile.years_of_experience))
            except Exception:
                exp_num = 3
            return str(exp_num) if (field_type == "number" or "whole number" in q) else str(settings.profile.years_of_experience)

        if "current ctc" in q or "current salary" in q or "present ctc" in q:
            if any(k in q for k in ["rupee", "annual", "inr", "amount", "whole"]) or "00" in q or field_type == "number":
                return "450000"
            return str(settings.profile.current_salary_lpa)

        if "expected ctc" in q or "expected salary" in q or "desired compensation" in q or "salary expectation" in q:
            if any(k in q for k in ["rupee", "annual", "inr", "amount", "whole"]) or "00" in q or field_type == "number":
                return "750000"
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

        if "certif" in q or "license" in q:
            return settings.profile.certifications or "AWS Certified Solutions Architect - Associate"

        if "degree" in q or "qualification" in q or "education" in q:
            return settings.profile.degree or "Bachelor of Engineering"

        if "college" in q or "university" in q or "institute" in q:
            return settings.profile.college or settings.profile.university

        if "company" in q or "employer" in q:
            return settings.profile.current_company or "Cloud & DevOps Solutions"

        if "designation" in q or "title" in q or "role" in q:
            return settings.profile.current_designation or "DevOps Engineer"

        if "skill" in q:
            return settings.profile.skills

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
        Generates the optimal, truthful answer to a recruiter's screening question.
        Order of priority:
        1. Specialized Fine-Tuned Model (Hugging Face / Ollama / Local)
        2. Gemini 2.5 Flash API
        3. Deterministic Profile Heuristics
        Automatically logs question & answer into jobs.db for continuous learning.
        """
        final_answer = ""
        source = "heuristic"

        # 1. Try DeepSeek Flash LLM (deepseek-ai/DeepSeek-V4.1-Flash-1017)
        if self.has_deepseek:
            ds_ans = self._query_deepseek(question, field_type, options, job_context)
            if ds_ans:
                final_answer = ds_ans
                source = "deepseek"
                log.info(f"[cyan]⚡ DeepSeek-V4.1-Flash answered:[/cyan] '{question}' -> [bold green]'{final_answer}'[/bold green]")

        # 2. Try Fine-Tuned Model (Qwen-2.5-1.5B trained on Colab)
        if not final_answer and self.has_fine_tuned_model:
            ft_ans = self._query_fine_tuned_model(question, field_type, options, job_context)
            if ft_ans:
                final_answer = ft_ans
                source = "fine_tuned"
                log.info(f"[cyan]🎯 Fine-Tuned Model answered:[/cyan] '{question}' -> [bold green]'{final_answer}'[/bold green]")

        # 3. Try Google Gemini API
        if not final_answer and self.is_active:
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
                if (answer.startswith('"') and answer.endswith('"')) or (answer.startswith("'") and answer.endswith("'")):
                    answer = answer[1:-1].strip()

                if answer:
                    final_answer = answer
                    source = "gemini"
                    log.info(f"[cyan]🤖 Gemini AI answered:[/cyan] '{question}' -> [bold green]'{final_answer}'[/bold green]")
            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower():
                    log.warning("Gemini API Free-Tier daily quota exceeded (429). Activating instant local heuristic answering engine.")
                    self._quota_exhausted = True
                else:
                    log.warning(f"Gemini API call failed: {e}")

        # 3. Fallback to Heuristic Engine
        if not final_answer:
            final_answer = self._heuristic_answer(question, field_type, options)
            source = "heuristic"
            log.info(f"[cyan]⚡ Heuristic answered:[/cyan] '{question}' -> [bold green]'{final_answer}'[/bold green]")

        # 4. Record to Database for Autonomous Continuous Dataset Expansion
        try:
            from core.storage import db
            db.record_interaction(
                platform="screening",
                job_title="Screening Question",
                company="Recruiter",
                field_type=field_type,
                question=question,
                options=options,
                answer=final_answer,
                source=source,
                context=job_context
            )
        except Exception:
            pass

        return final_answer

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
