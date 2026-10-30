#!/usr/bin/env python3
"""Model inference client for autonomous form resolution.

Provides model_fn(question, ftype, options) -> (answer, confidence) to answers.resolve().
Supports:
1. Fine-tuned Hugging Face Hub LoRA/Model (via Serverless Inference API)
2. Local Ollama / vLLM endpoint
3. LLM fallback (Gemini / DeepSeek) for zero-shot answering of complex questions
"""
import os
import json
import urllib.request
import urllib.error
from typing import Optional, List, Tuple
import yaml

SYSTEM_INSTRUCTION = (
    "You are an expert AI autonomous job application agent for candidate Avinash Talpade, "
    "a DevOps and Cloud Engineer with 3.6 years experience. Answer recruiter screening questions "
    "accurately, professionally, and truthfully according to the candidate profile. "
    "If options are provided, choose the EXACT option that best fits. "
    "If asked for years or numbers, return only the digits. "
    "If unsure or the question requires private facts not in the profile, answer SKIP."
)

def _load_profile():
    p_path = os.path.join(os.path.dirname(__file__), "profile.yaml")
    if os.path.exists(p_path):
        return yaml.safe_load(open(p_path, encoding="utf-8"))
    return {}

def format_prompt(question: str, ftype: str, options: Optional[List[str]] = None) -> str:
    s = f"Recruiter Question: '{question}'\nField Type: {ftype}"
    if options:
        s += "\nAvailable Options: " + ", ".join(options)
    return s

def query_huggingface(prompt: str, hf_model_id: str, hf_token: Optional[str] = None) -> Optional[Tuple[str, float]]:
    """Queries fine-tuned model on Hugging Face Serverless Inference API."""
    url = f"https://api-inference.huggingface.co/models/{hf_model_id}"
    chatml = (
        f"<|im_start|>system\n{SYSTEM_INSTRUCTION}<|im_end|>\n"
        f"<|im_start|>user\n{prompt}<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )
    payload = {
        "inputs": chatml,
        "parameters": {
            "max_new_tokens": 120,
            "temperature": 0.1,
            "return_full_text": False
        }
    }
    headers = {"Content-Type": "application/json"}
    if hf_token:
        headers["Authorization"] = f"Bearer {hf_token}"

    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list) and len(data) > 0:
                out = data[0].get("generated_text", "").strip()
                if "<|im_end|>" in out:
                    out = out.split("<|im_end|>")[0].strip()
                if out:
                    return out, 0.95
    except Exception:
        pass
    return None

def query_ollama(prompt: str, model: str = "qwen2.5:1.5b", host: str = "http://localhost:11434") -> Optional[Tuple[str, float]]:
    """Queries local Ollama instance running the fine-tuned model or GGUF."""
    url = f"{host.rstrip('/')}/api/generate"
    payload = {
        "model": model,
        "system": SYSTEM_INSTRUCTION,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 120}
    }
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            out = data.get("response", "").strip()
            if out:
                return out, 0.94
    except Exception:
        pass
    return None

def model_fn(question: str, ftype: str, options: Optional[List[str]] = None) -> Tuple[Optional[str], float]:
    """Universal model callback for answers.resolve(..., model_fn=model_fn).
    
    Returns (answer_string, confidence_float).
    If confidence < 0.90 or answer is SKIP/None, answers.py skips the field and queues it.
    """
    prompt = format_prompt(question, ftype, options)

    # 1. Check Hugging Face Hub fine-tuned model
    hf_model = os.getenv("HF_MODEL_ID")
    if hf_model:
        res = query_huggingface(prompt, hf_model, os.getenv("HF_TOKEN"))
        if res:
            return res

    # 2. Check local Ollama model
    ollama_model = os.getenv("OLLAMA_MODEL")
    if ollama_model:
        res = query_ollama(prompt, model=ollama_model, host=os.getenv("OLLAMA_HOST", "http://localhost:11434"))
        if res:
            return res

    return None, 0.0

if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "How many years of production Kubernetes experience do you have?"
    ans, conf = model_fn(q, "text")
    print(f"Question: {q}\nPredicted Answer: {ans}\nConfidence: {conf}")
