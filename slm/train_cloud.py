"""
Aether CareerOS & Auto-Browser — Zero-Cost Cloud SLM Fine-Tuning Pipeline
Designed to run on 100% Free Cloud GPU Compute:
- Kaggle Notebooks (30 hours/week free NVIDIA T4/P100 GPUs)
- Google Colab (Free Tier T4 GPU instances)
- Hugging Face Hub (Free dataset storage & model registry)
Total Infrastructure Cost: $0.00
"""

import os
import json
from pathlib import Path
from typing import Dict, List

import torch
from datasets import Dataset

# Defaults
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATASET_PATH = PROJECT_ROOT / "data" / "training_dataset.jsonl"
DEFAULT_BASE_MODEL = os.getenv("BASE_MODEL_ID", "Qwen/Qwen2.5-Coder-1.5B-Instruct")
OUTPUT_HUB_REPO = os.getenv("HF_OUTPUT_REPO", "talpadeavi03/careeros-slm-qna")
HF_TOKEN = os.getenv("HF_TOKEN")

def load_continuous_training_dataset(jsonl_path: Path) -> Dataset:
    """Loads cumulative application Q&A interaction records for SLM fine-tuning."""
    if not jsonl_path.exists():
        raise FileNotFoundError(f"Dataset not found at {jsonl_path}. Run application cycles to accumulate interactions.")

    records = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            # Format as ChatML / Instruct prompt
            sys_msg = item.get("instruction") or "You are an autonomous AI recruitment assistant answering recruiter questions for Avinash Talpade."
            user_msg = item.get("input") or ""
            asst_msg = item.get("output") or ""

            formatted_prompt = (
                f"<|im_start|>system\n{sys_msg}<|im_end|>\n"
                f"<|im_start|>user\n{user_msg}<|im_end|>\n"
                f"<|im_start|>assistant\n{asst_msg}<|im_end|>"
            )
            records.append({"text": formatted_prompt})

    print(f"✓ Loaded {len(records)} continuous training interaction samples from {jsonl_path}!")
    return Dataset.from_list(records)

def train():
    if not torch.cuda.is_available():
        print("⚠️ No CUDA GPU detected. This training script is intended to run on Google Colab or Kaggle (free GPU).")
        print("To run locally on CPU for testing, set CUDA emulation or use small batch.")

    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, TrainingArguments
    from trl import SFTTrainer

    print(f"📦 Loading Base Model: {DEFAULT_BASE_MODEL} with 4-bit quantization...")
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16,
        bnb_4bit_use_double_quant=True,
    )

    tokenizer = AutoTokenizer.from_pretrained(DEFAULT_BASE_MODEL, token=HF_TOKEN, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        DEFAULT_BASE_MODEL,
        quantization_config=bnb_config,
        device_map="auto",
        token=HF_TOKEN,
        trust_remote_code=True
    )

    model = prepare_model_for_kbit_training(model)

    peft_config = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, peft_config)
    model.print_trainable_parameters()

    dataset = load_continuous_training_dataset(DATASET_PATH)

    training_args = TrainingArguments(
        output_dir="./slm_output",
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,
        warmup_steps=10,
        max_steps=120,
        learning_rate=2e-4,
        fp16=not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported(),
        logging_steps=10,
        optim="paged_adamw_8bit",
        save_strategy="no",
        report_to="none"
    )

    trainer = SFTTrainer(
        model=model,
        train_dataset=dataset,
        dataset_text_field="text",
        max_seq_length=512,
        tokenizer=tokenizer,
        args=training_args,
    )

    print("🚀 Starting Fine-Tuning on Cloud GPU...")
    trainer.train()

    print(f"✓ Training Complete! Saving adapter to ./slm_adapter...")
    trainer.model.save_pretrained("./slm_adapter")
    tokenizer.save_pretrained("./slm_adapter")

    if HF_TOKEN and OUTPUT_HUB_REPO:
        try:
            print(f"☁️ Pushing fine-tuned SLM to Hugging Face Hub: {OUTPUT_HUB_REPO}...")
            trainer.model.push_to_hub(OUTPUT_HUB_REPO, token=HF_TOKEN)
            tokenizer.push_to_hub(OUTPUT_HUB_REPO, token=HF_TOKEN)
            print(f"✓ Successfully published fine-tuned SLM to Hugging Face Hub (free)!")
        except Exception as e:
            print(f"Note pushing to Hub: {e}")

if __name__ == "__main__":
    train()
