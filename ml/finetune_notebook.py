# ClearPath — Unsloth Fine-tuning Script
# Run on Kaggle Notebooks with GPU enabled
# pip install unsloth datasets evaluate

from unsloth import FastLanguageModel
from datasets import load_dataset
import torch

MAX_SEQ_LENGTH = 2048
MODEL_NAME = "unsloth/gemma-4-e4b-it"  # adjust to correct Unsloth model ID

# 1. Load model
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=MODEL_NAME,
    max_seq_length=MAX_SEQ_LENGTH,
    dtype=None,
    load_in_4bit=True,
)

# 2. Apply LoRA
model = FastLanguageModel.get_peft_model(
    model,
    r=16,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    lora_alpha=16,
    lora_dropout=0,
    bias="none",
    use_gradient_checkpointing="unsloth",
    random_state=42,
)

# 3. Load ASSET dataset
dataset = load_dataset("facebook/asset", "simplification")

SYSTEM_PROMPT = """You are an Easy Language writer.
Rewrite the text to be simple and clear.
Rules: max 10 words per sentence, simple vocabulary, active voice only."""

def format_example(example):
    original = example["original"]
    simple = example["simplifications"][0]  # take first simplification
    return {
        "text": f"<start_of_turn>system\n{SYSTEM_PROMPT}<end_of_turn>\n"
                f"<start_of_turn>user\nSimplify: {original}<end_of_turn>\n"
                f"<start_of_turn>model\n{simple}<end_of_turn>"
    }

train_data = dataset["validation"].map(format_example)

# 4. Train
from trl import SFTTrainer
from transformers import TrainingArguments

trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=train_data,
    dataset_text_field="text",
    max_seq_length=MAX_SEQ_LENGTH,
    args=TrainingArguments(
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,
        warmup_steps=10,
        num_train_epochs=3,
        learning_rate=2e-4,
        fp16=not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported(),
        logging_steps=10,
        output_dir="clearpath-writer",
        optim="adamw_8bit",
    ),
)

trainer.train()

# 5. Save and push to Ollama
model.save_pretrained("clearpath-writer")
tokenizer.save_pretrained("clearpath-writer")
print("Model saved! Next: convert to GGUF and create Ollama model")
print("Commands:")
print("  python -m unsloth.convert_hf_to_gguf clearpath-writer clearpath-writer.gguf")
print("  ollama create clearpath-writer -f Modelfile")
