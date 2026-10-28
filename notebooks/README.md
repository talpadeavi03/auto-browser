# 🤖 Auto-Browser: GitHub ↔ Colab ↔ MLflow Training Loop

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/talpadeavi03/auto-browser/blob/master/notebooks/train_colab.ipynb)

This pipeline establishes an autonomous, end-to-end MLOps loop across **GitHub**, **Google Colab**, and **MLflow**:

```
┌────────────────────────────────┐          ┌────────────────────────────────┐
│      GitHub Actions / Repo     │          │          Google Colab          │
│ • Runs 24/7 cloud RPA bot      │          │ • Free T4 GPU Training         │
│ • Logs Q&A to jobs.db          │─────────>│ • Pulls training_dataset.jsonl │
│ • Auto-syncs dataset to master │          │ • Fine-tunes Qwen-2.5-1.5B     │
│ • Receives updated model card  │<─────────│ • Pushes release metadata back │
└────────────────────────────────┘          └───────────────┬────────────────┘
                                                            │
                                                            ▼ (Logs metrics & artifacts)
                                            ┌────────────────────────────────┐
                                            │       Remote MLflow Hub        │
                                            │ • DagsHub Free Hosted MLflow   │
                                            │ • Model Registry (v1, v2, ...) │
                                            │ • Loss curves & hyperparameters│
                                            └────────────────────────────────┘
```

---

## 🛠️ The Triad Architecture

| Component | Role | Free Cloud Provider |
| :--- | :--- | :--- |
| **GitHub** | Code repository, CI/CD Actions, Dataset versioning, Model release docs | GitHub |
| **Google Colab** | High-performance GPU fine-tuning (LoRA 4-bit NF4) in ~3-5 mins | Google Colab (T4 GPU) |
| **MLflow** | Remote experiment tracking server, metrics logger, and central Model Registry | DagsHub (Integrated with GitHub) |

---

## 🚀 Step-by-Step Setup Guide

### 1. One-Time Setup: Connect DagsHub Free MLflow Server (2 minutes)
DagsHub provides a 100% free remote MLflow server connected to your GitHub repository:
1. Go to [dagshub.com](https://dagshub.com) and click **Sign in with GitHub**.
2. Click **Create** → **Migrate Repo** (or Connect existing repository) → Select `talpadeavi03/auto-browser`.
3. Your free hosted MLflow server is now live at:  
   `https://dagshub.com/talpadeavi03/auto-browser.mlflow`

### 2. (Optional) Add `GITHUB_TOKEN` in Colab for Automatic Commit
To let Colab automatically commit the model release card ([`docs/LATEST_MODEL.md`](file:///home/sudo69/Projects/auto-browser/docs/LATEST_MODEL.md)) back to GitHub:
1. Generate a GitHub Personal Access Token (classic) with `repo` scope at [GitHub Settings -> Tokens](https://github.com/settings/tokens).
2. In Google Colab, click the **🔑 Secrets** icon on the left panel.
3. Add a secret named `GITHUB_TOKEN` and paste your token.

### 3. Run Training on Colab
1. Click **[Open in Colab](https://colab.research.google.com/github/talpadeavi03/auto-browser/blob/master/notebooks/train_colab.ipynb)**.
2. Select **Runtime** → **Change runtime type** → **T4 GPU** (Free).
3. Click **Runtime** → **Run all** (`Ctrl + F9`).

### What Happens Automatically:
1. Colab pulls `data/training_dataset.jsonl` from GitHub.
2. Connects to your DagsHub remote MLflow server.
3. Fine-tunes `Qwen/Qwen2.5-1.5B-Instruct` in 4-bit with LoRA.
4. Streams loss curves live to MLflow dashboard.
5. Saves and registers the model in the **MLflow Model Registry** under `AutoBrowser-DevOps-Agent`.
6. Updates [`docs/LATEST_MODEL.md`](file:///home/sudo69/Projects/auto-browser/docs/LATEST_MODEL.md) and pushes the commit back to GitHub master branch!

---

## ⚡ How Auto-Browser Uses the Trained Model

Once registered in MLflow, Auto-Browser can load or download the model using any of the following:

### Method 1: Load directly via MLflow
```python
import mlflow.transformers
model = mlflow.transformers.load_model("models:/AutoBrowser-DevOps-Agent/latest")
```

### Method 2: Download Artifacts into Project
```bash
python -c "import mlflow; mlflow.artifacts.download_artifacts('models:/AutoBrowser-DevOps-Agent/latest', dst_path='data/trained_model')"
```
Auto-Browser will automatically detect `data/trained_model/` and prioritize it over Gemini and heuristics.
