#!/usr/bin/env python3
"""Run automated application on any external job URL (Greenhouse, Lever, Workday, etc.).

Usage:
  python run_external.py --url "https://jobs.lever.co/company/job-id" [--dry-run] [--headful]
"""
import sys
import argparse
import pathlib
from playwright.sync_api import sync_playwright

from forms import run_form
from model_client import model_fn

HERE = pathlib.Path(__file__).parent
RESUME_DEFAULT = HERE / "data" / "resumes" / "resume.pdf"

def main():
    parser = argparse.ArgumentParser(description="Autonomous External ATS Form Applier")
    parser.add_argument("--url", required=True, help="External application page URL")
    parser.add_argument("--resume", default=str(RESUME_DEFAULT), help="Path to resume.pdf")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Fill all fields but do not click final submit")
    parser.add_argument("--headful", action="store_true", default=False, help="Show browser window while running")
    args = parser.parse_args()

    print(f"🚀 Navigating to external application: {args.url}")
    print(f"📄 Resume: {args.resume}")
    print(f"🤖 Autonomous Model: Active (model_fn hook enabled)")
    print(f"⚙️ Mode: {'DRY RUN (verification only)' if args.dry_run else 'LIVE SUBMIT'}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headful)
        page = browser.new_page()
        try:
            page.goto(args.url, wait_until="domcontentloaded", timeout=45000)
            
            # Run the autonomous form filler with model_fn passed as hook
            result = run_form(
                page=page,
                resume_path=args.resume,
                url=args.url,
                dry_run=args.dry_run,
                model_fn=model_fn  # <-- Passes fine-tuned model into answers.py
            )

            print("\n" + "=" * 50)
            print(f"Application Result Status: {result['status'].upper()}")
            if result.get("reason"):
                print(f"Reason: {result['reason']}")
            if result.get("answers"):
                print("\nAnswered Fields Summary:")
                for q, a in result["answers"].items():
                    print(f"  • {q} -> {a}")
            print("=" * 50)

        except Exception as e:
            print(f"❌ Error during application: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    main()
