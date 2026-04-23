# T5 — Analyzer Enhancement
**Исполнитель:** Dev E  
**Ветка:** `feat/T5-analyzer`  
**Оценка:** ~0.5 дня  
**Приоритет:** 🟡 Важный (нужен для Scenario 3 — wizard form)

---

## Цель

Улучшить `analyzer.py` чтобы:
1. Извлекать `form_fields` из страниц с формами → нужно для wizard (Scenario 3)
2. Находить `distracting_elements` точнее → нужно для ADHD сценария
3. Убрать баг с `KeyError` при пустом ответе Gemini
4. Добавить `url` в `page_analysis` → нужно Planner'у (T3)

---

## Файл в твоём владении

```
backend/app/agents/analyzer.py
```

> Только этот файл. Остальные не трогать.

---

## Шаг 0 — Настройка ветки

```bash
git checkout main && git pull
git checkout -b feat/T5-analyzer
```

> ⚠️ Перед стартом убедись, что Senior B (T2) уже запушил первый коммит с `schemas.py`.
> Проверь: `git fetch && git log origin/feat/T2-extension-ux --oneline -3`

---

## Шаг 1 — Обновить system_prompt с новой JSON-схемой

Это главное изменение. Замени весь `system_prompt` на:

```python
system_prompt = """You are a web page analyzer for a cognitive accessibility tool.
Analyze the provided page content (URL, DOM text, optional screenshot).
Return ONLY valid JSON — no explanation, no markdown, just the JSON object.

Required structure:
{
  "content_type": "article|test|form|dashboard|unknown",
  "complexity_score": 1-10,
  "key_elements": ["list of important UI elements found on the page"],
  "main_text_blocks": ["up to 3 main text paragraphs, actual content only, no navigation"],
  "distracting_elements": ["CSS selectors of ads/banners/sidebars that should be hidden"],
  "action_required": "read|fill_form|take_test|navigate",
  "form_fields": [
    {
      "selector": "CSS selector pointing directly to the input/select/textarea element",
      "label": "Human-readable label text as shown on page",
      "hint": "Simple A2-level explanation of what to enter here, in the same language as the page",
      "required": true
    }
  ]
}

Rules:
- form_fields: populate ONLY when content_type is "form", otherwise return empty array []
- distracting_elements: include selectors like .advertisement, .banner, aside, [id*="ad"],
  [class*="promo"], [class*="popup"], .cookie-notice, .newsletter-signup
- main_text_blocks: real article sentences only, skip nav/footer/boilerplate
- complexity_score: 1=very simple (A1), 10=very complex (C2 academic)
- If content_type is "test": set action_required to "take_test"
- If content_type is "form": set action_required to "fill_form"
"""
```

---

## Шаг 2 — Добавить URL в page_analysis

В `analyze_page()` добавь `url` как параметр результата:

```python
async def analyze_page(
    url: str,
    dom_text: str,
    screenshot_base64: Optional[str] = None,
) -> dict:
```

В конце функции, перед `return`, добавь URL в результат:

```python
    try:
        result = json.loads(content.strip())
        result["url"] = url      # ← добавить URL в page_analysis
        return result
    except json.JSONDecodeError:
        return {
            "content_type": "unknown",
            "complexity_score": 5,
            "key_elements": [],
            "main_text_blocks": [dom_text[:500]],
            "distracting_elements": [],
            "action_required": "read",
            "form_fields": [],
            "url": url,           # ← и в fallback тоже
        }
```

---

## Шаг 3 — Исправить баг с KeyError

Сейчас код упадёт с `KeyError` если Gemini вернул пустой ответ.

Найди строку:
```python
content = result["choices"][0]["message"]["content"]
```

Замени на безопасную версию:

```python
result_json = response.json()

# Защита от пустого ответа
choices = result_json.get("choices", [])
if not choices:
    logger.warning(f"Gemini returned no choices. Response: {result_json}")
    return {
        "content_type": "unknown",
        "complexity_score": 5,
        "key_elements": [],
        "main_text_blocks": [dom_text[:500]],
        "distracting_elements": [],
        "action_required": "read",
        "form_fields": [],
        "url": url,
    }

content = choices[0].get("message", {}).get("content", "")
if not content:
    logger.warning("Gemini returned empty content")
    return {
        "content_type": "unknown",
        "complexity_score": 5,
        "key_elements": [],
        "main_text_blocks": [dom_text[:500]],
        "distracting_elements": [],
        "action_required": "read",
        "form_fields": [],
        "url": url,
    }
```

---

## Шаг 4 — Убрать markdown-обёртку из ответа

Gemini иногда оборачивает JSON в ```json ... ```. Добавить очистку перед `json.loads`:

```python
# Очистить markdown если есть
content = content.strip()
if content.startswith("```"):
    # Убрать первую строку с ```json или ```
    lines = content.split("\n")
    lines = [l for l in lines if not l.startswith("```")]
    content = "\n".join(lines).strip()

try:
    result = json.loads(content)
    result["url"] = url
    return result
except json.JSONDecodeError:
    # ... fallback ...
```

---

## Шаг 5 — Добавить логирование

После получения ответа от Gemini добавить debug-лог:

```python
import logging
logger = logging.getLogger("clearpath")

# После успешного парсинга JSON:
logger.debug(
    f"Analyzer: content_type={result.get('content_type')}, "
    f"complexity={result.get('complexity_score')}, "
    f"form_fields={len(result.get('form_fields', []))}"
)
```

---

## Итоговый код функции

```python
async def analyze_page(
    url: str,
    dom_text: str,
    screenshot_base64: Optional[str] = None,
) -> dict:
    system_prompt = """...(из Шага 1)..."""

    user_content = f"""URL: {url}

Page text content:
{dom_text[:3000]}"""

    messages_content = []
    if screenshot_base64:
        messages_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{screenshot_base64}"},
        })
    messages_content.append({"type": "text", "text": user_content})

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.google_ai_studio_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.gemma_cloud_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": messages_content},
                ],
                "max_tokens": 768,
                "temperature": 0.1,
            },
        )

    result_json = response.json()

    # Защита от пустого ответа (Шаг 3)
    choices = result_json.get("choices", [])
    if not choices:
        logger.warning(f"Analyzer: Gemini returned no choices")
        return _fallback_analysis(url, dom_text)

    content = choices[0].get("message", {}).get("content", "")
    if not content:
        return _fallback_analysis(url, dom_text)

    # Убрать markdown (Шаг 4)
    content = content.strip()
    if content.startswith("```"):
        lines = [l for l in content.split("\n") if not l.startswith("```")]
        content = "\n".join(lines).strip()

    try:
        result = json.loads(content)
        result["url"] = url
        result.setdefault("form_fields", [])   # гарантировать наличие поля
        logger.debug(
            f"Analyzer: type={result.get('content_type')}, "
            f"complexity={result.get('complexity_score')}, "
            f"fields={len(result.get('form_fields', []))}"
        )
        return result
    except json.JSONDecodeError:
        logger.warning(f"Analyzer: JSON parse failed, using fallback")
        return _fallback_analysis(url, dom_text)


def _fallback_analysis(url: str, dom_text: str) -> dict:
    return {
        "content_type": "unknown",
        "complexity_score": 5,
        "key_elements": [],
        "main_text_blocks": [dom_text[:500]],
        "distracting_elements": [],
        "action_required": "read",
        "form_fields": [],
        "url": url,
    }
```

---

## Шаг 6 — Проверка

```bash
docker-compose restart backend

# Тест 1: Статья Wikipedia — form_fields должен быть пустым
curl -s -X POST http://localhost:8001/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{"user_id":"test","tenant_id":"demo",
       "url":"https://en.wikipedia.org/wiki/Python_(programming_language)",
       "page_title":"Python","dom_text":"Python is a high-level programming language..."}' \
  | python -m json.tool | grep -A5 "content_type"
# Ожидаем: content_type: "article", form_fields: []

# Тест 2: Страница с формой
curl -s -X POST http://localhost:8001/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{"user_id":"test","tenant_id":"demo",
       "url":"https://httpbin.org/forms/post",
       "page_title":"HTML Form","dom_text":"Customer name: Email: Telephone: Delivery: Comments:"}' \
  | python -m json.tool | grep -A20 "form_fields"
# Ожидаем: непустой form_fields с полями формы
```

---

## Definition of Done

- [ ] На Wikipedia: `content_type = "article"`, `form_fields = []`
- [ ] На `httpbin.org/forms/post`: `content_type = "form"`, `form_fields` содержит поля
- [ ] `page_analysis` содержит поле `url` с оригинальным URL
- [ ] Нет `KeyError` при тестировании (проверить `docker logs clearpath-backend-1`)
- [ ] При пустом ответе от Gemini: функция возвращает fallback, не падает
- [ ] `max_tokens` изменён с 512 на 768 (для поддержки длинного form_fields)
