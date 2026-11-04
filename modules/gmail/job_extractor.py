import re
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup
from core.logger import log

class JobExtractor:
    """
    Extracts structured job posting fields and application URLs from email HTML and text.
    Ported from AetherApply (data-scrap).
    """

    JOB_PLATFORM_PATTERNS = [
        re.compile(r"greenhouse\.io", re.IGNORECASE),
        re.compile(r"lever\.co", re.IGNORECASE),
        re.compile(r"myworkdayjobs\.com|workday\.com", re.IGNORECASE),
        re.compile(r"ashbyhq\.com", re.IGNORECASE),
        re.compile(r"smartrecruiters\.com", re.IGNORECASE),
        re.compile(r"bamboohr\.com", re.IGNORECASE),
        re.compile(r"keka\.com", re.IGNORECASE),
        re.compile(r"linkedin\.com/jobs", re.IGNORECASE),
        re.compile(r"indeed\.com", re.IGNORECASE),
        re.compile(r"naukri\.com", re.IGNORECASE),
        re.compile(r"glassdoor\.com|glassdoor\.co\.in", re.IGNORECASE),
        re.compile(r"jobot\.com", re.IGNORECASE),
        re.compile(r"foundit\.in|monsterindia\.com", re.IGNORECASE),
        re.compile(r"ambitionbox\.com", re.IGNORECASE),
        re.compile(r"wellfound\.com|angel\.co", re.IGNORECASE),
        re.compile(r"hirist\.tech|iimjobs\.com", re.IGNORECASE),
        re.compile(r"instahyre\.com", re.IGNORECASE),
    ]

    ROLE_PATTERNS = [
        re.compile(r"(senior\s+|lead\s+|principal\s+|staff\s+|junior\s+)?(devops|mlops|cloud|platform|site reliability|sre|software|infrastructure|data|ai|machine learning|azure|aws)\s+(engineer|architect|developer|specialist|analyst)", re.IGNORECASE),
        re.compile(r"(cloud infrastructure analyst|systems engineer|devsecops engineer)", re.IGNORECASE),
    ]

    COMPANY_PATTERNS = [
        re.compile(r"(?:at|with|for|join)\s+([A-Z][A-Za-z0-9&.\- ]{1,30}?)(?:\s+is|\s+are|\s+team|[,\.\n\-]|\s*$)", re.IGNORECASE),
        re.compile(r"(?:application to|applied to|job at|opportunity at)\s+([A-Z][A-Za-z0-9&.\- ]{1,30}?)(?:[,\.\n\-]|\s*$)", re.IGNORECASE),
    ]

    @classmethod
    def is_job_alert(cls, subject: str, sender: str, body: str) -> bool:
        """Filters out non-job notification emails (security alerts, receipts, OTPs)."""
        combined = f"{subject} {sender}".lower()

        # Negative exclusions
        exclude_keywords = [
            "security alert", "password reset", "verify your", "verification code",
            "one-time password", "otp", "statement", "invoice", "receipt", "billing",
            "digest", "newsletter", "shut down", "github actions", "run failed",
            "bank", "credit card", "payment", "welcome to", "sign-in attempt"
        ]
        if any(neg in combined for neg in exclude_keywords):
            return False

        # Positive indicators
        job_senders = [
            "linkedin", "indeed", "naukri", "glassdoor", "greenhouse", "lever",
            "workday", "ashby", "foundit", "shine", "wellfound", "hirist", "instahyre", "jobot"
        ]
        if any(src in combined for src in job_senders):
            return True

        job_keywords = [
            "job", "career", "hiring", "opportunity", "interview", "application",
            "position", "vacancy", "devops", "cloud", "engineer", "recruitment"
        ]
        return any(k in combined for k in job_keywords)

    @classmethod
    def clean_html(cls, html_content: str) -> str:
        """Strips scripts, CSS, and tracker pixels, returning clean markdown-like text."""
        if not html_content or not html_content.strip():
            return ""
        try:
            soup = BeautifulSoup(html_content, "lxml")
            for tag in soup(["script", "style", "meta", "noscript", "svg"]):
                tag.decompose()
            for img in soup.find_all("img"):
                w = img.get("width", "")
                h = img.get("height", "")
                if w == "1" or h == "1":
                    img.decompose()
            for block in soup.find_all(["p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "li"]):
                block.insert_before("\n")
            lines = [line.strip() for line in soup.get_text().splitlines()]
            return "\n".join([l for l in lines if l])
        except Exception:
            return html_content[:2000]

    @classmethod
    def find_apply_url(cls, html_content: str, text_content: str = "") -> Optional[str]:
        """Scans HTML anchors and plain text for verified job portal and ATS links."""
        if not html_content and not text_content:
            return None

        links = []
        if html_content:
            try:
                soup = BeautifulSoup(html_content, "lxml")
                for a in soup.find_all("a", href=True):
                    href = a["href"].strip()
                    text = a.get_text().strip()
                    if href.startswith("http"):
                        links.append({"url": href, "text": text})
            except Exception:
                pass

        if not links and text_content:
            raw_urls = re.findall(r"https?://[^\s<>\"']+", text_content)
            for u in raw_urls:
                links.append({"url": u, "text": ""})

        # Priority 1: Direct ATS or recognized job platform links
        for l in links:
            url = l["url"]
            for pat in cls.JOB_PLATFORM_PATTERNS:
                if pat.search(url):
                    # Filter out unsubscribe or preference links
                    if any(u in url.lower() for u in ["unsubscribe", "privacy", "notifications/settings", "help"]):
                        continue
                    return url

        # Priority 2: Buttons with explicit 'Apply' / 'View Job' anchor text
        apply_keywords = ["apply now", "easy apply", "apply", "view job", "view opportunity", "see job"]
        for l in links:
            text_lower = l["text"].lower()
            if any(k in text_lower for k in apply_keywords):
                url = l["url"]
                if not any(u in url.lower() for u in ["unsubscribe", "privacy", "notifications/settings"]):
                    return url

        return None

    @classmethod
    def extract(cls, email_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extracts structured job posting details from raw email data."""
        subject = email_data.get("subject", "")
        sender = email_data.get("sender", "")
        body_html = email_data.get("body_html", "")
        body_text = email_data.get("body_text", "")

        cleaned_body = cls.clean_html(body_html) if body_html else body_text
        apply_url = cls.find_apply_url(body_html, body_text)
        full_text = f"{subject}\n{cleaned_body}"

        # 1. Extract Role
        role = "Cloud / DevOps Engineer"
        for pat in cls.ROLE_PATTERNS:
            m = pat.search(subject) or pat.search(cleaned_body)
            if m:
                role = m.group(0).strip().title()
                break

        # 2. Extract Company
        company = "Featured Employer"
        for pat in cls.COMPANY_PATTERNS:
            m = pat.search(subject) or pat.search(cleaned_body[:600])
            if m:
                company = m.group(1).strip()
                break
        if company == "Featured Employer" and sender:
            # Try to grab company from sender display name (e.g., 'Infosys Careers <jobs@infosys.com>')
            s_match = re.match(r"^([^<@]+)", sender)
            if s_match:
                cand = s_match.group(1).strip().replace('"', '')
                if cand and len(cand) < 40 and not any(k in cand.lower() for k in ["no-reply", "notification", "alerts", "team"]):
                    company = cand

        # 3. Detect Platform
        platform = "gmail_alert"
        if apply_url:
            for pat in cls.JOB_PLATFORM_PATTERNS:
                if pat.search(apply_url):
                    platform = pat.pattern.split(".")[0].replace("\\", "").lower()
                    break

        return {
            "company": company,
            "role": role,
            "platform": platform,
            "apply_url": apply_url,
            "subject": subject,
            "sender": sender,
            "body_snippet": cleaned_body[:500] if cleaned_body else ""
        }
