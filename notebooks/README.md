# 🤗 Auto-Browser: Hugging Face Hub Model Training Pipeline

This directory contains the production-ready pipeline to fine-tune your specialized AI screening agent (`Qwen-2.5-1.5B-Instruct`) on **Free Google Colab T4 GPU** and push it directly to **Hugging Face Hub** (Public or Private repository).

---

## 🔄 The Hugging Face Loop

```
┌────────────────────────────────┐          ┌────────────────────────────────┐
│      Auto-Browser Dataset      │          │          Google Colab          │
│ • data/training_dataset.jsonl  ├─────────>│ • Free T4 GPU Training         │
│ • 67+ screening Q&A pairs      │          │ • 4-bit LoRA (Qwen-2.5-1.5B)   │
└────────────────────────────────┘          └───────────────┬────────────────┘
                                                            │
                                                            ▼ (1-Click Push)
                                            ┌────────────────────────────────┐
                                            │      Hugging Face Hub 🤗       │
                                            │ • Private/Public Model Repo    │
                                            │ • Free Serverless Inference    │
                                            │ • Versioning & Git Commits     │
                                            └───────────────┬────────────────┘
                                                            │
                                                            ▼ (Free Cloud Queries)
                                            ┌────────────────────────────────┐
                                            │       Auto-Browser Bot         │
                                            │ • Autonomous form answering    │
                                            └────────────────────────────────┘
```

---

## 🚀 How to Train & Deploy in 3 Steps

### Step 1: Open the Notebook in Google Colab
1. Go to **[colab.research.google.com](https://colab.research.google.com)**.
2. Click **Upload** → Browse to [`notebooks/train_colab.ipynb`](file:///home/sudo69/Projects/auto-browser/notebooks/train_colab.ipynb).
3. Set Runtime to **T4 GPU** (**Runtime** → **Change runtime type** → **T4 GPU**).

### Step 2: Login with Free Hugging Face Write Token
1. Get your free Hugging Face Write Token at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens).
2. Run Step 2 in the notebook to log in.

### Step 3: Run All Cells
* The model fine-tunes in **~3 minutes**.
* Step 8 auto-pushes the trained LoRA adapter to your Hugging Face account:
  `https://huggingface.co/<your-username>/auto-browser-devops-agent`

---

## ⚡ Connecting to Auto-Browser

Once pushed to Hugging Face, add your repo to [.env](file:///home/sudo69/Projects/auto-browser/.env):

```env
HF_MODEL_ID=your-username/auto-browser-devops-agent
HF_TOKEN=hf_your_write_token
```

Auto-Browser will automatically query your fine-tuned model via Hugging Face's free Serverless Inference API for all job applications!
