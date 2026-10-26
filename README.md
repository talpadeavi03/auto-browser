# 🤖 Auto-Browser: Anti-Detect Job Application RPA Suite

A resilient, stealth-enabled browser automation system tailored for **Naukri.com**, **LinkedIn**, and modern hiring portals. It automates repetitive job searches, 1-click applications, and profile ranking boosts without triggering bot detection or repeated 2FA challenges.

---

### ⚠️ Note on Chromium
> **You do NOT need to clone the 40+ GB Chromium C++ source repository (`chromium/chromium.git`).**
> This project uses **Playwright** with precompiled Chromium and **Playwright-Stealth**. It manages a persistent user profile (`data/browser_profile`), allowing you to log in once interactively with 2FA/OTP, and permanently preserves your authenticated sessions.

---

## 🌟 Key Features

| Feature | Platform | Description |
|---|---|---|
| **Daily Profile Booster** | **Naukri** | Automatically edits and re-saves your Resume Headline to update your *"Profile Last Updated"* timestamp to today. This pushes you to the top of recruiter searches ("Active in last 7 days"). |
| **Easy Apply Automation** | **LinkedIn** | Scrapes matching jobs with the `Easy Apply` badge and automatically fills out multi-step contact info, resume selection, experience, and screening questions. |
| **1-Click Job Applier** | **Naukri** | Automates direct applications while gracefully handling or skipping non-standard screening questionnaires. |
| **Scraper & Deduplication** | **Both** | Tracks all seen and applied jobs in an internal SQLite database (`data/jobs.db`) so you **never** apply to the same position twice. |
| **Anti-Detection & Stealth** | **All** | Injects evasions to hide `navigator.webdriver`, masks Chrome DevTools Protocol fingerprints, and simulates human typing/scrolling delays. |
| **Automated Reporting** | **Both** | Exports tracking metrics, timestamps, and application statuses to Excel (`.xlsx`) and CSV files. |
| **Background Scheduler** | **Both** | Runs a background daemon (`scheduler.py`) that boosts your Naukri profile every 4 hours and executes daily application rounds. |

---

## 📁 Project Structure

```
auto-browser/
├── config/
│   ├── settings.yaml          # Search keywords, locations, profile information
│   └── config.py              # Pydantic configuration loader
├── core/
│   ├── browser.py             # Playwright persistent context & stealth manager
│   ├── logger.py              # Rich terminal and file logging
│   └── storage.py             # SQLite database engine & deduplication
├── modules/
│   ├── linkedin/
│   │   ├── scraper.py         # LinkedIn job search parser
│   │   └── easy_apply.py      # LinkedIn multi-step Easy Apply engine
│   ├── naukri/
│   │   ├── profile_updater.py # Daily profile refresh / recruiter rank booster
│   │   ├── scraper.py         # Naukri job listings scraper
│   │   └── auto_apply.py      # 1-Click direct applier
│   └── tracker/
│       └── export.py          # Excel / CSV reporting & statistics
├── data/
│   ├── browser_profile/       # Stored cookies & session storage (persistent)
│   ├── resumes/               # Place your resume.pdf here
│   ├── exports/               # Generated Excel and CSV reports
│   └── jobs.db                # SQLite database tracking all applications
├── main.py                    # Unified CLI tool
├── scheduler.py               # 24/7 background automation daemon
└── requirements.txt
```

---

## 🚀 Quickstart Guide

### 1. Activate Environment & Setup
The virtual environment and dependencies are already configured in this workspace:
```bash
cd /home/sudo69/Projects/auto-browser
source venv/bin/activate
```

### 2. Configure Your Profile & Preferences
Edit `config/settings.yaml` to specify your target keywords, locations, experience level, and contact details:
```yaml
profile:
  first_name: "YourName"
  last_name: "YourLastName"
  email: "your.email@example.com"
  phone: "9876543210"
  years_of_experience: 3
  current_salary_lpa: "12"
  expected_salary_lpa: "18"
  notice_period_days: 15
  resume_path: "data/resumes/resume.pdf"

linkedin:
  search_keywords: ["Python Developer", "Full Stack Developer"]
  locations: ["India", "Remote", "Bengaluru"]
  date_posted: "past_week" # past_24h, past_week, past_month
  max_applications_per_run: 15

naukri:
  profile_refresh:
    enabled: true
    interval_hours: 4
  search_keywords: ["Python Developer", "Backend Engineer"]
  locations: ["Bengaluru", "Remote"]
```

Place your latest resume PDF into `data/resumes/resume.pdf`.

---

### 3. One-Time Interactive Login
Run the login command:
```bash
python main.py login --platform all
```
- A Chromium browser window will open.
- Log into LinkedIn and Naukri normally (complete any OTP/2FA or captcha).
- The system automatically detects your successful authentication, stores the session in `data/browser_profile`, and closes safely.
- **You do not need to log in again.** Subsequent runs reuse this saved session.

---

## ⚡ CLI Commands

### 1. Boost Naukri Profile (Instant Rank Refresh)
Updates your resume headline timestamp so recruiters see your profile as "Active Today":
```bash
python main.py naukri-refresh
```

### 2. Run LinkedIn Easy Apply
Automatically applies to matching jobs up to the specified limit:
```bash
python main.py linkedin-apply --limit 15
```

### 3. Run Naukri 1-Click Apply
```bash
python main.py naukri-apply --limit 15
```

### 4. Complete Automation Pipeline
Runs profile boost, LinkedIn Easy Apply, Naukri Apply, and exports reports in one step:
```bash
python main.py run-all --limit 10
```

### 5. View Real-Time Application Stats
```bash
python main.py stats
```

### 6. Export Application Reports
```bash
python main.py export
```
Exports `.xlsx` and `.csv` sheets to `data/exports/` detailing applied jobs, timestamps, company names, and URLs.

---

## ⏰ 24/7 Background Scheduler
To run continuous background automation (boosts Naukri profile every 4 hours and applies to new jobs twice daily):
```bash
python scheduler.py
```
Or run as a systemd service or background process:
```bash
nohup python scheduler.py > data/scheduler.log 2>&1 &
```
