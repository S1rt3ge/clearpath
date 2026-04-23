# ClearPath 🧠

**Cognitive Accessibility Agent for Education — powered by Gemma 4**

> Gemma 4 Good Hackathon | Kaggle × Google DeepMind | Prize Pool: $200,000

---

## What it does

ClearPath is a Chrome Extension + AI backend that transforms any educational website
into an accessible experience for users with ADHD, dyslexia, or language barriers.

Unlike simple CSS tools, ClearPath **acts** — it understands the page context
(article? test? form?) and responds intelligently:

- 📖 **Article on Wikipedia** → Builds personalized summary, simplifies text to your reading level
- 📝 **Test on Moodle** → Creates preparation steps, shows your past error patterns
- 📋 **Complex form** → Converts to step-by-step wizard with A2-level explanations

## Architecture

```
Chrome Extension → FastAPI Backend → LangGraph Multi-Agent Graph
                                          ├── Analyzer (Gemma 4 26B, Cloud, Multimodal)
                                          ├── Planner  (Gemma 4 E2B, Local, Private)
                                          ├── Writer   (Gemma 4 E2B Fine-tuned, Local)
                                          └── Action   (Function Calling → DOM transforms)
                                    → PostgreSQL (Multi-tenant cognitive profiles)
```

**Privacy-first**: Cognitive profiles never leave your machine. Only page screenshots go to cloud for multimodal analysis.

## Quick Start

```bash
# 1. Clone
git clone https://github.com/S1rt3ge/clearpath.git
cd clearpath

# 2. Setup env
cp .env.example .env
# Edit .env — add GOOGLE_AI_STUDIO_API_KEY

# 3. Pull Gemma 4 locally via Ollama
ollama pull gemma4:e2b-it-q4_K_M

# 4. Start backend + database
docker-compose up -d

# 5. Load Extension in Chrome
# Settings → Extensions → Developer mode → Load unpacked → select /extension

# 6. Open the popup, select your profile, activate!
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| Agents | LangGraph Multi-Agent Graph |
| Local Model | Gemma 4 E2B via Ollama |
| Cloud Model | Gemma 4 26B via Google AI Studio |
| Fine-tuning | Unsloth on Kaggle Notebooks |
| Backend | FastAPI + WebSockets |
| Database | PostgreSQL (Multi-tenant) |
| Extension | Chrome Manifest V3 |
| Deploy | Docker Compose |

## How It Works

1. **Extension captures** the page URL, DOM text, and optional screenshot
2. **Analyzer** (Gemma 4 26B, multimodal) classifies the page — article, test, form, etc.
3. **Planner** (Gemma 4 E2B, local) decides which transformations to apply based on the user's cognitive profile
4. **Writer** (Gemma 4 E2B fine-tuned, local) simplifies text to the user's reading level in parallel with the Planner
5. **Action** generates DOM transformation commands sent back to the extension
6. **Extension** injects the simplified overlay, hides distractions, applies fonts

Everything runs in a LangGraph `StateGraph` — cold request ~40s, cache hit ~0.3s.

## Performance

| Metric | Value |
|--------|-------|
| Cold request (no cache) | ~40s |
| Cache hit | ~0.3s |
| Cache TTL | 5 min |
| Model VRAM (E2B q4_K_M) | ~1.9 GB |

## License

Apache 2.0
