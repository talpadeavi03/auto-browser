# 🤖 Auto-Browser: Google Colab Training Pipeline (Option C)

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/talpadeavi03/auto-browser/blob/master/notebooks/train_colab.ipynb)

This directory contains the complete end-to-end training pipeline to fine-tune your own specialized AI agent (`Qwen-2.5-1.5B-Instruct`) using **Free Google Colab T4 GPU**, and save the trained model for **FREE** to **Hugging Face Hub** or **Google Drive**.

---

## 🔄 The Autonomous GitHub ↔ Colab Data Loop

```
[24/7 Cloud Bot on GitHub Actions]
              │
              ▼ (Auto-applies to LinkedIn, Naukri, Keka)
[Extracts & Saves interaction Q&A to data/jobs.db]
              │
              ▼ (Auto-exports to data/training_dataset.jsonl)
[Pushes updated dataset back to GitHub master branch [skip ci]]
              │
              ▼ (Click "Open in Colab" Badge below)
[Google Colab pulls latest dataset directly from GitHub repo]
              │
              ▼ (Fine-tunes Qwen-2.5-1.5B on Free T4 GPU in 3 mins)
[Auto-pushes fine-tuned model to Hugging Face Hub (FREE)]
```

---

## 🚀 Quick Start (In 1 Click)

1. Click the **[Open in Colab](https://colab.research.google.com/github/talpadeavi03/auto-browser/blob/master/notebooks/train_colab.ipynb)** badge above.
2. Select **Runtime -> Change runtime type -> T4 GPU** (Free).
3. Click **Run All** (`Ctrl + F9`).
   * Colab automatically clones the repo and pulls the latest `data/training_dataset.jsonl` from GitHub!
   * Fine-tunes the model in **3 to 5 minutes**.
   * Pushes the trained adapter to your free **Hugging Face Hub** repository!

---

### Step 3: Free Model Saving & Deployment

#### Free Option 1: Hugging Face Hub (Private or Public Model Registry)
Create a free account on [Hugging Face](https://huggingface.co/) and generate a free Write Token.
Inside Colab:
```python
from huggingface_hub import login
login("hf_your_token_here")

model.push_to_hub("your-username/auto-browser-devops-agent")
tokenizer.push_to_hub("your-username/auto-browser-devops-agent")
```
* **Cost**: $0.00 / month forever.
* **Access**: Can be queried via free Hugging Face Serverless Inference API or loaded locally.

#### Free Option 2: Google Drive
```python
from google.colab import drive
drive.mount('/content/drive')
model.save_pretrained('/content/drive/MyDrive/auto_browser_qwen_lora')
```

#### Free Option 3: Export to GGUF (Run locally on ordinary CPU via Ollama)
```bash
ollama create devops-agent -f Modelfile
ollama run devops-agent
```
