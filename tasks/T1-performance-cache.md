# T1 — Performance & Cache Infrastructure
**Исполнитель:** Senior A  
**Ветка:** `feat/T1-perf-cache`  
**Оценка:** ~2.5 дня  
**Приоритет:** 🔴 Критический (блокирует демо)

---

## Цель

Снизить latency с 85–130 с до **≤ 28 с** на cold request, **≤ 0.3 с** на cached.

**Почему сейчас медленно:**
- `asyncio.gather()` в graph.py есть, но Planner и Writer делят одну GPU в Ollama → они всё равно сериализуются
- Writer использует `num_predict=640` даже с `think=False` → ~45–60 с
- Кэш только in-memory → не переживает рестарт контейнера

---

## Файлы в твоём владении

```
backend/app/agents/writer.py
backend/app/agents/graph.py
backend/app/models/analysis_cache.py   ← создать с нуля
backend/app/routers/analyze.py
backend/app/main.py
```

> ⚠️ Никто другой эти файлы не трогает. Если нужен hotfix от другого разработчика — через PR к тебе.

---

## Шаг 0 — Настройка ветки

```bash
git checkout main && git pull
git checkout -b feat/T1-perf-cache
```

---

## Шаг 1 — `writer.py`: три правки

### 1.1 Снизить num_predict

С `think=False` модель не тратит ~480 токенов на размышления — хватит 280:

```python
# Найди в simplify_text():
# БЫЛО:
"options": {"temperature": 0.3, "num_predict": 640}

# СТАЛО:
"options": {"temperature": 0.3, "num_predict": 280}
```

### 1.2 Добавить недостающие _THINKING_MARKERS

Скриншот пользователей показал, что фраза `"The user wants me to"` просачивается в overlay.
Замени весь кортеж `_THINKING_MARKERS` на этот:

```python
_THINKING_MARKERS = (
    "Thinking Process:",
    "**Analyze the Request",
    "**Step 1",
    "Step 1.",
    "Let me analyze",
    "I need to simplify",
    "I will simplify",
    "**Analyze:",
    "The user wants me to",   # ← исправляет баг из демо
    "My task is to",
    "I will now",
    "Let me break",
    "I should simplify",
    "To simplify this",
    "I'll simplify",
    "Here is the simplified",
)
```

### 1.3 Вернуть hard_terms вместе с текстом

Меняем сигнатуру функции — она теперь возвращает `tuple[str, list[str]]`:

```python
async def simplify_text(
    text: str,
    reading_level: str = "A2",
    language: str = "en",
    max_sentences: int = 10,
) -> tuple[str, list[str]]:          # ← было: -> str
    cleaned = _clean_text(text)
    article_text = _extract_article_text(cleaned)

    # ... весь существующий код без изменений до конца функции ...

    # После получения result — добавить:
    import re as _re
    original_words = set(_re.findall(r'\b[A-Za-zА-Яа-я]{8,}\b', article_text))
    simplified_words = set(_re.findall(r'\b[A-Za-zА-Яа-я]{8,}\b', result))
    hard_terms = list(original_words - simplified_words)[:10]

    return result, hard_terms         # ← было: return result
```

---

## Шаг 2 — `graph.py`: распаковать tuple + добавить hard_terms в state

### 2.1 Добавить поле в GraphState

```python
class GraphState(TypedDict):
    request: dict
    user_profile: dict
    page_analysis: Optional[dict]
    plan: Optional[dict]
    simplified_text: Optional[str]
    hard_terms: Optional[list]        # ← NEW
    transformations: Optional[list]
    response: Optional[dict]
    error: Optional[str]
    start_time: float
    last_visit_info: Optional[dict]   # ← NEW (заполняет router перед вызовом графа)
```

### 2.2 Распаковать tuple в planner_and_writer_node

```python
async def planner_and_writer_node(state: GraphState) -> GraphState:
    try:
        req = state["request"]
        profile = state["user_profile"]
        analysis = state["page_analysis"] or {}

        plan_coro = plan_transformations(
            page_analysis=analysis,
            user_profile=profile,
        )
        writer_coro = simplify_text(
            text=" ".join(analysis.get("main_text_blocks", []))[:2000]
                  or req.get("dom_text", "")[:2000],
            reading_level=profile.get("reading_level", "A2"),
            language=profile.get("language", "en"),
        )

        plan, (simplified, hard_terms) = await asyncio.gather(plan_coro, writer_coro)

        return {
            **state,
            "plan": plan,
            "simplified_text": simplified,
            "hard_terms": hard_terms,
        }
    except Exception as exc:
        logger.error(f"planner_and_writer_node error: {exc}")
        return {
            **state,
            "plan": {"actions": ["simplify_text"], "agent_message": "Page simplified.", "generate_steps": False},
            "simplified_text": None,
            "hard_terms": [],
        }
```

### 2.3 Прокинуть hard_terms и last_visit_info в response (action_node)

```python
# В action_node, в блоке построения response:
response = {
    "content_type": state["page_analysis"].get("content_type", "unknown"),
    "transformations": [t.model_dump() for t in transformations],
    "agent_message": state["plan"].get("agent_message", "Page adapted for you."),
    "processing_time_ms": int((time.time() - state["start_time"]) * 1000),
    "hard_terms": state.get("hard_terms") or [],           # ← NEW
    "last_visit_info": state.get("last_visit_info"),       # ← NEW
}
```

---

## Шаг 3 — `models/analysis_cache.py`: создать с нуля

Создай новый файл `backend/app/models/analysis_cache.py`:

```python
"""
PostgreSQL-based analysis result cache.
Survives container restarts; TTL enforced via expires_at column.
"""
import hashlib
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class AnalysisCache(Base):
    __tablename__ = "analysis_cache"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cache_key = Column(String(64), nullable=False, unique=True, index=True)
    result = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True),
                        default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=False)

    @staticmethod
    def make_key(
        url: str,
        tenant_id: str,
        profile_type: str,
        reading_level: str,
        language: str,
    ) -> str:
        """SHA-256 of the cache dimensions. Never stores URL in plain text."""
        raw = f"{tenant_id}:{url}:{profile_type}:{reading_level}:{language}"
        return hashlib.sha256(raw.encode()).hexdigest()
```

---

## Шаг 4 — `routers/analyze.py`: заменить in-memory кэш на PostgreSQL

### 4.1 Удалить весь старый кэш

Удали эти блоки целиком:
```python
# УДАЛИТЬ:
_result_cache: dict = {}
_CACHE_TTL = 300

def _cache_key(...): ...
def _get_cached(...): ...
def _set_cached(...): ...
```

### 4.2 Добавить импорты

```python
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, delete
from app.models.analysis_cache import AnalysisCache
```

### 4.3 Добавить два хелпера

```python
_CACHE_TTL_MINUTES = 5

async def _db_get_cache(db: AsyncSession, key: str) -> Optional[dict]:
    now = datetime.now(timezone.utc)
    row = await db.execute(
        select(AnalysisCache).where(
            AnalysisCache.cache_key == key,
            AnalysisCache.expires_at > now,
        )
    )
    entry = row.scalar_one_or_none()
    return entry.result if entry else None


async def _db_set_cache(db: AsyncSession, key: str, result: dict) -> None:
    expires = datetime.now(timezone.utc) + timedelta(minutes=_CACHE_TTL_MINUTES)
    existing = await db.execute(
        select(AnalysisCache).where(AnalysisCache.cache_key == key)
    )
    entry = existing.scalar_one_or_none()
    if entry:
        entry.result = result
        entry.expires_at = expires
    else:
        db.add(AnalysisCache(cache_key=key, result=result, expires_at=expires))
    await db.commit()
```

### 4.4 Обновить HTTP endpoint `analyze_page`

```python
@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_page(request: AnalyzeRequest, db: AsyncSession = Depends(get_db)):
    profile = await _load_or_create_profile(
        db, _parse_uuid(request.user_id), request.tenant_id
    )
    profile_dict = profile.to_dict()

    # --- L1: PostgreSQL cache check ---
    cache_key = AnalysisCache.make_key(
        request.url, request.tenant_id,
        profile_dict.get("profile_type", ""),
        profile_dict.get("reading_level", ""),
        profile_dict.get("language", "en"),
    )
    cached = await _db_get_cache(db, cache_key)
    if cached:
        cached["from_cache"] = True
        return cached

    # --- last_visit_info ---
    history = profile.interaction_history or []
    last = next((h for h in reversed(history) if h.get("url") == request.url), None)
    last_visit_info = None
    if last:
        days_ago = int((time.time() - last["timestamp"]) / 86400)
        last_visit_info = {"days_ago": days_ago, "url": request.url}

    # --- Run agent graph ---
    graph = get_graph()
    initial_state = _build_initial_state(request, profile_dict)
    initial_state["last_visit_info"] = last_visit_info
    state = await graph.ainvoke(initial_state)

    result = state["response"]

    # --- Save to cache ---
    if result:
        await _db_set_cache(db, cache_key, result)

    # --- Update profile ---
    hard_terms = result.get("hard_terms", []) if result else []
    existing_terms = set(profile.unknown_terms or [])
    profile.unknown_terms = list(existing_terms | set(hard_terms))[:100]
    profile.visited_content = (profile.visited_content or [])[-99:] + [
        {"url": request.url, "ts": time.time()}
    ]
    profile.interaction_history = (profile.interaction_history or [])[-49:] + [{
        "url": request.url,
        "content_type": result.get("content_type") if result else None,
        "timestamp": time.time(),
    }]
    await db.commit()

    return result
```

### 4.5 Обновить WebSocket endpoint аналогично

Тот же паттерн: сначала `_db_get_cache`, при miss → граф → `_db_set_cache`.

---

## Шаг 5 — `main.py`: фоновая очистка кэша

```python
# Добавить импорт:
from sqlalchemy import delete
from app.models.analysis_cache import AnalysisCache
from app.database import AsyncSessionLocal

async def _cleanup_cache_loop() -> None:
    """Удалять протухшие записи каждые 10 минут."""
    while True:
        await asyncio.sleep(600)
        try:
            async with AsyncSessionLocal() as db:
                await db.execute(
                    delete(AnalysisCache).where(
                        AnalysisCache.expires_at < datetime.now(timezone.utc)
                    )
                )
                await db.commit()
                _logger.debug("Cache cleanup: expired entries removed")
        except Exception as e:
            _logger.warning(f"Cache cleanup error: {e}")

# В lifespan, после asyncio.create_task(_warmup_ollama()):
asyncio.create_task(_cleanup_cache_loop())
```

Добавить импорт в начало файла:
```python
from datetime import datetime, timezone
```

---

## Шаг 6 — Проверка

```bash
# Применить изменения
docker-compose restart backend

# 1. Cold request — замерить время
curl -X POST http://localhost:8001/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{"user_id":"test","tenant_id":"demo","url":"https://en.wikipedia.org/wiki/Python","page_title":"Python","dom_text":"Python is a high-level programming language..."}'
# Ожидаем: processing_time_ms < 30000

# 2. Повторный запрос — должен вернуться мгновенно
# Ожидаем: from_cache: true, время < 500мс

# 3. Проверить таблицу в PostgreSQL
docker exec -it clearpath-postgres-1 psql -U clearpath_user -d clearpath \
  -c "SELECT cache_key, expires_at FROM analysis_cache LIMIT 5;"
```

---

## Definition of Done

- [ ] Cold request: `processing_time_ms < 30000` в JSON ответе
- [ ] Повторный запрос того же URL: `from_cache: true` и время ответа < 500 мс
- [ ] В таблице `analysis_cache` появляется запись после первого запроса
- [ ] Overlay на Wikipedia не содержит "Thinking Process:", "The user wants me to" и аналогичный мусор
- [ ] `docker-compose restart backend` не ломает кэш (он в PostgreSQL, не в памяти)
- [ ] Нет `KeyError` / `AttributeError` в логах при нормальной работе

---

## Интерфейсный контракт для других разработчиков

Ты добавляешь в `AnalyzeResponse` (через `schemas.py` — это делает **Senior B в T2**) два поля:
```
hard_terms: list[str]     — сложные слова из оригинала
last_visit_info: dict     — {"days_ago": int, "url": str} или null
```
Твой код их **заполняет**, Senior B их только **объявляет** в схеме.
