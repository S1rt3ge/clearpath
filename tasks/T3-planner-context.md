# T3 — Planner: Скорость + Контекст профиля
**Исполнитель:** Dev C  
**Ветка:** `feat/T3-planner-context`  
**Оценка:** ~1 день  
**Приоритет:** 🟡 Важный

---

## Цель

1. Ускорить Planner с ~20 с до ~8 с (сейчас тратит токены впустую)
2. Добавить контекст visited_content → Сценарий 1 (Wikipedia + Dyslexia)
3. Добавить контекст error_patterns → Сценарий 2 (Moodle + ADHD)

---

## Файл в твоём владении

```
backend/app/agents/planner.py
```

> Только этот файл. Остальные не трогать.

---

## Шаг 0 — Настройка ветки

```bash
git checkout main && git pull
git checkout -b feat/T3-planner-context
```

> ⚠️ Перед стартом убедись, что Senior B (T2) уже запушил первый коммит с `schemas.py`.
> Проверь: `git fetch origin feat/T2-extension-ux && git log origin/feat/T2-extension-ux --oneline -3`

---

## Шаг 1 — Ускорение: think=False + num_predict=128

Найди в `plan_transformations()` вызов Ollama и замени `options`:

```python
# БЫЛО (примерно так):
"options": {"temperature": 0.1, "num_predict": 256}

# СТАЛО:
"think": False,                                       # ← убирает reasoning pass
"options": {"temperature": 0.05, "num_predict": 128}  # JSON ≈ 80 токенов, хватит
```

**Почему 128?** Planner возвращает JSON ~80 токенов. При `think=False` модель не тратит сотни токенов на размышления — идёт прямо к ответу.

---

## Шаг 2 — Почистить system_prompt от лишнего контекста

Сейчас planner передаёт `unknown_terms[:10]` инлайн в system_prompt. Это увеличивает входной контекст и заставляет модель дольше "обдумывать". Убери `unknown_terms` из system_prompt — они не нужны Planner'у (это для Writer'а):

```python
# УБРАТЬ из system_prompt эту часть (или аналогичную):
# f"Previously unknown terms for this user: {unknown_terms[:10]}"

# Оставить только:
# profile_type, reading_level, content_type, complexity_score
```

---

## Шаг 3 — Сценарий 1: Wikipedia + Dyslexia (visited_content)

Добавить в `plan_transformations()` анализ истории посещений.

Вставь этот блок **перед** формированием `system_prompt`:

```python
# --- История посещений (для персонализации) ---
visited_content = user_profile.get("visited_content", [])
visited_urls = [v.get("url", "") for v in visited_content[-20:]]

# Проверить, был ли пользователь на этом URL раньше
current_url = page_analysis.get("url", "")  # URL приходит в page_analysis если передать
seen_before = any(current_url in u for u in visited_urls) if current_url else False

# Уникальные домены из истории
visited_domains = []
for url in visited_urls:
    try:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.replace("www.", "")
        if domain and domain not in visited_domains:
            visited_domains.append(domain)
    except Exception:
        pass
visited_domains = visited_domains[:5]
```

> **Откуда взять current_url?** Он приходит в `page_analysis` — добавь его туда в `analyzer.py` (это делает Dev E в T5). Но чтобы не зависеть от T5, используй запасной вариант: передавай URL через `user_profile` или оставь `current_url = ""` — функционал деградирует gracefully.

Добавить в `system_prompt` (в конец, перед закрывающими кавычками):

```python
history_note = ""
if seen_before:
    history_note = "\nIMPORTANT: User has visited this page before. Set seen_before=true in response. Focus agent_message on NEW information only."
elif visited_domains:
    history_note = f"\nUser recently visited: {', '.join(visited_domains)}."

# Добавить history_note в system_prompt
system_prompt = f"""...существующий промпт...{history_note}"""
```

Добавить `seen_before` в JSON-схему в промпте:

```python
# В system_prompt, в JSON-схеме ответа добавить поле:
"""
{
  "actions": [...],
  "agent_message": "...",
  "priority": "high|medium|low",
  "generate_steps": true/false,
  "generate_summary": true/false,
  "seen_before": true/false
}
"""
```

Добавить `seen_before` в fallback-ответ:

```python
return {
    "actions": ["simplify_text"],
    "agent_message": "I've made this page easier to read.",
    "priority": "medium",
    "generate_steps": False,
    "generate_summary": True,
    "seen_before": False,   # ← добавить
}
```

---

## Шаг 4 — Сценарий 2: Moodle + ADHD (error_patterns)

Вставить блок **после** блока с visited_content:

```python
# --- Паттерны ошибок (для ADHD сценария) ---
error_patterns = user_profile.get("error_patterns", {})
profile_type = user_profile.get("profile_type", "low_literacy")

errors_note = ""
if error_patterns and profile_type == "adhd":
    # Топ-3 темы по количеству ошибок
    top_errors = sorted(error_patterns.items(), key=lambda x: x[1], reverse=True)[:3]
    errors_str = ", ".join(f'"{topic}"' for topic, _ in top_errors)
    errors_note = (
        f"\nUser previously struggled with: {errors_str}. "
        "If this is a test page, mention these topics in agent_message and set generate_steps=true."
    )
```

Добавить `errors_note` в `system_prompt`.

Обновить fallback `agent_message` с учётом ошибок:

```python
# В fallback-ответе:
fallback_message = "I've made this page easier to read."
if error_patterns and profile_type == "adhd":
    top = sorted(error_patterns.items(), key=lambda x: x[1], reverse=True)
    if top:
        fallback_message = f"Раньше было сложно с: {top[0][0]}. Вот план подготовки."

return {
    "actions": ["simplify_text"],
    "agent_message": fallback_message,
    "priority": "medium",
    "generate_steps": profile_type == "adhd",
    "generate_summary": True,
    "seen_before": False,
}
```

---

## Итоговая структура `plan_transformations()`

```python
async def plan_transformations(page_analysis: dict, user_profile: dict) -> dict:
    profile_type = user_profile.get("profile_type", "low_literacy")
    reading_level = user_profile.get("reading_level", "B1")
    content_type = page_analysis.get("content_type", "unknown")

    # Блок 1: visited_content
    visited_content = user_profile.get("visited_content", [])
    # ... (код из Шага 3) ...

    # Блок 2: error_patterns
    error_patterns = user_profile.get("error_patterns", {})
    # ... (код из Шага 4) ...

    system_prompt = f"""You are a cognitive accessibility planner.
User profile: {profile_type}, reading level: {reading_level}

Based on page analysis, decide what transformations to apply.
Return ONLY valid JSON:
{{
  "actions": ["simplify_text", "hide_distractions", "add_step_guide", "apply_dyslexia_font", "wizard_form"],
  "agent_message": "Short friendly message in the page language (max 2 sentences)",
  "priority": "high|medium|low",
  "generate_steps": true/false,
  "generate_summary": true/false,
  "seen_before": true/false
}}{history_note}{errors_note}"""

    user_prompt = f"""Page type: {content_type}
Complexity: {page_analysis.get('complexity_score', 5)}/10
Action required: {page_analysis.get('action_required', 'read')}"""

    # Ollama call с think=False и num_predict=128
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            f"{settings.ollama_base_url}/api/chat",
            json={
                "model": settings.gemma_local_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                "stream": False,
                "think": False,
                "options": {"temperature": 0.05, "num_predict": 128},
            },
        )

    content = response.json().get("message", {}).get("content", "")

    # Убрать markdown-обёртку если есть
    content = content.strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    content = content.strip()

    # Убрать thinking-часть если модель всё равно выдала её
    if "<channel|>" in content:
        content = content.split("<channel|>", 1)[1].strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # ... fallback из Шага 4 ...
```

---

## Шаг 5 — Проверка

```bash
docker-compose restart backend

# Проверить время planner отдельно (смотреть логи):
docker logs clearpath-backend-1 -f

# Сделать запрос и смотреть на шаг planner в логах
curl -X POST http://localhost:8001/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{"user_id":"test","tenant_id":"demo","url":"https://en.wikipedia.org/wiki/Python",
       "page_title":"Python","dom_text":"Python is a language..."}'
```

---

## Definition of Done

- [ ] Planner возвращает ответ за < 10 с (видно в логах или `processing_time_ms` уменьшилось)
- [ ] При повторном URL в visited_content: `seen_before: true` в ответе от Planner
- [ ] При `profile_type=adhd` и непустом `error_patterns`: `agent_message` упоминает прошлые темы
- [ ] При `profile_type=adhd` и `content_type=test`: `generate_steps: true`
- [ ] Нет `JSONDecodeError` в логах (fallback работает)
- [ ] `think: False` и `num_predict: 128` в коде (проверить grep)

```bash
grep -n "num_predict" backend/app/agents/planner.py
# Должно быть: num_predict: 128
```
