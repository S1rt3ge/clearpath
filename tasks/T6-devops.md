# T6 — DevOps, README & Demo Prep
**Исполнитель:** Dev F  
**Ветка:** `feat/T6-devops`  
**Оценка:** ~1 день  
**Приоритет:** 🟢 Важный для сабмишна

---

## Цель

1. Гарантировать что `docker-compose up -d` работает на чистой машине без ручных шагов
2. Написать README уровня хакатон-сабмишна
3. Подготовить демо-инструкцию для видео

---

## Файлы в твоём владении

```
docker-compose.yml
README.md
.env.example
backend/Dockerfile
```

> Только эти файлы. Backend-код не трогать.

---

## Шаг 0 — Настройка ветки

```bash
git checkout main && git pull
git checkout -b feat/T6-devops
```

---

## Шаг 1 — `docker-compose.yml`

Замени весь файл:

```yaml
version: "3.9"

services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: clearpath
      POSTGRES_USER: clearpath_user
      POSTGRES_PASSWORD: clearpath_pass
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U clearpath_user -d clearpath"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s

  backend:
    build: ./backend
    ports:
      - "8001:8000"
    environment:
      DATABASE_URL: postgresql+asyncpg://clearpath_user:clearpath_pass@postgres:5432/clearpath
      OLLAMA_BASE_URL: ${OLLAMA_BASE_URL:-http://host.docker.internal:11434}
      GOOGLE_AI_STUDIO_API_KEY: ${GOOGLE_AI_STUDIO_API_KEY:-}
      GEMMA_LOCAL_MODEL: ${GEMMA_LOCAL_MODEL:-gemma4:e2b-it-q4_K_M}
      GEMMA_CLOUD_MODEL: ${GEMMA_CLOUD_MODEL:-gemini-2.0-flash}
      CACHE_TTL_MINUTES: ${CACHE_TTL_MINUTES:-5}
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - ./backend:/app
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
    extra_hosts:
      - "host.docker.internal:host-gateway"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 20s

  # Опциональный pgAdmin для отладки БД
  # Запустить: docker-compose --profile debug up -d
  pgadmin:
    image: dpage/pgadmin4:latest
    profiles: ["debug"]
    environment:
      PGADMIN_DEFAULT_EMAIL: admin@clearpath.local
      PGADMIN_DEFAULT_PASSWORD: admin
    ports:
      - "5050:80"
    depends_on:
      - postgres

volumes:
  postgres_data:
```

---

## Шаг 2 — `.env.example`

Замени весь файл:

```env
# =============================================================================
# ClearPath — Environment Configuration
# =============================================================================
# Скопируй в .env и заполни значения:
#   cp .env.example .env

# -----------------------------------------------------------------------------
# PostgreSQL (используется автоматически через Docker Compose)
# -----------------------------------------------------------------------------
DATABASE_URL=postgresql+asyncpg://clearpath_user:clearpath_pass@postgres:5432/clearpath

# -----------------------------------------------------------------------------
# Ollama (локально на хост-машине, не в Docker)
# Убедись что Ollama запущен: ollama serve
# Скачай модель: ollama pull gemma4:e2b-it-q4_K_M
# -----------------------------------------------------------------------------
OLLAMA_BASE_URL=http://host.docker.internal:11434
GEMMA_LOCAL_MODEL=gemma4:e2b-it-q4_K_M

# -----------------------------------------------------------------------------
# Google AI Studio — бесплатный доступ к Gemini Flash
# Получить ключ: https://aistudio.google.com/apikey
# Лимиты бесплатного уровня: 1500 запросов/день
# -----------------------------------------------------------------------------
GOOGLE_AI_STUDIO_API_KEY=your_key_here
GEMMA_CLOUD_MODEL=gemini-2.0-flash

# -----------------------------------------------------------------------------
# Cache
# -----------------------------------------------------------------------------
CACHE_TTL_MINUTES=5

# -----------------------------------------------------------------------------
# App
# -----------------------------------------------------------------------------
LOG_LEVEL=INFO
```

---

## Шаг 3 — `backend/Dockerfile`

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Системные зависимости (curl нужен для healthcheck)
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Ключевое изменение: добавлен `curl` — без него healthcheck в `docker-compose.yml` не работает.

---

## Шаг 4 — `README.md`

Замени весь файл:

```markdown
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
```

---

## Шаг 5 — Проверка на чистой машине

Прогони полный сценарий Quick Start сам, как будто видишь проект впервые:

```bash
# Убедиться что docker-compose up не требует ручных шагов
docker-compose down -v          # полный сброс
docker-compose up -d            # старт с нуля
docker-compose ps               # все сервисы должны быть healthy

# Проверить healthcheck'и
docker inspect clearpath-backend-1 | grep -A5 '"Health"'
docker inspect clearpath-postgres-1 | grep -A5 '"Health"'

# API должен отвечать через ~20с после старта
curl http://localhost:8001/health
```

---

## Definition of Done

- [ ] `docker-compose up -d` на чистой машине → все сервисы `healthy` за ~30с
- [ ] `curl http://localhost:8001/health` → `{"status": "ok", "service": "clearpath-api"}`
- [ ] README содержит рабочий Quick Start (проверен вручную от первой команды)
- [ ] `.env.example` содержит все переменные с комментариями
- [ ] В `Dockerfile` есть `curl` (нужен для healthcheck)
- [ ] `docker-compose --profile debug up -d` поднимает pgAdmin на `localhost:5050`

---

## Важные замечания

**Не меняй** backend-код — это за пределами твоего таска.

Если `docker-compose up` падает из-за кода — создай issue в GitHub и сообщи в команду.
Твоя задача: инфраструктура работает, документация готова к сабмишну.
