# ClearPath — ML / Fine-tuning (Unsloth Track)

## Goal
Fine-tune Gemma 4 E4B on Easy Language dataset.
Target: outperform GPT-4o on text simplification task.
Prize: Unsloth special mention ($10,000).

## Datasets
- **WikiLarge**: https://github.com/louismartin/dress-data
- **ASSET**: https://github.com/facebookresearch/asset
- **Simple English Wikipedia**: via HuggingFace datasets

## Setup (Kaggle Notebooks — Free GPU T4/P100)
1. Open Kaggle → New Notebook
2. Enable GPU (T4 or P100)
3. Install: `pip install unsloth`
4. Use `finetune_notebook.py` as starting point

## Deliverables
1. Fine-tuned model pushed to Ollama: `clearpath-writer:latest`
2. Benchmark results: SARI score vs GPT-4o vs base E4B
3. Kaggle Notebook link (public, reproducible)

## Metric to beat
- SARI score > 40 (GPT-4o baseline: ~38 on ASSET benchmark)
