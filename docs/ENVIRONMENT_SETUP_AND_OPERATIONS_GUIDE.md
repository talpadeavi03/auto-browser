# 🛠️ Auto-Browser: Environment Setup & Operations Guide

> **Quick-Start Operations Manual**  
> Everything you need to set up, configure, run, and maintain the Auto-Browser automation suite locally and on the cloud.

---

## 1. Prerequisites

Ensure your system meets the following requirements:
* **Operating System:** Linux (Ubuntu 20.04+, Fedora, Debian), macOS, or Windows (WSL2 recommended).
* **Python:** Python 3.10, 3.11, or 3.12 (`python3 --version`).
* **Browser:** Brave Browser (recommended for anti-fingerprinting) or standard Google Chrome / Chromium.
* **Git:** Installed and configured (`git --version`).

---

## 2. Local Environment Setup

### Step 2.1: Clone the Repository
```bash
git clone https://github.com/talpadeavi03/auto-browser.git
cd auto-browser
```

### Step 2.2: Create and Activate Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
```
*(On Windows PowerShell: `.\venv\Scripts\Activate.ps1`)*

### Step 2.3: Install Python Dependencies & Playwright
```bash
pip install --upgrade pip
pip install -r requirements.txt
playwright install --with-deps chromium
```

---

## 3. Candidate Profile & Resume Configuration

All personal information, qualifications, and search criteria are configured in [`config/settings.yaml`](file:///config/settings.yaml).

### Step 3.1: Place Your PDF Resume
Create the directory and copy your updated PDF resume:
```bash
mkdir -p data/resumes
cp /path/to/your/resume.pdf data/resumes/AT_26_AI.pdf
```

### Step 3.2: Verify Candidate Profile
Open [`config/settings.yaml`](file:///config/settings.yaml) and ensure your information is up to date:
```yaml
profile:
  first_name: "Avinash"
  last_name: "Talpade"
  email: "talpadeavi0303@gmail.com"
  phone: "8999285015"
  current_location: "Pune, Maharashtra, India"
  city: "Pune"
  state: "Maharashtra"
  country: "India"
  postal_code: "411001"
  linkedin_url: "https://www.linkedin.com/in/talpadeavi/"
  github_url: "https://github.com/talpadeavi03"
  headline: "DevOps & Cloud Engineer | AWS, Kubernetes, Terraform, CI/CD, MLOps"
  summary: "Experienced DevOps & Cloud Engineer with 3.6 years of expertise in automating, deploying, and maintaining cloud platforms."
  degree: "Bachelor of Engineering"
  branch: "Information Technology"
  university: "Savitribai Phule Pune University"
  college: "Pune Institute of Computer Technology"
  current_company: "Cloud & DevOps Solutions"
  current_designation: "DevOps Engineer"
  years_of_experience: 3.6
  current_salary_lpa: "4.5"
  expected_salary_lpa: "8.5"
  notice_period_days: "Immediate Joiner"
  require_visa_sponsorship: false
  authorized_to_work: true
  resume_path: "data/resumes/AT_26_AI.pdf"
```

---

## 4. Initial Authentication & Session Capture

To allow the bot to apply on your behalf without entering passwords every time, capture your session cookies once:

### Method A: Interactive CLI Login (Recommended)
```bash
python main.py login --platform all
```
1. An interactive Brave/Chromium browser will open.
2. Log into your **Naukri** account and your **LinkedIn** account.
3. Once logged in and viewing your feed, return to the terminal and press **Enter**.
4. The bot will save your encrypted session to `data/browser_profile/`.

### Method B: Attach Directly to Running Brave Browser (via CDP)
If you already use Brave Browser on Linux:
```bash
# Launch Brave with remote debugging enabled
flatpak run com.brave.Browser --remote-debugging-port=9222
# Or native Brave:
brave-browser --remote-debugging-port=9222
```
When Auto-Browser detects port `9222`, it connects directly to your active browser tab, inheriting your existing logins!

---

## 5. Exporting Auth State for 24/7 Cloud Running

To run 24/7 on GitHub Actions without keeping your laptop on:

```bash
python main.py export-auth
```
**Output:**
```
✓ Successfully exported 43 session cookies!
Cloud Secret saved to: data/auth_secret_for_github.txt
```

---

## 6. GitHub Actions Cloud Setup (24/7 Automation)

### Step 6.1: Add Secrets to GitHub Repository
1. Go to your repository on GitHub:  
   `https://github.com/talpadeavi03/auto-browser/settings/secrets/actions`
2. Click **New repository secret**:
   * **Secret 1:**
     * Name: `AUTH_STORAGE_STATE`
     * Value: *Paste the full string from `data/auth_secret_for_github.txt`*
   * **Secret 2:**
     * Name: `GEMINI_API_KEY`
     * Value: *Your Google Gemini API Key from Google AI Studio*

### Step 6.2: Automated Schedule
The cloud worker runs automatically:
* **Every 4 hours**: Refreshes Naukri profile to maintain **"Active Today"** rank, applies to top matching LinkedIn and Naukri jobs, and uploads Excel reports.
* **On Git Push**: Re-verifies pipeline, boosts profile, and checks recent postings.

---

## 7. CLI Operations Reference

Run any command locally via `python main.py <COMMAND>`:

```bash
# Full automation sequence: Boost profile -> LinkedIn Apply -> Naukri Apply
python main.py run-all --limit 5

# Boost Naukri profile ranking to #1 'Active Today'
python main.py naukri-refresh

# Auto-apply to LinkedIn Easy Apply jobs
python main.py linkedin-apply --limit 10

# Auto-apply to Naukri jobs
python main.py naukri-apply --limit 10

# Apply directly to ANY external company ATS (Keka, Greenhouse, Lever, Workday)
python main.py external-apply --url "https://company.keka.com/careers/applyjob/123" --company "Target Company" --title "DevOps Engineer"

# Scrape matching jobs without applying
python main.py scrape --platform all

# Display metrics table of all applied & scraped jobs
python main.py stats

# Export database records to Excel (.xlsx) and CSV
python main.py export

# Export recorded interaction dataset for Google Colab fine-tuning
python main.py export-dataset
```

---

## 8. Model Context Protocol (MCP) Server Setup

The MCP server exposes Auto-Browser capabilities as standardized tools for AI agents (Claude Desktop, Cursor, Antigravity):

### Start MCP Server:
```bash
python mcp_server.py
```

### Available MCP Tools:
* `get_candidate_profile`: Returns candidate skills, contact info, and compensation.
* `search_jobs(platform, keyword, location)`: Scrapes live listings matching role.
* `inspect_job_description(platform, job_url)`: Extracts description and requirements.
* `linkedin_inspect_easy_apply_step(job_url)`: Reads questions on the current modal step.
* `apply_linkedin_easy_apply_smart(job_url, job_title, company)`: Autonomously applies to LinkedIn Easy Apply.
* `apply_naukri_direct(job_url, job_title, company)`: Autonomously applies to Naukri 1-Click job.
* `apply_external_company_job(job_url, company, job_title)`: Autonomously applies to external ATS portals.
* `boost_naukri_profile()`: Updates resume headline timestamp.
* `ai_answer_screening_question(question, field_type, options)`: Answers screening questions with Gemini.
* `export_ml_training_dataset()`: Dumps interaction dataset into ChatML JSONL format.

---

## 9. Google Colab ML Training Step-by-Step

Train a specialized Small Language Model (`Qwen-2.5-1.5B-Instruct`) for free:

1. **Export Latest Dataset:**
   ```bash
   python main.py export-dataset
   ```
   *(Creates `data/training_dataset.jsonl`)*.
2. **Open in Google Colab:**
   * Go to [Google Colab](https://colab.research.google.com/).
   * Click **File $\rightarrow$ Upload notebook**, and upload [`notebooks/train_colab.ipynb`](file:///notebooks/train_colab.ipynb).
3. **Select Free GPU:**
   * Click **Runtime $\rightarrow$ Change runtime type $\rightarrow$ T4 GPU**.
4. **Click "Run All":**
   * The notebook clones your repo, loads `training_dataset.jsonl`, attaches 4-bit LoRA adapters, and trains with `SFTTrainer` in **3 to 5 minutes**.
5. **Save to Hugging Face Hub (Free):**
   * Provide your free Hugging Face Write Token in Step 7 of the notebook to push your model directly to Hugging Face.

---

## 10. Maintenance & Troubleshooting

| Issue | Cause | Fix |
| :--- | :--- | :--- |
| **"Continuing in unauthenticated mode" on GitHub** | Session cookies expired after 30–60 days | Run `python main.py export-auth` locally, copy `data/auth_secret_for_github.txt`, and update GitHub Secret `AUTH_STORAGE_STATE`. |
| **LinkedIn displays in non-English language** | Historical browser locale cache | Auto-resolved by `ensure_linkedin_english()` in `modules/linkedin/scraper.py`. |
| **Notice period field validation error** | Input expects number of days, not string | Auto-resolved: "Immediate Joiner" is converted to numeric `0` days. |
| **External ATS readonly datepicker timeout** | Playwright default timeout on uneditable fields | Auto-resolved: `_safe_fill` verifies `is_editable()` and skips readonly elements. |
| **Captcha on external portal** | Simple text/image captcha | Auto-resolved: Canvas extracts base64 PNG and Gemini Vision solves it. |

---
*For further assistance, refer to [`docs/PROJECT_ARCHITECTURE_AND_SYSTEM_DESIGN.md`](file:///docs/PROJECT_ARCHITECTURE_AND_SYSTEM_DESIGN.md).*
