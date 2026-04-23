# ClearPath — Параллельные таски для команды

**Дедлайн:** 18 мая 2026  
**Текущая проблема:** latency 85–130 с → нужно ≤ 28 с  

---

## Раздай файлы разработчикам

| Файл | Кому отдать | Оценка |
|------|-------------|--------|
| `T1-performance-cache.md` | Senior A | ~2.5 дня |
| `T2-extension-ux.md` | Senior B | ~2.5 дня |
| `T3-planner-context.md` | Dev C | ~1 день |
| `T4-profile-history.md` | Dev D | ~0.5 дня |
| `T5-analyzer.md` | Dev E | ~0.5 дня |
| `T6-devops.md` | Dev F | ~1 день |

---

## Единственное правило дня 0

**Senior B (T2) должен сделать первый коммит до того, как кто-либо начнёт.**

Один коммит, один файл: обновлённый `schemas.py`.  
После этого все остальные стартуют параллельно без зависимостей.

```bash
# Senior B — первый коммит:
git checkout -b feat/T2-extension-ux
# ... правки schemas.py ...
git push -u origin feat/T2-extension-ux
# Пишет в чат: "schema commit done"
```

---

## Карта владения файлами (кто что трогает)

```
backend/app/agents/
  writer.py          → T1 (Senior A)
  graph.py           → T1 (Senior A)
  planner.py         → T3 (Dev C)
  analyzer.py        → T5 (Dev E)
  action.py          → T2 (Senior B)

backend/app/routers/
  analyze.py         → T1 (Senior A)
  profiles.py        → T4 (Dev D)

backend/app/models/
  analysis_cache.py  → T1 (Senior A) — создать с нуля
  user_profile.py    → НИКТО (только читают)

backend/app/schemas/
  analyze.py         → T2 (Senior B) — первый коммит!

backend/app/
  main.py            → T1 (Senior A)

extension/
  content.js         → T2 (Senior B)
  popup/             → T2 (Senior B)
  background.js      → T2 (Senior B)

docker-compose.yml   → T6 (Dev F)
README.md            → T6 (Dev F)
.env.example         → T6 (Dev F)
backend/Dockerfile   → T6 (Dev F)
```

**Конфликтов при мерже не будет** — каждый разработчик владеет своими файлами.

---

## Порядок мержа PR (когда все готовы)

```
1. T6 → main  (devops, нет зависимостей)
2. T5 → main  (analyzer, нет зависимостей)
3. T4 → main  (profiles, нет зависимостей)
4. T3 → main  (planner, нет зависимостей)
5. T1 → main  (performance — самый важный)
6. T2 → main  (extension — последним, он потребитель всего)
```

---

## Интерфейсные контракты (согласовать на Дне 0)

### Контракт 1 — `AnalyzeResponse` (T2 определяет, T1 заполняет)
```python
hard_terms: Optional[List[str]] = None      # T1 заполняет в writer.py
last_visit_info: Optional[dict] = None      # T1 заполняет в analyze.py
# Формат last_visit_info: {"days_ago": 2, "url": "https://..."}
```

### Контракт 2 — `page_analysis` dict (T5 определяет, T2 и T3 читают)
```json
{
  "content_type": "article|test|form|dashboard|unknown",
  "form_fields": [{"selector": "...", "label": "...", "hint": "...", "required": true}],
  "distracting_elements": [".banner", "#sidebar"],
  "url": "https://..."
}
```

### Контракт 3 — Profile endpoints (T4 создаёт, T2 вызывает из Extension)
```
GET  /api/v1/profiles/{id}/history   → {recent, hard_terms, top_domains, error_patterns}
POST /api/v1/profiles/{id}/error     → body: {topic: str, url: str}
```

---

## Целевые метрики

| Метрика | Сейчас | После |
|---------|--------|-------|
| Cold request | 85–130 с | ≤ 28 с |
| Cache hit | ~0.3 с | ≤ 0.3 с |
| Planner | ~20 с | ~8 с |
| Writer | ~45–60 с | ~18 с |

---

## Ежедневный sync (15 минут)

Три вопроса:
1. Что сделано вчера?
2. Что блокирует?
3. Что будет сделано сегодня?

Если блокировка касается интерфейсного контракта — решать немедленно в чате.
