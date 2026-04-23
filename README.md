# ClearPath 🧠

**Cognitive Accessibility Agent for Education — powered by Gemma 4**

> Gemma 4 Good Hackathon | Kaggle × Google DeepMind | Prize Pool: $200,000

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green.svg)](https://fastapi.tiangolo.com)

---

## What it does

ClearPath is a Chrome Extension + AI backend that transforms any educational website
into an accessible experience for students with **ADHD, dyslexia, or language barriers**.

Unlike simple CSS tools, ClearPath **understands context** and acts:

| Page type | ClearPath action |
|-----------|-----------------|
| 📖 Wikipedia article | Simplifies text to A2 level, OpenDyslexic font, highlights new info |
| 📝 Moodle test | Hides distractions, shows 5-step prep plan, recalls past mistakes |
| 📋 Complex form | Transforms into a step-by-step wizard with A2-level hints |

**Cold request: ~25s · Cache hit: <0.3s · Works 100% locally for private data**

---

## Architecture

```
Chrome Extension
     │  DOM text + screenshot
     ▼
FastAPI Backend (port 8001)
     │
     ▼
LangGraph Multi-Agent Graph
     │
     ├── Analyzer  ── Gemini Flash (cloud, multimodal)
     │                Classifies page: article / test / form
     │
     ├── Planner ──┐
     │  (parallel) │── Gemma 4 E2B (local, Ollama)
     ├── Writer  ──┘   Private: cognitive profile never leaves device
     │
     └── Action ──── DOM transformation commands → Extension
          │
          ▼
     Chrome Extension applies:
     apply_font | simplify_text | hide_element | add_step_guide | wizard_form

PostgreSQL — Multi-tenant cognitive profiles with long-term memory
```

### Model split

| Agent | Model | Location | Why |
|-------|-------|----------|-----|
| Analyzer | Gemini Flash | Cloud | Multimodal (screenshot), fast |
| Planner | Gemma 4 E2B | Local (Ollama) | Private — reads user profile |
| Writer | Gemma 4 E2B | Local (Ollama) | Private — generates personal text |
| Action | Rule-based | Backend | Deterministic, no latency |

**Privacy-first:** Only screenshots go to the cloud. Cognitive profiles, interaction history,
and error patterns stay on your machine.

---

## Quick Start

### Prerequisites
- Docker Desktop
- [Ollama](https://ollama.com) installed and running locally
- [Google AI Studio API key](https://aistudio.google.com/apikey) (free)

### 5-step setup

```bash
# 1. Clone
git clone https://github.com/S1rt3ge/clearpath.git
cd clearpath

# 2. Configure
cp .env.example .env
# Edit .env — add your GOOGLE_AI_STUDIO_API_KEY

# 3. Pull the local model (~1.9 GB)
ollama pull gemma4:e2b-it-q4_K_M

# 4. Start backend + database
docker-compose up -d

# Wait ~20s, then verify:
curl http://localhost:8001/health
# → {"status": "ok", "service": "clearpath-api"}

# 5. Load Extension in Chrome
# chrome://extensions → Enable "Developer mode" → "Load unpacked" → select /extension folder
# Open the popup → choose your profile → "Activate ClearPath"
```

### Verify it works

```bash
# Health check
curl http://localhost:8001/health

# Test analysis endpoint
curl -s -X POST http://localhost:8001/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test-user",
    "tenant_id": "demo",
    "url": "https://en.wikipedia.org/wiki/Python_(programming_language)",
    "page_title": "Python",
    "dom_text": "Python is a high-level, general-purpose programming language."
  }' | python -m json.tool
```

---

## Demo Scenarios

### Scenario 1 — Wikipedia + Dyslexia profile
1. Set profile: Dyslexia, Reading Level A2
2. Open `https://en.wikipedia.org/wiki/Recursion`
3. ClearPath: simplifies text → OpenDyslexic font → "You visited this before, here's what's new"

### Scenario 2 — Moodle test + ADHD profile
1. Set profile: ADHD
2. Open any Moodle quiz page
3. ClearPath: hides banners → shows 5-step preparation plan → recalls past mistakes

### Scenario 3 — HTML form + Low Literacy profile
1. Set profile: Low Literacy
2. Open `https://httpbin.org/forms/post`
3. ClearPath: transforms form into wizard → shows one field at a time with A2 hints

---

## Performance

| Metric | Value |
|--------|-------|
| Cold request (no cache) | ~25s |
| Cache hit (PostgreSQL) | <0.3s |
| Cache TTL | 5 min |
| Local model VRAM (E2B q4_K_M) | ~1.9 GB |
| Planner latency | ~8s |
| Writer latency | ~18s |

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Agent orchestration | LangGraph StateGraph |
| Local model | Gemma 4 E2B via Ollama |
| Cloud model | Gemini Flash via Google AI Studio |
| Backend | FastAPI + WebSockets |
| Database | PostgreSQL 16 + SQLAlchemy async |
| Cache | PostgreSQL-backed, 5-min TTL |
| Extension | Chrome Manifest V3 |
| Deploy | Docker Compose (single command) |
| Fine-tuning | Unsloth on Kaggle (in progress) |

---

## Project Structure

```
clearpath/
├── backend/
│   └── app/
│       ├── agents/
│       │   ├── analyzer.py   # Gemini Flash — page classification
│       │   ├── planner.py    # Gemma E2B — transformation planning
│       │   ├── writer.py     # Gemma E2B — text simplification
│       │   ├── action.py     # DOM transformation generation
│       │   └── graph.py      # LangGraph orchestration
│       ├── models/
│       │   ├── user_profile.py     # Cognitive profiles (PostgreSQL)
│       │   └── analysis_cache.py   # URL result cache (PostgreSQL)
│       └── routers/
│           ├── analyze.py    # /analyze HTTP + /ws/analyze WebSocket
│           └── profiles.py   # Profile CRUD + history + errors
├── extension/
│   ├── content.js     # DOM capture + transformation injection
│   ├── popup/         # User profile UI
│   └── background.js  # Screenshot capture
├── ml/
│   └── finetune_notebook.py  # Unsloth fine-tuning (Kaggle)
└── docker-compose.yml
```

---

## License

Apache 2.0 — see [LICENSE](LICENSE)

---

*Built for the Gemma 4 Good Hackathon by Team ClearPath*
