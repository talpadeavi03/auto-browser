#!/usr/bin/env python3
"""Build training_dataset.jsonl from profile.yaml + corrections + cleaned old rows.

  python build_dataset.py build [--existing path/to/old.jsonl]
  python build_dataset.py review          # answer fields the bot couldn't answer
  python build_dataset.py check           # show what the old dataset got wrong

Priority (first wins per question): corrections > profile-generated > cleaned old rows.
Phone/email are written as {{phone}} / {{email}} placeholders; fill at runtime with fill().
"""
import json, re, sys, argparse, pathlib
import yaml

D = pathlib.Path("data")
OUT, CORR, QUEUE = D / "training_dataset.jsonl", D / "corrections.jsonl", D / "review_queue.jsonl"
INSTR = "Fill job-application fields truthfully from the candidate profile. If unsure, answer SKIP."
JUNK = re.compile(r"^(given the|month$|year$|select|please select|choose)", re.I)

def norm(s):  # normalise a question for matching
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9/+ ]", " ", s.lower())).strip()

def prompt(q, ftype, options=None):
    s = f"Recruiter Question: '{q}'\nField Type: {ftype}"
    if options: s += "\nAvailable Options: " + ", ".join(options)
    return s

def key(q, ftype, options=None):
    return norm(q) + "|" + ftype + "|" + ",".join(sorted(norm(o) for o in (options or [])))

def load(path):
    if not pathlib.Path(path).exists(): return []
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]

def fill(text, p):  # runtime: replace placeholders with real values
    return text.replace("{{email}}", p["email"]).replace("{{phone}}", str(p["phone"]))

def pick_range(options, y):
    for o in options:
        m = re.match(r"\s*(\d+(?:\.\d+)?)\s*[-–to]+\s*(\d+(?:\.\d+)?)", o)
        if m and float(m[1]) <= y < float(m[2]): return o
    return None

# ---------------------------------------------------------------- generation
def generate(p):
    rows = []
    def add(qs, ftype, ans, options=None):
        if ans in (None, ""): return
        for q in ([qs] if isinstance(qs, str) else qs):
            rows.append((key(q, ftype, options), prompt(q, ftype, options), str(ans)))

    add(["What is your email address?", "Email", "Contact email", "email address*", "Email ID"], "text", "{{email}}")
    add(["Mobile phone number", "What is your primary contact number / phone number?", "Phone", "Contact number"], "text", "{{phone}}")
    add(["LinkedIn Profile", "Please enter your LinkedIn profile URL", "LinkedIn URL"], "text", p["linkedin"])
    add(["GitHub", "Please provide your GitHub profile link", "GitHub URL"], "text", p["github"])
    add(["Portfolio", "Website", "Portfolio URL"], "text", p.get("portfolio"))
    add(["What is your current location?", "Current city", "City", "Location"], "text", p["location"])
    add(["What is your postal / ZIP code?", "Postal code", "Pincode"], "text", p["postal_code"])

    add(["Current Employer", "Current company", "Most recent employer"], "text", p["current_employer"])
    add(["Designation / Job Title", "Current job title", "Current designation"], "text", p["job_title"])
    y = p["total_experience_years"]
    add(["Total years of software/IT industry experience?", "Total experience (years)", "Total years of experience"], "number", y)
    add(["How much is your relevant exp. as a DevOps Engineer?", "Years of relevant experience in DevOps"], "number", y)
    for opts in (["0-1 years","1-3 years","3-5 years","5-8 years","8+ years"], ["0-2 years","2-4 years","4-6 years","6+ years"]):
        add("Total Experience", "dropdown", pick_range(opts, y), opts)

    # notice / joining
    d = p["notice_days"]
    for q in ["Notice period (in days)", "How many days notice are you required to serve?", "Available To Join (in days)"]:
        add(q, "number", d)
    add(["How soon can you join if selected?", "Earliest joining date"], "text", "Immediately" if d == 0 else f"{d} days")
    add("Are you currently serving notice period?", "text", "No" if d == 0 else "Yes")
    for opts in (["Immediate","15 Days","30 Days","60 Days","90 Days"], ["Immediate","Less than 15 days","15-30 days","1-2 months","3 months"]):
        add(["Notice Period", "Notice period"], "dropdown", opts[0] if d == 0 else None, opts)

    # compensation
    cur, exp = p["current_ctc_lpa"], p["expected_ctc_lpa"]
    for lab, v in (("Current", cur), ("Expected", exp)):
        add([f"{lab} CTC (Annual)", f"{lab} CTC in rupees"], "text", int(v * 100000))
        add([f"What is your {lab.lower()} CTC in Lakhs (LPA)?", f"{lab} CTC (LPA)", f"{lab} CTC in lakhs"], "text", v)

    # education
    add(["Degree / Course", "Highest Degree?", "Degree"], "text", p["highest_degree"])
    add(["Branch / Specialization", "Specialization", "Field of study"], "text", p["degree_branch"])
    add(["University / College", "College or Institute Name", "Which university or college did you graduate from?", "University"], "text", p["university"])
    add(["Year of Graduation", "Graduation year", "Passing year"], "text", p["graduation_year"])
    add("Highest Qualification", "dropdown", p["highest_qualification_bucket"],
        ["High School", "Diploma", "Bachelor's Degree", "Master's Degree", "PhD"])

    # certs
    certs = "; ".join(p["certifications"])
    aws_held = next((c for c in p["certifications"] if "AWS" in c), None)
    aws_wip = next((c for c in p.get("in_progress_certs", []) if "AWS" in c), None)
    add(["Which AWS certification do you have?", "AWS certifications"], "text",
        aws_held or ("None yet; " + aws_wip + " in progress" if aws_wip else "None"))
    add(["Which certifications do you hold?", "Certifications"], "text", certs)
    if p.get("in_progress_certs"):
        add(["Certifications in progress", "Are you pursuing any certification?"], "text", "; ".join(p["in_progress_certs"]))
    for opts in (["Yes", "No"],):
        add(["Do you hold an active AWS Certification?", "Do you have an AWS certification?"], "radio",
            "Yes" if p["holds_aws_cert"] and p.get("cert_valid_until") else ("No" if not p["holds_aws_cert"] else None), opts)

    # skills (honest: skills_none -> 0 / No)
    allsk = dict(p["skills"]); allsk.update({s: 0 for s in p.get("skills_none", [])})
    for s, yrs in allsk.items():
        for q in [f"How many years of experience do you have with {s}?", f"How many years of work experience do you have with {s}?",
                  f"Years of experience in {s}", f"{s} experience (in years)"]:
            add(q, "number", yrs)
        for q in [f"Do you have experience with {s}?", f"Do you have hands-on experience in {s}?", f"Have you worked with {s}?"]:
            add(q, "radio", "Yes" if yrs > 0 else "No", ["Yes", "No"])
    add(["Key Skills", "Skills"], "text", ", ".join(p["skills"]))

    # eligibility
    yn = lambda b: "Yes" if b else "No"
    add(["Are you legally authorized to work in India?", "Work authorization"], "radio", yn(p["authorized_to_work_india"]), ["Yes", "No"])
    add(["Will you now or in the future require visa sponsorship?", "Do you require sponsorship?"], "radio", yn(p["needs_visa_sponsorship"]), ["Yes", "No"])
    add(["Are you comfortable with background checks?", "Do you consent to a background check?"], "radio", yn(p["ok_background_check"]), ["Yes", "No"])
    add(["Have you been convicted of any crime?", "Do you have a criminal record?"], "radio", yn(p["criminal_record"]), ["Yes", "No"])
    for city in p["willing_to_relocate"]:
        add([f"Are you willing to relocate to {city}?", f"Are you fine working from {city} location?"], "radio", "Yes", ["Yes", "No"])
    add("Work Mode Preference", "dropdown", p["work_modes"], ["On-site", "Hybrid", "Remote", "Any"])
    add("Gender", "dropdown", p.get("gender"), ["Male", "Female", "Non-binary", "Prefer not to say"])

    # migrations + free text
    add(["Which tools have you used for migration?"], "text", p.get("migration_tools"))
    add(["Approximately how many server or database have you migrated?"], "text", p.get("migration_count_text"))
    a = p["answers"]
    ft = {"kubernetes_summary": ["Briefly summarize your experience with Kubernetes:", "Describe your Kubernetes experience"],
          "cicd_summary": ["Briefly describe your CI/CD pipeline experience:", "Describe your CI/CD experience"],
          "iac_summary": ["Describe your experience with Infrastructure as Code (IaC):", "Tell us about your Terraform experience"],
          "monitoring_summary": ["What observability and monitoring tools have you configured in production?"],
          "migration_summary": ["Briefly describe your experience with cloud migration:"],
          "why_this_role": ["Why are you interested in this role?", "Why do you want to join us?"]}
    for k, qs in ft.items():
        if a.get(k) and not a[k].startswith("TODO"): add(qs, "text", a[k])
    return rows

# ---------------------------------------------------------------- cleaning old rows
def parse_input(inp):
    q = re.search(r"Question: '(.*?)'", inp, re.S)
    t = re.search(r"Field Type: (\w+)", inp)
    o = re.search(r"Available Options: (.*)", inp)
    return (q[1] if q else inp), (t[1] if t else "text"), ([x.strip() for x in o[1].split(",")] if o else None)

def clean_old(path, p):
    keep, dropped = [], []
    banned = [b.lower() for b in p.get("banned_claims", [])]
    for r in load(path):
        out = r["output"].strip()
        out = out.replace(p["email"], "{{email}}").replace(str(p["phone"]), "{{phone}}")
        why = ("junk" if JUNK.match(out) else "banned" if any(b in out.lower() for b in banned) else None)
        q, t, o = parse_input(r["input"])
        if why: dropped.append((why, q, out[:60]))
        else: keep.append((key(q, t, o), prompt(q, t, o), out))
    return keep, dropped

# ---------------------------------------------------------------- commands
def cmd_build(args):
    p = yaml.safe_load(open("profile.yaml", encoding="utf-8"))
    final, seen = [], set()
    corr = [(key(*parse_input(r["input"])), r["input"], r["output"]) for r in load(CORR)] if CORR.exists() else []
    gen = generate(p)
    old, dropped = clean_old(args.existing, p) if args.existing else ([], [])
    covered = {k.split("|")[0] for k, _, _ in corr + gen}      # a question the profile covers is never taken from old rows
    old = [r for r in old if r[0].split("|")[0] not in covered]
    for src, rows in (("corrections", corr), ("profile", gen), ("old", old)):
        n = 0
        for k, inp, out in rows:
            if k in seen: continue
            seen.add(k); n += 1
            final.append({"instruction": INSTR, "input": inp, "output": out, "source": src})
        print(f"{src:12s} {n:4d} rows")
    D.mkdir(exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        for r in final: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(final)} rows -> {OUT}  (dropped {len(dropped)} bad old rows)")
    todo = [k for k, v in p["answers"].items() if str(v).startswith("TODO")]
    if todo: print("WARNING: fill these in profile.yaml answers:", ", ".join(todo))

def cmd_check(args):
    p = yaml.safe_load(open("profile.yaml", encoding="utf-8"))
    _, dropped = clean_old(args.existing, p)
    for why, q, o in dropped: print(f"[{why}] {q[:60]!r} -> {o!r}")
    print(len(dropped), "rows would be dropped")

def cmd_review(args):
    q = load(QUEUE)
    if not q: return print("queue empty")
    remaining = []
    for r in q:
        print(f"\nQ: {r['question']}\ntype={r['field_type']} options={r.get('options')} site={r.get('url','')}")
        a = input("answer (enter=skip, !=never answer): ").strip()
        if not a: remaining.append(r); continue
        a = "SKIP" if a == "!" else a
        with open(CORR, "a", encoding="utf-8") as f:
            f.write(json.dumps({"input": prompt(r["question"], r["field_type"], r.get("options")), "output": a}, ensure_ascii=False) + "\n")
    with open(QUEUE, "w", encoding="utf-8") as f:
        for r in remaining: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("saved. now run: python build_dataset.py build")

# ---------------------------------------------------------------- runtime helpers (import these from your bot)
def lookup(question, field_type, options=None, dataset=OUT):
    """Exact-match answer from the built dataset, or None -> call queue_for_review()."""
    k = key(question, field_type, options)
    for r in load(dataset):
        if key(*parse_input(r["input"])) == k:
            return None if r["output"] == "SKIP" else r["output"]
    return None

def queue_for_review(question, field_type, options=None, url=""):
    D.mkdir(exist_ok=True)
    with open(QUEUE, "a", encoding="utf-8") as f:
        f.write(json.dumps({"question": question, "field_type": field_type, "options": options, "url": url}) + "\n")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "review", "check"])
    ap.add_argument("--existing")
    a = ap.parse_args()
    {"build": cmd_build, "review": cmd_review, "check": cmd_check}[a.cmd](a)
