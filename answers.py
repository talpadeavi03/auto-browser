#!/usr/bin/env python3
"""Confidence-gated answer resolver. Never guesses: unknown -> None -> application is skipped + queued.

Order: corrections/exact -> skill rules -> strict fuzzy -> optional model -> optional LLM (free text only).
"""
import re, sys, json, difflib, functools
import yaml
from build_dataset import norm, load, fill, key, parse_input, queue_for_review, pick_range, OUT, CORR

MIN_CONF = 0.90
STOP = set("a an the your you do are is of to for in on at please what which how many much have has any be can will would we our".split())
ALIASES = {"k8s": "kubernetes", "amazon web services": "aws", "github action": "github actions", "gitlab ci/cd": "gitlab ci",
           "azure devops": "azure devops", "cicd": "ci/cd", "ci cd": "ci/cd", "tf": "terraform", "amazon eks": "eks",
           "microsoft azure": "azure", "google cloud platform": "gcp", "google cloud": "gcp", "powershell scripting": "powershell",
           "shell scripting": "bash", "version control": "git", "prometheus and grafana": "prometheus"}

class SkipApplication(Exception): pass

class Answer:
    def __init__(self, value, conf, source): self.value, self.conf, self.source = str(value), conf, source
    def __repr__(self): return f"Answer({self.value!r}, {self.conf:.2f}, {self.source})"

@functools.lru_cache(maxsize=1)
def _profile(path="profile.yaml"): return yaml.safe_load(open(path, encoding="utf-8"))

@functools.lru_cache(maxsize=1)
def _dataset():
    rows = []
    for r in (load(CORR) if CORR.exists() else []) + load(OUT):
        q, t, o = parse_input(r["input"]); rows.append((norm(q), t, o, r["output"], key(q, t, o)))
    return rows

def reload(): _dataset.cache_clear(); _profile.cache_clear()

# ---------- option handling
def match_option(ans, options):
    if not options: return ans
    a = norm(ans)
    for o in options:
        if norm(o) == a: return o
    if a in ("yes", "no"):
        for o in options:
            if norm(o).split(" ")[0] == a: return o
    return None            # never invent a value outside the offered options

# ---------- skills
def _skill_table(p):
    t = {norm(k): float(v) for k, v in p["skills"].items()}
    t.update({norm(s): 0.0 for s in p.get("skills_none", [])})
    return t

def _find_skills(nq, table):
    names = {**{a: norm(b) for a, b in ALIASES.items() if norm(b) in table}, **{k: k for k in table}}
    found, text = set(), f" {nq} "
    for name in sorted(names, key=len, reverse=True):     # longest first so "azure devops" beats "azure"
        pat = f" {norm(name)} "
        if pat in text:
            found.add(names[name]); text = text.replace(pat, " # ")
    return found

def skill_rule(nq, ftype, options, p):
    if not re.search(r"\b(experience|years?|worked|hands on|proficien)\b", nq): return None
    table = _skill_table(p); found = _find_skills(nq, table)
    if len(found) != 1: return None                         # none/ambiguous -> don't guess
    yrs = table[next(iter(found))]
    if ftype == "number": return Answer(f"{yrs:g}", 1.0, "skill-rule")
    if ftype in ("radio", "dropdown", "select") and options:
        yn = match_option("Yes" if yrs > 0 else "No", options)
        if yn: return Answer(yn, 1.0, "skill-rule")
        r = pick_range(options, yrs)
        if r: return Answer(r, 1.0, "skill-rule")
    if ftype == "text": return Answer(f"{yrs:g}", 0.95, "skill-rule")
    return None


# ---------- deterministic profile-field intents (facts, not guesses)
OTHER_COUNTRY = re.compile(r"\b(us|usa|united states|uk|canada|europe|eu|uae|dubai|singapore|germany|australia)\b")

def intent_rule(nq, ftype, options, p):
    def out(v, src="intent"):
        v = match_option(str(v), options) if options else str(v)
        return Answer(v, 1.0, src) if v else None
    if not re.search(r"\b(company|school|college|university|manager|reference|employer|institution|referrer)\b", nq):
        parts = p["name"].split()
        if re.search(r"\b(first|given) name\b", nq): return out(parts[0])
        if re.search(r"\b(last|family) name\b|\bsurname\b", nq): return out(parts[-1])
        if re.search(r"\b(full|legal|your) name\b", nq) or nq == "name": return out(p["name"])
    if re.search(r"\b(e ?mail)\b", nq) and not re.search(r"\b(alert|notification|subscribe|newsletter)\b", nq): return out("{{email}}")
    if re.search(r"\b(phone|mobile|whatsapp|contact number)\b", nq) and "country code" not in nq: return out("{{phone}}")
    if "linkedin" in nq: return out(p["linkedin"].split("   ")[0])
    if "github" in nq: return out(p["github"])
    if re.search(r"\b(portfolio|personal website)\b", nq) and p.get("portfolio"): return out(p["portfolio"])
    if re.search(r"\b(current|present|home) (location|city)\b", nq) or nq in ("location", "city"):
        return out(p["location"].split(",")[0] if "city" in nq else p["location"])
    if re.search(r"\bnotice\b", nq):
        d = p["notice_days"]
        if re.search(r"\b(serving|currently)\b", nq): return out("No" if d == 0 else "Yes")
        if ftype == "number": return out(d)
        if options:
            return out("Immediate") if d == 0 else None
        return out("Immediate" if d == 0 else f"{d} days")
    if OTHER_COUNTRY.search(nq): return None
    if re.search(r"\b(visa|sponsorship|sponsor)\b", nq): return out("Yes" if p["needs_visa_sponsorship"] else "No")
    if re.search(r"\b(authori[sz]ed|eligible|legally|right) .*\b(work|employ)", nq): return out("Yes" if p["authorized_to_work_india"] else "No")
    m = re.search(r"\b(expected|current)\b.*\b(ctc|salary|compensation)\b", nq) or re.search(r"\b(ctc|salary)\b.*\b(expected|current)\b", nq)
    if m and not re.search(r"\b(usd|dollar|dollars|eur|gbp|monthly|hourly|per month|per hour)\b", nq):
        v = p["expected_ctc_lpa"] if "expected" in nq else p["current_ctc_lpa"]
        if re.search(r"\b(lpa|lakh|lakhs|lac)\b", nq): return out(f"{v:g}")
        if re.search(r"\b(annual|rupees|inr|per annum|p a)\b", nq): return out(int(v * 100000))
    return None

# ---------- strict fuzzy
def _tokens(s): return set(s.split())
def fuzzy(nq, ftype, options):
    best = None
    for q, t, o, out, _ in _dataset():
        if t != ftype or out == "SKIP": continue
        r = difflib.SequenceMatcher(None, nq, q).ratio()
        if r < 0.92: continue
        if (_tokens(nq) ^ _tokens(q)) - STOP: continue    # any differing meaningful word -> reject
        if not best or r > best[0]: best = (r, out)
    if best:
        v = match_option(best[1], options)
        if v: return Answer(v, best[0], "fuzzy")
    return None

# ---------- main entry
def resolve(question, ftype, options=None, model_fn=None, llm_fn=None):
    if model_fn is None:
        try:
            from model_client import model_fn as default_model_fn
            model_fn = default_model_fn
        except ImportError:
            pass
    p, nq = _profile(), norm(question)
    k = key(question, ftype, options)
    for q, t, o, out, kk in _dataset():                     # exact (corrections come first in the list)
        if kk == k:
            return None if out == "SKIP" else _fin(Answer(out, 1.0, "exact"), options, p)
    for q, t, o, out, _ in _dataset():                      # same question, other option list
        if q == nq and t == ftype and out != "SKIP":
            v = match_option(out, options)
            if v: return _fin(Answer(v, 0.97, "exact-q"), options, p)
    a = skill_rule(nq, ftype, options, p) or intent_rule(nq, ftype, options, p)
    if a: return _fin(a, options, p)
    if not re.search(r"\b(experience|years?)\b", nq):
        a = fuzzy(nq, ftype, options)
        if a: return _fin(a, options, p)
    if model_fn:                                            # fine-tuned model hook: -> (answer, confidence)
        ans, conf = model_fn(question, ftype, options)
        v = match_option(ans, options) if ans and ans != "SKIP" else None
        if v and conf >= MIN_CONF: return _fin(Answer(v, conf, "model"), options, p)
    if llm_fn and ftype == "text" and len(nq.split()) >= 4:  # free text only, grounded in profile answers
        txt = llm_fn(question, p["answers"])
        if txt: return _fin(Answer(txt, 0.90, "llm"), options, p)
    return None

def _fin(a, options, p):
    a.value = fill(a.value, p)
    return a if _valid(a, p) else None

def _valid(a, p):
    v = a.value.strip()
    if not v or re.search(r"\bTODO\b|^SKIP$|\{\{", v): return False
    if a.source == "skill-rule":
        try:
            if float(v) > p["total_experience_years"] + 0.01: return False   # can't exceed total experience
        except ValueError: pass
    return True

def resolve_form(fields, url="", **hooks):
    """fields: [{question, ftype, options?, required?}] -> {question: value}; raises SkipApplication."""
    out, bad = {}, []
    for f in fields:
        q, t, o, req = f["question"], f["ftype"], f.get("options"), f.get("required", True)
        a = resolve(q, t, o, **hooks)
        if a and a.conf >= MIN_CONF: out[q] = a.value
        elif req: bad.append(f)
    if bad:
        for f in bad: queue_for_review(f["question"], f["ftype"], f.get("options"), url)
        raise SkipApplication(f"{len(bad)} required field(s) unanswerable: " + "; ".join(f["question"][:50] for f in bad))
    return out

if __name__ == "__main__":
    q, t = sys.argv[1], sys.argv[2]; o = sys.argv[3:] or None
    print(resolve(q, t, o) or "None -> would skip + queue")
