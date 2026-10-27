# 🤖 Auto-Browser: Google Colab Training Pipeline (Option C)

This directory contains the complete end-to-end training pipeline to fine-tune your own specialized AI agent (`Qwen-2.5-1.5B-Instruct`) using **Free Google Colab T4 GPU**, and save the trained model for **FREE** to **Hugging Face Hub** or **Google Drive**.

---

## 🚀 Quick Start (In 3 Steps)

### Step 1: Export Your Application Interactions Dataset
Run the auto-browser dataset exporter from your repository:
```bash
python main.py export-dataset
```
This generates `data/training_dataset.jsonl` containing all recorded recruiter screening questions, form fields, and answers in ChatML/Alpaca instruction format.

---

### Step 2: Open in Google Colab
1. Go to [Google Colab](https://colab.research.google.com/).
2. Click **File -> Upload notebook** and select `notebooks/train_colab.ipynb`.
3. Change runtime type to **T4 GPU** (Runtime -> Change runtime type -> T4 GPU - Free).
4. Run all cells (`Ctrl + F9`). Training takes **~3-5 minutes**!

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
