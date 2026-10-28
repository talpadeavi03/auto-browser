#!/usr/bin/env python3
"""
Auto-Browser ML Model Fine-Tuning Pipeline for Google Colab (Free T4 GPU).
Trains Qwen-2.5-1.5B-Instruct using LoRA / PEFT on your application interactions dataset.
Saves the resulting model to Hugging Face Hub (Free Private/Public Model Registry).
"""

import os
import sys
import json
import shutil
from pathlib import Path

def train():
    print("=" * 70)
    print("🤖 Auto-Browser Fine-Tuning Pipeline (Hugging Face Hub 🤗)")
    print("=" * 70)

    # 1. Install ML & Hugging Face dependencies
    try:
        import torch
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
            TrainingArguments
        )
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from datasets import Dataset
        from huggingface_hub import login, whoami
    except ImportError:
        print("📦 Installing required ML packages...")
        os.system("pip install -q \"transformers>=4.40.0\" \"peft>=0.10.0\" \"trl>=0.8.0\" bitsandbytes accelerate datasets huggingface_hub")
        import torch
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
            TrainingArguments
        )
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from datasets import Dataset
        from huggingface_hub import login, whoami

    # 2. Check GPU
    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)
        vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        print(f"✓ GPU Detected: {gpu_name} ({vram_gb:.2f} GB VRAM)")
    else:
        print("⚠️ Warning: No GPU detected. In Colab, select: Runtime -> Change runtime type -> T4 GPU.")

    # 3. Locate Training Dataset
    dataset_paths = [
        Path("data/training_dataset.jsonl"),
        Path("/content/auto-browser/data/training_dataset.jsonl"),
        Path("/content/training_dataset.jsonl"),
        Path("training_dataset.jsonl"),
        Path("../data/training_dataset.jsonl")
    ]
    data_file = next((p for p in dataset_paths if p.exists()), None)
    if not data_file:
        print("❌ Error: training_dataset.jsonl not found!")
        print("Upload data/training_dataset.jsonl directly to Colab.")
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
            f"<|im_start|>system\n{r['instruction']}<|im_end|>\\n"
            f"<|im_start|>user\n{r['input']}<|im_end|>\\n"
            f"<|im_start|>assistant\n{r['output']}<|im_end|>"
        )
        formatted_data.append({"text": text})

    dataset = Dataset.from_list(formatted_data)
    print("✓ Sample ChatML Prompt Preview:\n" + "-" * 40)
    print(dataset[0]["text"][:250] + "...\n" + "-" * 40)

    # 5. Load Model & Tokenizer (Qwen-2.5-1.5B-Instruct in 4-bit NF4)
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

    # 6. Configure LoRA
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

    # 7. Configure SFT Trainer
    output_dir = "./auto_browser_qwen_lora"
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
            report_to="none"
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
            report_to="none"
        )
        trainer = SFTTrainer(
            model=model,
            train_dataset=dataset,
            dataset_text_field="text",
            max_seq_length=512,
            tokenizer=tokenizer,
            args=training_args
        )

    # 8. Train the Model
    print("\n🚀 Starting LoRA Fine-Tuning on Colab GPU (~3-5 minutes)...")
    trainer.train()
    print("\n🎉 Training completed successfully!")

    # 9. Save LoRA Adapter Locally
    final_model_dir = "./final_lora_model"
    model.save_pretrained(final_model_dir)
    tokenizer.save_pretrained(final_model_dir)
    zip_path = shutil.make_archive("auto_browser_lora_model", "zip", final_model_dir)
    print(f"✓ Model saved locally to: {final_model_dir}")

    # 10. Run Live Validation Inference
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

    # 11. Push to Hugging Face Hub (if token present)
    hf_token = os.environ.get("HF_TOKEN")
    if hf_token:
        try:
            login(token=hf_token)
            username = whoami()["name"]
            repo_id = f"{username}/auto-browser-devops-agent"
            print(f"Pushing to Hugging Face Hub: {repo_id}...")
            model.push_to_hub(repo_id, private=True)
            tokenizer.push_to_hub(repo_id, private=True)
            print(f"✓ Model successfully pushed to: https://huggingface.co/{repo_id}")
        except Exception as e:
            print(f"Hugging Face push note: {e}")
    else:
        print("ℹ️ Set HF_TOKEN environment variable to auto-push to Hugging Face Hub.")

if __name__ == "__main__":
    train()
