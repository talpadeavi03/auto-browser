#!/usr/bin/env python3
"""Held-out evaluation. Release gate: wrong_rate < 1% and accuracy >= 98% on answered fields.
Cases use phrasings NOT in the training templates. 'SKIP' = the correct behaviour is to abstain.
Add real mistakes/corrections to data/eval_set.jsonl over time: {"question","ftype","options","expected"}.
"""
import json, pathlib, yaml
from answers import resolve, reload
from build_dataset import norm

def builtin(p):
    Y = ["Yes", "No"]; yrs = p["total_experience_years"]
    return [
     ("Please share your email ID", "text", None, p["email"]),
     ("Mobile number*", "text", None, str(p["phone"])),
     ("Link to your LinkedIn", "text", None, p["linkedin"].split()[0]),
     ("Years of experience with Terraform", "number", None, f"{p['skills']['Terraform']:g}"),
     ("How many years have you worked with Docker?", "number", None, f"{p['skills']['Docker']:g}"),
     ("Experience in K8s (years)", "number", None, f"{p['skills']['Kubernetes']:g}"),
     ("Do you have hands-on experience with Jenkins?", "radio", Y, "Yes"),
     ("Do you have experience with Splunk?", "radio", Y, "No"),
     ("Years of experience with Datadog", "number", None, "0"),
     ("Experience with Terraform", "dropdown", ["0-1","1-3","3-5","5+"], "3-5"),
     ("Are you authorized to work in India?", "radio", Y, "Yes"),
     ("Do you need visa sponsorship?", "radio", Y, "No"),
     ("What is your notice period?", "dropdown", ["Immediate","15 Days","30 Days","60 Days"], "Immediate"),
     ("Current location", "text", None, p["location"]),
     ("Expected CTC in LPA", "text", None, str(p["expected_ctc_lpa"])),
     ("Highest qualification", "dropdown", ["High School","Diploma","Bachelor's Degree","Master's Degree","PhD"], "Master's Degree"),
     ("Do you hold an active AWS Certification?", "radio", Y, "No"),
     # must abstain: unknown tools, personal data not in profile, company-specific essays, ambiguous
     ("Years of experience with Java", "number", None, "SKIP"),
     ("Years of experience with Ansible and Puppet", "number", None, "SKIP"),
     ("Experience with Rust", "radio", Y, "SKIP"),
     ("Your gender", "dropdown", ["Male","Female","Prefer not to say"], "SKIP"),
     ("Why do you want to work at Acme Corp?", "text", None, "SKIP"),
     ("Expected salary in USD", "text", None, "SKIP"),
     ("Date of birth", "text", None, "SKIP"),
     ("Do you have a valid passport?", "radio", Y, "SKIP"),
     ("Years of experience with Kubernetes and Terraform", "number", None, "SKIP"),
    ]

def run():
    reload(); p = yaml.safe_load(open("profile.yaml", encoding="utf-8"))
    cases = builtin(p)
    ev = pathlib.Path("data/eval_set.jsonl")
    if ev.exists():
        cases += [(r["question"], r["ftype"], r.get("options"), r["expected"]) for r in map(json.loads, ev.open())]
    ok = wrong = abst_ok = abst_bad = 0; fails = []
    for q, t, o, exp in cases:
        a = resolve(q, t, o); got = a.value if a else "SKIP"
        if exp == "SKIP":
            if a is None: abst_ok += 1
            else: wrong += 1; fails.append((q, exp, got))
        elif a is None: abst_bad += 1; fails.append((q, exp, "SKIP (missed)"))
        elif norm(got) == norm(str(exp)): ok += 1
        else: wrong += 1; fails.append((q, exp, got))
    answerable = ok + wrong + abst_bad - sum(1 for *_, e in cases if e == "SKIP" and False)
    n = len(cases); answered = ok + wrong
    print(f"cases={n}  correct={ok}  wrong={wrong}  correct_abstain={abst_ok}  missed_answer={abst_bad}")
    print(f"wrong_rate={wrong/n:.1%}  accuracy_on_answered={ok/max(answered,1):.1%}  coverage_of_answerable={ok/max(ok+abst_bad+ (wrong - sum(1 for _,e,_ in fails if e=='SKIP')),1):.1%}")
    for f in fails: print("  FAIL:", f)
    return wrong == 0

if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
