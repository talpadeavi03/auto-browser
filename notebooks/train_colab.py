#!/usr/bin/env python3
"""
Auto-Browser ML Model Fine-Tuning Pipeline for Google Colab (Free T4 GPU).
Trains Qwen-2.5-1.5B-Instruct using LoRA / PEFT on your application interactions dataset.
Saves the resulting model for FREE to Hugging Face Hub or Google Drive.
"""

import os
import sys
import json
import torch
from pathlib import Path

def train():
    print("=" * 60)
    print("🤖 Auto-Browser Model Fine-Tuner (Google Colab T4 GPU)")
    print("=" * 60)

    # 1. Check GPU
    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)
        print(f"✓ Using GPU: {gpu_name}")
    else:
        print("⚠️ Warning: No GPU detected. Training will run on CPU (slower).")

    # 2. Install dependencies if running on Colab
    try:
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
            TrainingArguments
        )
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from trl import SFTTrainer
        from datasets import Dataset
    except ImportError:
        print("Installing required ML packages...")
        os.system("pip install -q transformers peft trl bitsandbytes accelerate datasets")
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
            TrainingArguments
        )
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from trl import SFTTrainer
        from datasets import Dataset

    # 3. Locate Dataset
    dataset_paths = [
        Path("data/training_dataset.jsonl"),
        Path("/content/auto-browser/data/training_dataset.jsonl"),
        Path("/content/training_dataset.jsonl"),
        Path("../data/training_dataset.jsonl")
    ]
    data_file = next((p for p in dataset_paths if p.exists()), None)
    if not data_file:
        print("❌ Error: training_dataset.jsonl not found!")
        print("Run 'python main.py export-dataset' in auto-browser repo and upload it here.")
        sys.exit(1)

    print(f"✓ Loading dataset from: {data_file}")
    records = []
    with open(data_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))

    print(f"✓ Loaded {len(records)} application Q&A interaction pairs.")

    # 4. Format Dataset into ChatML / Qwen format
    formatted_data = []
    for r in records:
        text = (
            f"<|im_start|>system\n{r['instruction']}<|im_end|>\n"
            f"<|im_start|>user\n{r['input']}<|im_end|>\n"
            f"<|im_start|>assistant\n{r['output']}<|im_end|>"
        )
        formatted_data.append({"text": text})

    dataset = Dataset.from_list(formatted_data)

    # 5. Load Model & Tokenizer (Qwen-2.5-1.5B-Instruct in 4-bit)
    model_id = "Qwen/Qwen2.5-1.5B-Instruct"
    print(f"✓ Loading base model '{model_id}' with 4-bit quantization...")

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

    # 6. Configure LoRA (Low-Rank Adaptation)
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

    # 7. Training Arguments
    output_dir = "./auto_browser_qwen_lora"
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
        report_to="none"
    )

    # 8. Train with SFTTrainer
    print("\n🚀 Starting SFT Training on Colab GPU...")
    trainer = SFTTrainer(
        model=model,
        train_dataset=dataset,
        peft_config=peft_config,
        dataset_text_field="text",
        max_seq_length=512,
        tokenizer=tokenizer,
        args=training_args
    )

    trainer.train()
    print("\n🎉 Training completed successfully!")

    # 9. Save LoRA Adapter Locally
    final_model_dir = "./final_lora_model"
    model.save_pretrained(final_model_dir)
    tokenizer.save_pretrained(final_model_dir)
    print(f"✓ LoRA Adapter saved locally to: {final_model_dir}")

    # 10. Test Inference live
    print("\n" + "=" * 50)
    print("🧪 Running Live Test Inference with Trained Model:")
    print("=" * 50)
    test_question = "Recruiter Question: 'Which AWS certification do you have?'\nField Type: text"
    prompt = (
        f"<|im_start|>system\n{records[0]['instruction']}<|im_end|>\n"
        f"<|im_start|>user\n{test_question}<|im_end|>\n"
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
    print(f"Question: Which AWS certification do you have?")
    print(f"Generated Answer: {generated.strip()}")

    # 11. Free Save / Upload Options
    print("\n" + "=" * 50)
    print("☁️ FREE MODEL SAVING OPTIONS:")
    print("=" * 50)
    print("Option 1: Push to Hugging Face Hub (FREE Private/Public Repo):")
    print("  from huggingface_hub import login")
    print("  login('your_hf_token')")
    print("  model.push_to_hub('your_username/auto-browser-devops-agent')")
    print("  tokenizer.push_to_hub('your_username/auto-browser-devops-agent')")
    print("\nOption 2: Save to Google Drive (FREE):")
    print("  from google.colab import drive")
    print("  drive.mount('/content/drive')")
    print("  !cp -r ./final_lora_model /content/drive/MyDrive/auto_browser_model")
    print("=" * 50)

if __name__ == "__main__":
    train()
