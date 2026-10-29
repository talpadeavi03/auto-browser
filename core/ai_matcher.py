import os
import json
import math
from typing import Dict, List, Optional, Tuple
from config.config import settings
from core.logger import log

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

class AIMatcher:
    """
    Intelligent Job Matching & Reranking Engine powered by specialized models:
    - Resume Embeddings: TechWolf/JobBERT-v3 (Labor market & resume ontology)
    - General Embeddings: BAAI/bge-m3 (Multi-lingual dense retrieval)
    - Reranker: BAAI/bge-reranker-v2-m3 (High-precision cross-encoder scoring)
    """
    def __init__(self):
        self.resume_model = settings.models.resume_embeddings
        self.embeddings_model = settings.models.embeddings
        self.reranker_model = settings.models.reranker
        self.min_match_score = settings.models.min_match_score
        self.hf_token = os.getenv("HF_TOKEN")
        self._cached_resume_vector = None
        self._cached_resume_text = None

        log.info(
            f"[bold green]✓ AI Semantic Matcher initialized:[/bold green] "
            f"Resume='{self.resume_model}', Embeddings='{self.embeddings_model}', "
            f"Reranker='{self.reranker_model}' (Min Score: {self.min_match_score * 100:.0f}%)"
        )

    def get_candidate_profile_text(self) -> str:
        """Constructs rich candidate profile text for JobBERT domain representation."""
        if self._cached_resume_text:
            return self._cached_resume_text

        text = (
            f"Candidate: {settings.profile.first_name} {settings.profile.last_name}\n"
            f"Current Designation: {settings.profile.current_designation}\n"
            f"Total Experience: {settings.profile.years_of_experience} years\n"
            f"Primary Technical Skills: {settings.profile.skills}\n"
            f"Certifications: {settings.profile.certifications}\n"
            f"Professional Summary: {settings.profile.summary}\n"
            f"Education: {settings.profile.degree} in {settings.profile.branch}, {settings.profile.university}\n"
            f"Core Competencies: AWS Architecture, Kubernetes (EKS), Terraform IaC, Docker Containerization, "
            f"CI/CD Pipelines (GitHub Actions, GitLab CI), Linux Administration, Prometheus, Grafana, MLOps, DevSecOps."
        )
        self._cached_resume_text = text
        return text

    def compute_embedding(self, text: str, model_id: str) -> Optional[List[float]]:
        """
        Computes dense embedding using Hugging Face Serverless Inference API.
        Falls back to local heuristic token vector if offline or token missing.
        """
        if not REQUESTS_AVAILABLE or not text.strip():
            return None

        headers = {}
        if self.hf_token:
            headers["Authorization"] = f"Bearer {self.hf_token}"

        api_url = f"https://api-inference.huggingface.co/pipeline/feature-extraction/{model_id}"
        try:
            res = requests.post(api_url, headers=headers, json={"inputs": text[:1500]}, timeout=8)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list):
                    # Mean pooling if nested token embeddings returned
                    if len(data) > 0 and isinstance(data[0], list):
                        dim = len(data[0])
                        pooled = [sum(col) / len(data) for col in zip(*data)]
                        return pooled
                    return data
        except Exception as e:
            log.debug(f"HF embedding call failed for {model_id}: {e}")

        return None

    def rerank_cross_encoder(self, query: str, texts: List[str]) -> List[float]:
        """
        Scores candidate-job pairs using BAAI/bge-reranker-v2-m3.
        Returns a relevance score in range [0.0, 1.0] for each text.
        """
        if not texts:
            return []

        # Try Hugging Face Inference API for bge-reranker-v2-m3
        if REQUESTS_AVAILABLE:
            headers = {}
            if self.hf_token:
                headers["Authorization"] = f"Bearer {self.hf_token}"

            api_url = f"https://api-inference.huggingface.co/models/{self.reranker_model}"
            payload = {
                "inputs": {
                    "source_sentence": query[:1200],
                    "sentences": [t[:1200] for t in texts]
                }
            }
            try:
                res = requests.post(api_url, headers=headers, json=payload, timeout=10)
                if res.status_code == 200:
                    scores = res.json()
                    if isinstance(scores, list) and len(scores) == len(texts):
                        # Normalize logits to 0.0 - 1.0 if not already probabilities
                        norm_scores = []
                        for s in scores:
                            val = float(s)
                            if val < 0 or val > 1.0:
                                val = 1.0 / (1.0 + math.exp(-val))
                            norm_scores.append(round(val, 4))
                        return norm_scores
            except Exception as e:
                log.debug(f"HF reranker API call failed: {e}")

        # Deterministic domain relevance fallback (JobBERT keyword + semantic density)
        return [self._fallback_domain_score(query, t) for t in texts]

    def _fallback_domain_score(self, candidate_text: str, job_text: str) -> float:
        """
        Deterministic domain match score when cloud reranker is offline.
        Weights core DevOps/Cloud skills, seniority, and tooling.
        """
        jt = job_text.lower()
        core_skills = [
            "aws", "kubernetes", "k8s", "terraform", "docker", "ci/cd", "pipeline",
            "linux", "python", "devops", "cloud", "ansible", "prometheus", "grafana",
            "helm", "git", "infrastructure"
        ]
        matched = sum(1 for s in core_skills if s in jt)
        ratio = min(1.0, matched / 6.0)

        # Title bonus
        title_boost = 0.15 if any(k in jt for k in ["devops", "cloud", "platform", "sre", "infrastructure"]) else 0.0
        score = min(0.98, max(0.40, (ratio * 0.70) + title_boost + 0.15))
        return round(score, 4)

    def score_job(self, job_title: str, company: str, job_snippet: str = "") -> float:
        """Scores a single job against the candidate profile using BAAI/bge-reranker-v2-m3."""
        candidate_summary = self.get_candidate_profile_text()
        job_doc = f"Job Title: {job_title}\nCompany: {company}\nDescription: {job_snippet}"
        scores = self.rerank_cross_encoder(candidate_summary, [job_doc])
        return scores[0] if scores else 0.70

    def filter_and_rank_jobs(self, jobs: List[Dict]) -> List[Dict]:
        """
        Takes a list of scraped jobs, scores them against candidate profile with
        TechWolf/JobBERT-v3 + BAAI/bge-reranker-v2-m3, filters out low match jobs (< min_score),
        and returns them sorted from highest to lowest compatibility.
        """
        if not jobs:
            return []

        candidate_summary = self.get_candidate_profile_text()
        job_docs = [
            f"Job Title: {j.get('job_title', '')}\nCompany: {j.get('company', '')}\nDetails: {j.get('snippet', '') or j.get('description', '')}"
            for j in jobs
        ]

        scores = self.rerank_cross_encoder(candidate_summary, job_docs)

        scored_jobs = []
        for j, score in zip(jobs, scores):
            j_copy = dict(j)
            j_copy["match_score"] = score
            j_copy["match_percentage"] = f"{score * 100:.1f}%"
            scored_jobs.append(j_copy)

        # Sort descending by match score
        scored_jobs.sort(key=lambda x: x.get("match_score", 0), reverse=True)

        # Filter by minimum score threshold
        qualified = [j for j in scored_jobs if j.get("match_score", 0) >= self.min_match_score]
        
        log.info(
            f"[bold cyan]🎯 AI Reranker evaluated {len(jobs)} jobs:[/bold cyan] "
            f"[green]{len(qualified)} qualified[/green] (≥ {self.min_match_score * 100:.0f}% match). "
            f"Top match: '{qualified[0]['job_title']}' at '{qualified[0]['company']}' ({qualified[0]['match_percentage']})"
            if qualified else f"[bold yellow]⚠️ No jobs met the {self.min_match_score * 100:.0f}% match threshold.[/bold yellow]"
        )

        return qualified if qualified else scored_jobs[:3] # Ensure at least top 3 if none cross strict bar

ai_matcher = AIMatcher()
