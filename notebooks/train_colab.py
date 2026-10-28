#!/usr/bin/env python3
"""
Auto-Browser ML Model Fine-Tuning Pipeline for Google Colab (Free T4 GPU).
Trains Qwen-2.5-1.5B-Instruct using LoRA / PEFT on your application interactions dataset.
Saves the resulting model to MLflow Model Registry, Hugging Face Hub, Google Drive, or Direct Zip Download.
Automatically updates model release documentation on GitHub.
"""

import os
import sys
import json
import shutil
from datetime import datetime
from pathlib import Path

def train():
    print("=" * 70)
    print("🤖 Auto-Browser Model Fine-Tuning Pipeline (GitHub ↔ Colab ↔ MLflow)")
    print("=" * 70)

    # 1. Install ML & Tracking dependencies
    try:
        import torch
        import mlflow
        import mlflow.transformers
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
            TrainingArguments
        )
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from datasets import Dataset
    except ImportError:
        print("📦 Installing required ML & tracking packages...")
        os.system("pip install -q \"transformers>=4.40.0\" \"peft>=0.10.0\" \"trl>=0.8.0\" bitsandbytes accelerate datasets dagshub mlflow huggingface_hub")
        import torch
        import mlflow
        import mlflow.transformers
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
            TrainingArguments
        )
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from datasets import Dataset

    # 2. Configure Free Remote MLflow Tracking Server via DagsHub
    mlflow_active = False
    try:
        import dagshub
        print("🔗 Initializing Remote MLflow Server on DagsHub...")
        # Automatically connects your Colab session to https://dagshub.com/talpadeavi03/auto-browser.mlflow
        dagshub.init(repo_owner="talpadeavi03", repo_name="auto-browser", mlflow=True)
        mlflow.set_experiment("auto-browser-devops-sft")
        mlflow_active = True
        print("✓ Connected to Remote MLflow Server: https://dagshub.com/talpadeavi03/auto-browser.mlflow")
    except Exception as e:
        print(f"ℹ️ Local MLflow fallback (DagsHub note: {e})")
        try:
            mlflow.set_experiment("auto-browser-devops-sft")
            mlflow_active = True
        except Exception:
            mlflow_active = False

    # 3. Check GPU
    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)
        vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        print(f"✓ GPU Detected: {gpu_name} ({vram_gb:.2f} GB VRAM)")
    else:
        print("⚠️ Warning: No GPU detected. In Colab, select: Runtime -> Change runtime type -> T4 GPU.")

    # 4. Locate Training Dataset
    dataset_paths = [
        Path("data/training_dataset.jsonl"),
        Path("/content/auto-browser/data/training_dataset.jsonl"),
        Path("/content/training_dataset.jsonl"),
        Path("../data/training_dataset.jsonl")
    ]
    data_file = next((p for p in dataset_paths if p.exists()), None)
    if not data_file:
        print("❌ Error: training_dataset.jsonl not found!")
        print("Tip: Run !git clone https://github.com/talpadeavi03/auto-browser.git in Colab.")
        sys.exit(1)

    print(f"✓ Loading dataset from: {data_file}")
    records = []
    with open(data_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))

    print(f"✓ Loaded {len(records)} application Q&A interaction pairs.")

    # 5. Format Dataset into ChatML / Qwen format
    formatted_data = []
    for r in records:
        text = (
            f"<|im_start|>system\n{r['instruction']}<|im_end|>\n"
            f"<|im_start|>user\n{r['input']}<|im_end|>\n"
            f"<|im_start|>assistant\n{r['output']}<|im_end|>"
        )
        formatted_data.append({"text": text})

    dataset = Dataset.from_list(formatted_data)
    print("✓ Sample ChatML Prompt Preview:\n" + "-" * 40)
    print(dataset[0]["text"][:250] + "...\n" + "-" * 40)

    # 6. Load Model & Tokenizer (Qwen-2.5-1.5B-Instruct in 4-bit NF4)
    model_id = "Qwen/Qwen2.5-1.5B-Instruct"
    print(f"✓ Loading base model '{model_id}' with 4-bit NF4 Quantization...")

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True
    )

    tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True
    )
    model = prepare_model_for_kbit_training(model)

    # 7. Configure LoRA (Low-Rank Adaptation)
    peft_config = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
    )
    model = get_peft_model(model, peft_config)
    model.print_trainable_parameters()

    # 8. Configure SFT Trainer with MLflow Logging
    output_dir = "./auto_browser_qwen_lora"
    report_targets = ["mlflow"] if mlflow_active else "none"

    try:
        from trl import SFTTrainer, SFTConfig
        sft_config = SFTConfig(
            output_dir=output_dir,
            num_train_epochs=5,
            per_device_train_batch_size=2,
            gradient_accumulation_steps=4,
            learning_rate=2e-4,
            fp16=torch.cuda.is_available(),
            logging_steps=5,
            save_strategy="epoch",
            optim="paged_adamw_8bit",
            dataset_text_field="text",
            max_seq_length=512,
            report_to=report_targets
        )
        trainer = SFTTrainer(
            model=model,
            train_dataset=dataset,
            processing_class=tokenizer,
            args=sft_config
        )
    except (ImportError, TypeError):
        from trl import SFTTrainer
        training_args = TrainingArguments(
            output_dir=output_dir,
            num_train_epochs=5,
            per_device_train_batch_size=2,
            gradient_accumulation_steps=4,
            learning_rate=2e-4,
            fp16=torch.cuda.is_available(),
            logging_steps=5,
            save_strategy="epoch",
            optim="paged_adamw_8bit",
            report_to=report_targets
        )
        trainer = SFTTrainer(
            model=model,
            train_dataset=dataset,
            dataset_text_field="text",
            max_seq_length=512,
            tokenizer=tokenizer,
            args=training_args
        )

    # 9. Train the Model
    print("\n🚀 Starting LoRA Fine-Tuning on Colab GPU (~3-5 minutes)...")
    train_result = trainer.train()
    print("\n🎉 Training completed successfully!")

    # 10. Save LoRA Adapter Locally & Create Zip
    final_model_dir = "./final_lora_model"
    model.save_pretrained(final_model_dir)
    tokenizer.save_pretrained(final_model_dir)
    zip_path = shutil.make_archive("auto_browser_lora_model", "zip", final_model_dir)
    print(f"✓ Model packaged locally into archive: {zip_path}")

    # 11. Register Model in MLflow Model Registry
    run_id = "local-run"
    if mlflow_active:
        try:
            with mlflow.start_run(run_name=f"qwen2.5-lora-{datetime.utcnow().strftime('%Y%m%d-%H%M')}") as run:
                mlflow.log_params({
                    "base_model": model_id,
                    "lora_r": peft_config.r,
                    "lora_alpha": peft_config.lora_alpha,
                    "dataset_samples": len(records),
                    "epochs": 5,
                    "learning_rate": 2e-4,
                })
                if hasattr(train_result, "training_loss"):
                    mlflow.log_metric("final_train_loss", train_result.training_loss)

                print("📦 Registering model in MLflow Model Registry...")
                mlflow.transformers.log_model(
                    transformers_model={"model": model, "tokenizer": tokenizer},
                    artifact_path="devops_agent_model",
                    registered_model_name="AutoBrowser-DevOps-Agent"
                )
                run_id = run.info.run_id
                print(f"✓ Model registered in MLflow! Run ID: {run_id}")
                print(f"✓ Model URI: models:/AutoBrowser-DevOps-Agent/latest")
        except Exception as e:
            print(f"MLflow model logging note: {e}")

    # 12. Run Live Validation Inference
    print("\n" + "=" * 55)
    print("🧪 Running Live Test Inference with Trained Model:")
    print("=" * 55)
    test_questions = [
        "Which AWS certification do you have?",
        "How many years of experience do you have with Kubernetes?",
        "What is your notice period in days?",
        "Briefly summarize your experience with Kubernetes:"
    ]

    for q in test_questions:
        prompt = (
            f"<|im_start|>system\n{records[0]['instruction']}<|im_end|>\n"
            f"<|im_start|>user\nRecruiter Question: '{q}'\nField Type: text<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=60,
                pad_token_id=tokenizer.eos_token_id,
                do_sample=False
            )
        generated = tokenizer.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        print(f"Q: {q}")
        print(f"A: {generated.strip()}\n")

    # 13. Auto-Update GitHub Release Metadata
    github_token = os.environ.get("GITHUB_TOKEN")
    report_content = f"""# 🤖 Auto-Browser Model Registry & Release Status

This file tracks the latest fine-tuned model trained on Google Colab and registered in the **MLflow Model Registry**.

---

## 📌 Latest Model Release
- **Updated**: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}
- **Model Name**: `AutoBrowser-DevOps-Agent`
- **Base Architecture**: `Qwen/Qwen2.5-1.5B-Instruct`
- **MLflow Run ID**: `{run_id}`
- **MLflow Model URI**: `models:/AutoBrowser-DevOps-Agent/latest`
- **Dataset Size**: {len(records)} interaction pairs
- **Remote MLflow Server**: [DagsHub MLflow Dashboard](https://dagshub.com/talpadeavi03/auto-browser.mlflow)
- **Status**: Production Ready

---

## ⚡ How to Load in Auto-Browser

```python
import mlflow.transformers
model = mlflow.transformers.load_model("models:/AutoBrowser-DevOps-Agent/latest")
```
"""
    doc_path = Path("docs/LATEST_MODEL.md")
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(report_content, encoding="utf-8")
    print(f"✓ Updated model card at {doc_path}")

    if github_token:
        print("🚀 Syncing model release metadata to GitHub master branch...")
        os.system('git config --global user.name "Auto-Browser ML Trainer (Colab)"')
        os.system('git config --global user.email "bot@auto-browser.ai"')
        os.system('git add docs/LATEST_MODEL.md')
        os.system('git commit -m "model: update MLflow model release [skip ci]"')
        os.system(f'git push https://x-access-token:{github_token}@github.com/talpadeavi03/auto-browser.git master')
        print("✓ Successfully updated GitHub with latest MLflow model release!")
    else:
        print("ℹ️ Set GITHUB_TOKEN environment variable in Colab to auto-push updates back to GitHub.")

    print("\n" + "=" * 55)
    print("☁️ ALL FREE DEPLOYMENT OPTIONS:")
    print("=" * 55)
    print("1. MLflow Model Registry: models:/AutoBrowser-DevOps-Agent/latest")
    print("2. 1-Click Browser Download: from google.colab import files; files.download('auto_browser_lora_model.zip')")
    print("3. Hugging Face Hub: model.push_to_hub('your_username/auto-browser-devops-agent')")
    print("=" * 55)

if __name__ == "__main__":
    train()
