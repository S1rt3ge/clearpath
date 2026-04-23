# T4 — Profile History API
**Исполнитель:** Dev D  
**Ветка:** `feat/T4-profile-history`  
**Оценка:** ~0.5 дня  
**Приоритет:** 🟡 Важный (нужен для P3 Long-term memory)

---

## Цель

Добавить два новых REST endpoint'а в `profiles.py`:
1. `GET /api/v1/profiles/{id}/history` — история визитов + сложные термины (нужен popup'у Extension)
2. `POST /api/v1/profiles/{id}/error` — сохранить ошибку пользователя (нужен Extension для Scenario 2)

Больше ничего трогать не нужно.

---

## Файл в твоём владении

```
backend/app/routers/profiles.py
```

> Только этот файл. Остальные не трогать.

---

## Шаг 0 — Настройка ветки

```bash
git checkout main && git pull
git checkout -b feat/T4-profile-history
```

---

## Шаг 1 — Добавить endpoint истории

Открой `backend/app/routers/profiles.py`.

В конец файла добавь:

```python
# ---------------------------------------------------------------------------
# History endpoint
# ---------------------------------------------------------------------------

@router.get("/{profile_id}/history")
async def get_profile_history(
    profile_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Returns recent interaction history and hard terms for a profile.
    Used by the Chrome Extension popup to show "last visited X days ago".
    """
    result = await db.execute(
        select(UserProfile).where(UserProfile.id == profile_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    history = profile.interaction_history or []
    hard_terms = profile.unknown_terms or []

    # Посчитать топ-5 доменов
    top_domains = _count_domains(history)

    return {
        "profile_id": profile_id,
        "recent": history[-20:],              # последние 20 визитов
        "total_visits": len(history),
        "hard_terms": hard_terms[:20],        # топ-20 сложных слов
        "top_domains": top_domains,
        "error_patterns": profile.error_patterns or {},
    }


def _count_domains(history: list) -> list:
    """Count visits per domain from interaction history."""
    from collections import Counter
    domains = []
    for entry in history:
        url = entry.get("url", "")
        if "://" in url:
            try:
                # Берём домен без www
                domain = url.split("://")[1].split("/")[0].replace("www.", "")
                domains.append(domain)
            except Exception:
                pass
    counts = Counter(domains).most_common(5)
    return [{"domain": d, "visits": c} for d, c in counts]
```

---

## Шаг 2 — Добавить endpoint для сохранения ошибок

Добавить Pydantic-модель и endpoint сразу после предыдущего:

```python
# ---------------------------------------------------------------------------
# Error reporting endpoint
# ---------------------------------------------------------------------------

class ErrorReport(BaseModel):
    topic: str    # тема ошибки: "recursion", "fractions", "passive voice", etc.
    url: str      # URL страницы где произошла ошибка


@router.post("/{profile_id}/error")
async def report_error(
    profile_id: str,
    data: ErrorReport,
    db: AsyncSession = Depends(get_db),
):
    """
    Records a topic where the user made an error.
    Used by the Chrome Extension when user answers a test question wrong.
    Planner reads error_patterns to personalize agent_message.

    Example: POST /api/v1/profiles/{id}/error
    Body: {"topic": "recursion", "url": "https://moodle.example.com/quiz/1"}
    """
    result = await db.execute(
        select(UserProfile).where(UserProfile.id == profile_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Увеличить счётчик для темы (или создать с нуля)
    patterns = dict(profile.error_patterns or {})
    patterns[data.topic] = patterns.get(data.topic, 0) + 1

    # Ограничить размер словаря (топ-50 тем)
    if len(patterns) > 50:
        # Удалить тему с наименьшим счётчиком
        min_topic = min(patterns, key=patterns.get)
        del patterns[min_topic]

    profile.error_patterns = patterns
    await db.commit()

    return {
        "ok": True,
        "topic": data.topic,
        "count": patterns[data.topic],
        "all_patterns": dict(sorted(patterns.items(), key=lambda x: x[1], reverse=True)),
    }
```

---

## Шаг 3 — Убедиться что импорты есть

В начале файла должны быть эти импорты (добавь если нет):

```python
from pydantic import BaseModel
from typing import Optional
```

`BaseModel` нужен для `ErrorReport`. Скорее всего уже есть в файле.

---

## Шаг 4 — Проверка

```bash
docker-compose restart backend

# 1. Получить profile_id (создать профиль если нет)
curl -X POST http://localhost:8001/api/v1/profiles/ \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"demo","profile_type":"adhd","reading_level":"A2","language":"ru"}'
# Скопируй id из ответа → вставь вместо YOUR_PROFILE_ID

# 2. Проверить историю (пустая на новом профиле)
curl http://localhost:8001/api/v1/profiles/YOUR_PROFILE_ID/history
# Ожидаем: {"profile_id":"...","recent":[],"total_visits":0,"hard_terms":[],...}

# 3. Записать ошибку
curl -X POST http://localhost:8001/api/v1/profiles/YOUR_PROFILE_ID/error \
  -H "Content-Type: application/json" \
  -d '{"topic":"recursion","url":"https://moodle.example.com/quiz/1"}'
# Ожидаем: {"ok":true,"topic":"recursion","count":1,...}

# 4. Записать ещё раз ту же тему
curl -X POST http://localhost:8001/api/v1/profiles/YOUR_PROFILE_ID/error \
  -H "Content-Type: application/json" \
  -d '{"topic":"recursion","url":"https://moodle.example.com/quiz/2"}'
# Ожидаем: {"ok":true,"topic":"recursion","count":2,...}

# 5. Проверить что ошибки сохранились в истории
curl http://localhost:8001/api/v1/profiles/YOUR_PROFILE_ID/history
# Ожидаем: error_patterns: {"recursion": 2}
```

---

## Definition of Done

- [ ] `GET /api/v1/profiles/{id}/history` возвращает `recent`, `hard_terms`, `total_visits`, `top_domains`, `error_patterns`
- [ ] `POST /api/v1/profiles/{id}/error` увеличивает счётчик темы в `error_patterns`
- [ ] Повторный вызов `error` для той же темы увеличивает счётчик (не сбрасывает)
- [ ] Оба endpoint'а возвращают `404` для несуществующего `profile_id`
- [ ] Нет ошибок в логах при нормальной работе (`docker logs clearpath-backend-1`)

---

## Как это используется другими частями проекта

- **Extension popup (T2)** вызывает `GET /history` при открытии и показывает последние 3 визита
- **Extension content.js (T2)** может вызывать `POST /error` когда пользователь ошибается в тесте
- **Planner (T3)** читает `error_patterns` из профиля (уже хранится в `UserProfile.error_patterns`) — ты просто даёшь endpoint для записи новых ошибок

Тебе не нужно трогать ни planner, ни extension. Твоя задача — только два endpoint'а.
