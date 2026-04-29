# ClearPath 🧠

**Cognitive Accessibility Agent for Education — powered by Gemma 4**

> Gemma 4 Good Hackathon | Kaggle × Google DeepMind | Prize Pool: $200,000

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green.svg)](https://fastapi.tiangolo.com)

---

## What it does

ClearPath is a Chrome Extension + AI backend that transforms educational websites
into a more accessible experience for students with **ADHD, dyslexia, or language barriers**.

Unlike simple CSS tools, ClearPath understands the page context and acts:

| Page type | ClearPath action |
|-----------|------------------|
| 📖 Wikipedia article | Simplifies text to A2 level, applies easier reading styles, highlights repeated visits |
| 📝 Moodle test | Hides distractions, shows a 5-step preparation plan, recalls past mistake topics |
| 📋 Complex form | Converts the form into a step-by-step wizard with A2-level hints |

**Cold request: ~25s · Cache hit: <0.3s · Private profile data stays local**

---

## Architecture

```text
Chrome Extension
     │  DOM text + optional screenshot
     ▼
FastAPI Backend (port 8001)
     │
     ▼
LangGraph Multi-Agent Graph
     │
     ├── Analyzer ── Google AI Studio (cloud, multimodal)
     │               Classifies page: article / test / form
     │
     ├── Planner ─┐
     │  parallel  │── Gemma 4 E2B (local, Ollama)
     ├── Writer ──┘   Private: cognitive profile never leaves device
     │
     └── Action ───── DOM transformation commands
          │
          ▼
Chrome Extension applies:
apply_font | simplify_text | hide_element | add_step_guide | wizard_form

PostgreSQL stores multi-tenant cognitive profiles, interaction history, and cached analyses.
```

### Model split

| Agent | Model | Location | Why |
|-------|-------|----------|-----|
| Analyzer | Google AI Studio model | Cloud | Multimodal screenshot and page classification |
| Planner | Gemma 4 E2B | Local Ollama | Reads private user profile and history |
| Writer | Gemma 4 E2B or fine-tuned `clearpath-writer` | Local Ollama | Generates personal simplified text |
| Action | Rule-based backend code | Backend | Deterministic DOM commands with no extra model latency |

**Privacy-first:** Only page screenshots and extracted page context go to the cloud analyzer.
Cognitive profiles, interaction history, hard terms, and error patterns stay on the user's machine.

---

## Quick Start

### Prerequisites

- Docker Desktop
- [Ollama](https://ollama.com) installed and running locally
- [Google AI Studio API key](https://aistudio.google.com/apikey)

### Setup

```bash
git clone https://github.com/S1rt3ge/clearpath.git
cd clearpath

cp .env.example .env
# Edit .env and set GOOGLE_AI_STUDIO_API_KEY

ollama pull gemma4:e2b-it-q4_K_M

docker-compose up -d
curl http://localhost:8001/health
```

Expected health response:

```json
{"status":"ok","service":"clearpath-api"}
```

### Load the extension

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Click **Load unpacked**.
4. Select the `extension/` folder.
5. Open the ClearPath popup, choose a profile, and activate it.

---

## API smoke test

```bash
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

Repeat the same request within 5 minutes to verify PostgreSQL-backed cache:
the response should include `"from_cache": true`.

---

## Demo Scenarios

### Scenario 1 — Wikipedia + Dyslexia profile

1. Set profile: Dyslexia, Reading Level A2.
2. Open `https://en.wikipedia.org/wiki/Recursion`.
3. ClearPath simplifies the article, applies easier reading styles, and notes repeat visits.

### Scenario 2 — Moodle test + ADHD profile

1. Set profile: ADHD.
2. Open a quiz/test page.
3. ClearPath hides distracting elements, shows a preparation plan, and uses stored error patterns.

### Scenario 3 — HTML form + Low Literacy profile

1. Set profile: Low Literacy.
2. Open `https://httpbin.org/forms/post`.
3. ClearPath transforms the form into a wizard with one field at a time and simple hints.

---

## Performance

| Metric | Target |
|--------|--------|
| Cold request, no cache | ≤ 28s |
| Cache hit | < 0.3s |
| Cache TTL | 5 min by default |
| Local model VRAM | ~1.9 GB for q4 model |
| Planner latency | ~8s target |
| Writer latency | ~18s target |

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Agent orchestration | LangGraph StateGraph |
| Local model | Gemma 4 via Ollama |
| Cloud analysis | Google AI Studio OpenAI-compatible API |
| Backend | FastAPI + WebSockets |
| Database | PostgreSQL 16 + SQLAlchemy async |
| Cache | PostgreSQL-backed, TTL cleanup task |
| Extension | Chrome Manifest V3 |
| Deploy | Docker Compose |
| Fine-tuning | Unsloth on Kaggle |

---

## Project Structure

```text
clearpath/
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── agents/
│       │   ├── analyzer.py   # cloud page classification and form extraction
│       │   ├── planner.py    # local profile-aware transformation plan
│       │   ├── writer.py     # local text simplification
│       │   ├── action.py     # DOM transformation generation
│       │   └── graph.py      # LangGraph orchestration
│       ├── models/
│       │   ├── user_profile.py
│       │   └── analysis_cache.py
│       ├── routers/
│       │   ├── analyze.py    # HTTP + WebSocket analysis endpoints
│       │   └── profiles.py   # profile CRUD, history, error reporting
│       └── schemas/
│           └── analyze.py
├── extension/
│   ├── background.js
│   ├── content.js
│   ├── manifest.json
│   └── popup/
├── ml/
│   └── finetune_notebook.py
├── tasks/
└── docker-compose.yml
```

---

## Debug tools

Start pgAdmin when you need to inspect the database:

```bash
docker-compose --profile debug up -d
```

Then open `http://localhost:5050`.

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
