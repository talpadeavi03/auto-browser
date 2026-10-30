#!/usr/bin/env python3
"""Job-fit score 0-100 before applying. Below targeting.min_score -> don't apply."""
import re, yaml
from build_dataset import norm

def score_job(title, description="", location="", profile=None):
    p = profile or yaml.safe_load(open("profile.yaml", encoding="utf-8"))
    tg, t, d, loc = p["targeting"], norm(title), norm(description), norm(location)
    reasons, s = [], 0
    if any(norm(x) in t for x in tg["title_exclude"]): return 0, ["excluded title"]
    if any(norm(x) in t for x in tg["title_include"]): s += 40; reasons.append("title match")
    else: return 10, ["title not in target list"]
    if not loc or any(norm(x) in loc for x in tg["locations"]) or "remote" in (loc + t): s += 20; reasons.append("location ok")
    else: reasons.append("location not preferred")
    yrs = [int(m) for m in re.findall(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:years|yrs)", description.lower())]
    if yrs:
        need = min(yrs)
        if need <= p["total_experience_years"] + 1.6: s += 20; reasons.append(f"needs {need}y ok")
        else: s -= 30; reasons.append(f"needs {need}y too high")
    else: s += 10
    names = [norm(k) for k in p["skills"]]
    hit = [n for n in names if f" {n} " in f" {d} "]
    s += min(20, 4 * len(hit)); reasons.append(f"{len(hit)} skills in JD")
    return max(0, min(100, s)), reasons

def should_apply(title, description="", location="", profile=None):
    p = profile or yaml.safe_load(open("profile.yaml", encoding="utf-8"))
    sc, why = score_job(title, description, location, p)
    return sc >= p["targeting"]["min_score"], sc, why

if __name__ == "__main__":
    print(should_apply("DevOps Engineer", "5 years experience AWS Terraform Kubernetes Docker CI/CD", "Pune"))
    print(should_apply("Java Developer", "Spring Boot", "Pune"))
    print(should_apply("Senior SRE", "10+ years Kubernetes", "Bengaluru"))
