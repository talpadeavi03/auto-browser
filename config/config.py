import os
from pathlib import Path
from typing import List, Optional, Union
import yaml
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Base paths
ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT_DIR / "config" / "settings.yaml"
ENV_PATH = ROOT_DIR / ".env"

load_dotenv(ENV_PATH)

class BrowserConfig(BaseModel):
    engine: str = "brave" # "brave" or "chromium"
    brave_path: Optional[str] = None
    headless: bool = False
    slow_mo_ms: int = 60
    user_data_dir: str = "data/browser_profile"
    timeout_ms: int = 30000

class ProfileConfig(BaseModel):
    first_name: str = "Applicant"
    last_name: str = "User"
    email: str = "user@example.com"
    phone: str = "9876543210"
    current_location: str = "Bengaluru, India"
    city: str = "Pune"
    state: str = "Maharashtra"
    country: str = "India"
    postal_code: str = "411001"
    linkedin_url: str = "https://www.linkedin.com/in/talpadeavi/"
    github_url: str = "https://github.com/talpadeavi03"
    portfolio_url: str = ""
    headline: str = "DevOps & Cloud Engineer | AWS, Kubernetes, Terraform, CI/CD, MLOps"
    summary: str = "Experienced DevOps & Cloud Engineer with 3.6 years of expertise in automating, deploying, and maintaining cloud platforms."
    degree: str = "Bachelor of Engineering"
    branch: str = "Information Technology"
    university: str = "Savitribai Phule Pune University"
    college: str = "Pune Institute of Computer Technology"
    graduation_year: str = "2021"
    current_company: str = "Cloud & DevOps Solutions"
    current_designation: str = "DevOps Engineer"
    skills: str = "AWS, Kubernetes, Docker, Terraform, CI/CD, GitHub Actions, Linux, Python, Prometheus, Grafana, Ansible"
    certifications: str = "AWS Certified Solutions Architect - Associate"
    gender: str = "Male"
    veteran_status: str = "No"
    disability_status: str = "No"
    years_of_experience: Union[int, float] = 3
    current_salary_lpa: str = "12"
    expected_salary_lpa: str = "18"
    notice_period_days: Union[int, str] = 15
    require_visa_sponsorship: bool = False
    authorized_to_work: bool = True
    resume_path: str = "data/resumes/resume.pdf"

class LinkedInConfig(BaseModel):
    enabled: bool = True
    search_keywords: List[str] = ["Software Engineer"]
    locations: List[str] = ["India"]
    experience_levels: List[str] = ["Associate", "Mid-Senior level"]
    date_posted: str = "past_week"
    easy_apply_only: bool = True
    max_applications_per_run: int = 15
    skip_screening_questions_if_complex: bool = True

class NaukriProfileRefresh(BaseModel):
    enabled: bool = True
    interval_hours: int = 4
    tweak_headline_dot: bool = True

class NaukriConfig(BaseModel):
    enabled: bool = True
    profile_refresh: NaukriProfileRefresh = Field(default_factory=NaukriProfileRefresh)
    search_keywords: List[str] = ["Python Developer"]
    locations: List[str] = ["Bengaluru"]
    experience_years: Union[int, float] = 3
    max_applications_per_run: int = 15

class ReportingConfig(BaseModel):
    auto_export_csv: bool = True
    export_dir: str = "data/exports"

class AIModelsConfig(BaseModel):
    llm: str = "deepseek-ai/DeepSeek-V4.1-Flash-1017"
    embeddings: str = "BAAI/bge-m3"
    resume_embeddings: str = "TechWolf/JobBERT-v3"
    reranker: str = "BAAI/bge-reranker-v2-m3"
    min_match_score: float = 0.65
    deepseek_api_key: Optional[str] = None
    deepseek_base_url: str = "https://api.deepseek.com/v1"

class AppConfig(BaseModel):
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    profile: ProfileConfig = Field(default_factory=ProfileConfig)
    linkedin: LinkedInConfig = Field(default_factory=LinkedInConfig)
    naukri: NaukriConfig = Field(default_factory=NaukriConfig)
    reporting: ReportingConfig = Field(default_factory=ReportingConfig)
    models: AIModelsConfig = Field(default_factory=AIModelsConfig)

    @classmethod
    def load(cls) -> "AppConfig":
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        else:
            data = {}

        config = cls(**data)

        # Environment variable overrides
        env_headless = os.getenv("HEADLESS")
        if env_headless is not None:
            config.browser.headless = env_headless.lower() in ("1", "true", "yes")

        env_deepseek_key = os.getenv("DEEPSEEK_API_KEY")
        if env_deepseek_key:
            config.models.deepseek_api_key = env_deepseek_key

        # Resolve paths relative to ROOT_DIR
        config.browser.user_data_dir = str(ROOT_DIR / config.browser.user_data_dir)
        config.reporting.export_dir = str(ROOT_DIR / config.reporting.export_dir)
        if not Path(config.profile.resume_path).is_absolute():
            config.profile.resume_path = str(ROOT_DIR / config.profile.resume_path)

        return config

settings = AppConfig.load()
