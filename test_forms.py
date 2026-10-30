import sys, pathlib
HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))
from playwright.sync_api import sync_playwright
from forms import run_form
CASES = [  # fixture, expected status
    ("ok.html", "submitted"), ("styled_radio.html", "submitted"), ("multistep.html", "submitted"), ("landing.html", "submitted"),
    ("unknown_question.html", "skipped"), ("captcha.html", "skipped"),
]
ok = True
with sync_playwright() as pw:
    br = pw.chromium.launch(headless=True)
    for name, want in CASES:
        pg = br.new_page(); pg.goto((HERE / "fixtures" / name).as_uri())
        r = run_form(pg, resume_path=str(HERE / "resume.pdf"), url=name, dry_run=False)
        good = r["status"] == want; ok &= good
        print(("PASS" if good else "FAIL"), f"{name:24s} -> {r['status']:10s} {r['reason'][:80]}")
        if good and want == "submitted" and name == "ok.html": print("      answers:", r["answers"])
    br.close()
raise SystemExit(0 if ok else 1)
