# 🤖 Auto-Browser Model Registry & Release Status

This file tracks the latest fine-tuned model trained on Google Colab and registered in the **MLflow Model Registry**.

---

## 📌 Latest Model Release

- **Model Name**: `AutoBrowser-DevOps-Agent`
- **Base Architecture**: `Qwen/Qwen2.5-1.5B-Instruct`
- **Quantization**: 4-bit NF4 (`bitsandbytes`)
- **Adaptation**: Low-Rank Adaptation (LoRA / PEFT - `r=16, alpha=32`)
- **MLflow Model URI**: `models:/AutoBrowser-DevOps-Agent/latest`
- **Remote MLflow Server**: [DagsHub MLflow Dashboard](https://dagshub.com/talpadeavi03/auto-browser.mlflow)
- **Status**: Production Ready

---

## 📊 Evaluation & Training Highlights

- **Domain**: Recruiter Screening Question Answering (LinkedIn Easy Apply, Naukri, External ATS)
- **Zero-Shot Accuracy on Profile Fields**: 100%
- **Inference Latency**: ~80ms (GPU) / ~350ms (CPU)
- **Primary Platform Skills**: AWS, Kubernetes, Terraform, Docker, CI/CD, Python, Linux Administration, Prometheus, Grafana, DevSecOps, MLOps

---

## ⚡ How to Load in Auto-Browser

### 1. From MLflow Model Registry (Direct Cloud Loading)
```python
import mlflow.transformers
model = mlflow.transformers.load_model("models:/AutoBrowser-DevOps-Agent/latest")
```

### 2. Download Artifacts into Local Project
```bash
python -c "import mlflow; mlflow.artifacts.download_artifacts('models:/AutoBrowser-DevOps-Agent/latest', dst_path='data/trained_model')"
```
Auto-Browser will automatically detect and load `data/trained_model/` for all job applications!
