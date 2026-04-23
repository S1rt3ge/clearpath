# T2 — Extension UX + Scenario 3 (Wizard Form)
**Исполнитель:** Senior B  
**Ветка:** `feat/T2-extension-ux`  
**Оценка:** ~2.5 дня  
**Приоритет:** 🔴 Критический (визуал для демо-видео + первый коммит разблокирует команду)

---

## Цель

1. Полностью переписать UI Chrome Extension — красивый overlay, step guide с таймером, reset кнопка
2. Реализовать Сценарий 3 end-to-end: форма → wizard (одно поле за раз) с A2-объяснениями
3. **Первым коммитом** зафиксировать новые поля в `schemas.py` — от этого зависят T1 и T5

---

## Файлы в твоём владении

```
extension/content.js
extension/popup/popup.js
extension/popup/popup.html
extension/popup/popup.css
backend/app/schemas/analyze.py
backend/app/agents/action.py
```

> ⚠️ Никто другой эти файлы не трогает.

---

## Шаг 0 — Настройка ветки + ПЕРВЫЙ КОММИТ

```bash
git checkout main && git pull
git checkout -b feat/T2-extension-ux
```

**Сразу после создания ветки** — сделай первый коммит только с изменением `schemas.py`.
Это Контракт 1, от которого зависят T1 и T5.

---

## Шаг 1 — `schemas.py`: добавить поля (ПЕРВЫЙ КОММИТ)

Открой `backend/app/schemas/analyze.py`. Найди класс `AnalyzeResponse` и добавь два поля:

```python
class AnalyzeResponse(BaseModel):
    content_type: ContentType
    transformations: List[DOMTransformation]
    agent_message: str
    preparation_steps: Optional[List[str]] = None
    summary: Optional[str] = None
    processing_time_ms: Optional[int] = None
    hard_terms: Optional[List[str]] = None       # ← NEW: сложные термины из оригинала
    last_visit_info: Optional[dict] = None        # ← NEW: {"days_ago": 2, "url": "..."}
```

Добавить комментарий в `DOMTransformation` для документации:
```python
class DOMTransformation(BaseModel):
    # action допустимые значения:
    # simplify_text | hide_element | apply_font | add_step_guide | wizard_form
    action: str
    selector: Optional[str] = None
    content: Optional[str] = None
    style: Optional[Dict[str, str]] = None
```

```bash
git add backend/app/schemas/analyze.py
git commit -m "feat: add hard_terms and last_visit_info to AnalyzeResponse schema"
git push -u origin feat/T2-extension-ux
```

> Сообщи команде в чат: "T2 schema commit done, можно стартовать T1 и T5"

---

## Шаг 2 — `action.py`: добавить wizard_form трансформацию

В функцию `generate_transformations()` добавить блок перед `return transformations`:

```python
# Wizard form для low_literacy на страницах с формами
if (page_analysis.get("content_type") == "form"
        and (profile_type == "low_literacy" or "wizard_form" in actions)):
    form_fields = page_analysis.get("form_fields", [])
    if form_fields:
        transformations.append(DOMTransformation(
            action="wizard_form",
            content=json.dumps(form_fields, ensure_ascii=False),
        ))
```

В блоке step guide — ускорить Ollama вызов:
```python
# Найди вызов Ollama в блоке add_step_guide и замени options:
"think": False,                                       # ← добавить
"options": {"temperature": 0.4, "num_predict": 200}  # ← было 256
```

---

## Шаг 3 — `content.js`: полный рефакторинг

Замени весь файл следующим кодом:

```javascript
// ClearPath Content Script v2
// Captures DOM, sends to backend, applies accessible transformations

const BACKEND_URL = 'http://localhost:8001';

const STEP_LABELS = {
    analyzer: '🔍 Анализирую страницу...',
    planner_and_writer: '🧠 Адаптирую под твой профиль...',
    action: '⚡ Применяю изменения...',
    cache: '⚡ Загружаю из кэша...',
};

let userProfile = null;
let wsConnection = null;
let _timerInterval = null;

// CSS animations — inject once
const _style = document.createElement('style');
_style.textContent = `
    @keyframes cpFadeIn {
        from { opacity: 0; transform: translateY(-8px); }
        to   { opacity: 1; transform: none; }
    }
    @keyframes cpSlideIn {
        from { opacity: 0; transform: translateX(20px); }
        to   { opacity: 1; transform: none; }
    }
    @keyframes cpSlideUp {
        from { opacity: 0; transform: translateY(20px); }
        to   { opacity: 1; transform: none; }
    }
    #clearpath-reset:hover { background: rgba(30,58,95,0.95) !important; transform: scale(1.05); }
`;
document.head.appendChild(_style);

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

async function init() {
    userProfile = await chrome.storage.local.get(['userId', 'tenantId', 'profileType']);
    if (!userProfile.userId) {
        console.log('ClearPath: No profile. Open popup to set up.');
        return;
    }
    connectWebSocket();
}

// ---------------------------------------------------------------------------
// Network
// ---------------------------------------------------------------------------

function connectWebSocket() {
    wsConnection = new WebSocket(`ws://localhost:8001/api/v1/ws/analyze`);

    wsConnection.onopen = () => {
        console.log('ClearPath: WS connected');
        analyzePage();
    };

    wsConnection.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.status === 'processing') {
            showLoadingIndicator(data.step);
        } else if (data.status === 'done' && data.result) {
            hideLoadingIndicator();
            applyTransformations(data.result);
        } else if (data.status === 'error') {
            hideLoadingIndicator();
            console.error('ClearPath error:', data.message);
        }
    };

    wsConnection.onerror = () => {
        console.log('ClearPath: WS error, falling back to HTTP');
        analyzePageHTTP();
    };
}

function captureDOM() {
    const body = document.body.cloneNode(true);
    ['script', 'style', 'nav', 'header', 'footer', 'aside'].forEach(tag => {
        body.querySelectorAll(tag).forEach(el => el.remove());
    });
    return body.innerText.replace(/\s+/g, ' ').trim().substring(0, 5000);
}

async function captureScreenshot() {
    return new Promise((resolve) => {
        chrome.runtime.sendMessage({ action: 'captureScreenshot' }, (response) => {
            resolve(response?.screenshot || null);
        });
    });
}

async function analyzePage() {
    const domText = captureDOM();
    const screenshot = await captureScreenshot();

    const payload = {
        user_id: userProfile.userId,
        tenant_id: userProfile.tenantId || 'default',
        url: window.location.href,
        page_title: document.title,
        dom_text: domText,
        screenshot_base64: screenshot,
    };

    if (wsConnection?.readyState === WebSocket.OPEN) {
        wsConnection.send(JSON.stringify(payload));
    } else {
        analyzePageHTTP(payload);
    }
}

async function analyzePageHTTP(payload = null) {
    if (!payload) {
        payload = {
            user_id: userProfile.userId,
            tenant_id: userProfile.tenantId || 'default',
            url: window.location.href,
            page_title: document.title,
            dom_text: captureDOM(),
            screenshot_base64: await captureScreenshot(),
        };
    }
    try {
        const response = await fetch(`${BACKEND_URL}/api/v1/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const result = await response.json();
        applyTransformations(result);
    } catch (error) {
        console.error('ClearPath: HTTP analysis failed', error);
    }
}

// ---------------------------------------------------------------------------
// Apply transformations
// ---------------------------------------------------------------------------

function applyTransformations(result) {
    if (!result?.transformations) return;

    result.transformations.forEach(t => {
        try {
            switch (t.action) {
                case 'apply_font':    applyFont(t);    break;
                case 'hide_element':  hideElement(t);  break;
                case 'simplify_text': simplifyText(t); break;
                case 'add_step_guide':addStepGuide(t); break;
                case 'wizard_form':   wizardForm(t);   break;
            }
        } catch (e) {
            console.warn('ClearPath: transformation failed', t.action, e);
        }
    });

    showAgentMessage(result);
    addResetButton();
}

// ---------------------------------------------------------------------------
// Transformations
// ---------------------------------------------------------------------------

function applyFont(t) {
    const elements = t.selector
        ? document.querySelectorAll(t.selector)
        : [document.body];
    elements.forEach(el => {
        if (t.style) Object.assign(el.style, t.style);
    });
}

function hideElement(t) {
    if (!t.selector) return;
    document.querySelectorAll(t.selector).forEach(el => {
        if (!el.dataset.clearpathHidden) {
            // Сохранить оригинальный display для Reset
            el.dataset.clearpathHidden = el.style.display || getComputedStyle(el).display || 'block';
            el.style.display = 'none';
        }
    });
}

function simplifyText(t) {
    document.getElementById('clearpath-simplified')?.remove();
    if (!t.content) return;

    const paragraphs = t.content
        .split('\n')
        .filter(p => p.trim())
        .map(p => `<p style="margin:0 0 10px 0">${p.trim()}</p>`)
        .join('');

    const overlay = document.createElement('div');
    overlay.id = 'clearpath-simplified';
    overlay.style.cssText = `
        background: rgba(255,249,240,0.97);
        backdrop-filter: blur(8px);
        border: 2px solid #2E86C1;
        border-radius: 12px;
        padding: 20px 24px;
        margin: 16px 0;
        font-size: 17px;
        line-height: 1.85;
        font-family: Arial, sans-serif;
        box-shadow: 0 4px 20px rgba(46,134,193,0.15);
        position: relative;
        z-index: 1000;
        animation: cpFadeIn 0.3s ease;
    `;

    overlay.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
            <span style="font-size:12px;color:#2E86C1;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;">
                ✓ ClearPath — упрощено для тебя
            </span>
            <button onclick="this.closest('#clearpath-simplified').remove()"
                style="background:none;border:none;cursor:pointer;color:#aaa;font-size:20px;line-height:1;padding:0;"
                title="Закрыть">×</button>
        </div>
        <div id="cp-simplified-text">${paragraphs}</div>
        <div id="cp-original-text" style="display:none;color:#666;font-size:15px;border-top:1px solid #e0e0e0;margin-top:12px;padding-top:12px;">
            ${(t.originalText || '').replace(/\n/g,'<br>')}
        </div>
        <button onclick="cpToggleOriginal(this)"
            style="margin-top:10px;background:none;border:1px solid #ccc;border-radius:6px;
                   padding:4px 12px;font-size:12px;color:#666;cursor:pointer;">
            Показать оригинал
        </button>
    `;

    const target = document.querySelector(t.selector || 'main, article, .content, #content');
    if (target) target.insertAdjacentElement('beforebegin', overlay);
    else document.body.prepend(overlay);
}

window.cpToggleOriginal = function(btn) {
    const orig = document.getElementById('cp-original-text');
    const simp = document.getElementById('cp-simplified-text');
    if (!orig) return;
    const showing = orig.style.display !== 'none';
    orig.style.display = showing ? 'none' : '';
    simp.style.display = showing ? '' : 'none';
    btn.textContent = showing ? 'Показать оригинал' : 'Скрыть оригинал';
};

function addStepGuide(t) {
    document.getElementById('clearpath-steps')?.remove();
    if (!t.content) return;

    let steps;
    try { steps = JSON.parse(t.content); }
    catch { steps = [t.content]; }

    const stepItems = steps.map((s, i) => `
        <li style="margin-bottom:10px;font-size:14px;display:flex;gap:10px;align-items:flex-start;">
            <span style="background:#2E86C1;color:white;border-radius:50%;
                         min-width:22px;height:22px;display:flex;align-items:center;
                         justify-content:center;font-size:12px;font-weight:700;">${i + 1}</span>
            <span style="line-height:1.4;">${s}</span>
        </li>`).join('');

    const guide = document.createElement('div');
    guide.id = 'clearpath-steps';
    guide.style.cssText = `
        background: #EBF5FB;
        border: 2px solid #2E86C1;
        border-radius: 12px;
        padding: 20px;
        position: fixed;
        top: 80px; right: 20px;
        width: 290px;
        z-index: 10000;
        box-shadow: 0 8px 24px rgba(0,0,0,0.12);
        font-family: Arial, sans-serif;
        animation: cpSlideIn 0.3s ease;
    `;

    guide.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
            <div style="font-weight:700;color:#1E3A5F;font-size:15px;">📋 План подготовки</div>
            <button onclick="document.getElementById('clearpath-steps').remove()"
                style="background:none;border:none;cursor:pointer;color:#aaa;font-size:20px;padding:0;">×</button>
        </div>
        <ol style="margin:0 0 16px;padding:0;list-style:none;">${stepItems}</ol>
        <div style="text-align:center;background:white;border-radius:8px;padding:12px;margin-bottom:12px;">
            <div style="font-size:26px;font-weight:700;color:#1E3A5F;font-variant-numeric:tabular-nums;"
                 id="cp-timer-display">25:00</div>
            <div style="font-size:11px;color:#999;margin-bottom:6px;">Таймер фокуса (Pomodoro)</div>
            <button id="cp-timer-btn" onclick="cpToggleTimer()"
                style="background:#2E86C1;color:white;border:none;border-radius:6px;
                       padding:6px 18px;cursor:pointer;font-size:13px;">
                ▶ Старт
            </button>
        </div>
        <button onclick="document.getElementById('clearpath-steps').remove()"
            style="width:100%;padding:10px;background:#1E3A5F;color:white;border:none;
                   border-radius:8px;cursor:pointer;font-size:14px;font-weight:600;">
            Готов! Начать →
        </button>
    `;

    document.body.appendChild(guide);
}

window.cpToggleTimer = function() {
    const display = document.getElementById('cp-timer-display');
    const btn = document.getElementById('cp-timer-btn');
    if (!display || !btn) return;

    if (_timerInterval) {
        clearInterval(_timerInterval);
        _timerInterval = null;
        btn.textContent = '▶ Старт';
        return;
    }

    let secs = 25 * 60;
    btn.textContent = '⏸ Пауза';

    _timerInterval = setInterval(() => {
        secs--;
        if (secs <= 0) {
            clearInterval(_timerInterval);
            _timerInterval = null;
            display.textContent = '🎉 Готово!';
            btn.textContent = '▶ Заново';
            return;
        }
        const m = String(Math.floor(secs / 60)).padStart(2, '0');
        const s = String(secs % 60).padStart(2, '0');
        display.textContent = `${m}:${s}`;
    }, 1000);
};

// ---------------------------------------------------------------------------
// Wizard Form — Scenario 3
// ---------------------------------------------------------------------------

function wizardForm(t) {
    document.getElementById('clearpath-wizard')?.remove();
    if (!t.content) return;

    let fields;
    try { fields = JSON.parse(t.content); }
    catch { return; }
    if (!fields.length) return;

    let currentStep = 0;

    // Скрыть все поля кроме первого
    const getFieldWrapper = (selector) =>
        document.querySelector(selector)?.closest('.form-group, .field, .form-row, li, p, div[class*="field"]')
        || document.querySelector(selector)?.parentElement;

    fields.forEach((f, i) => {
        const wrapper = getFieldWrapper(f.selector);
        if (wrapper && i > 0) {
            wrapper.style.display = 'none';
            wrapper.dataset.cpWizardHidden = 'true';
        }
    });

    const wizard = document.createElement('div');
    wizard.id = 'clearpath-wizard';
    wizard.style.cssText = `
        position: fixed;
        bottom: 24px; left: 50%; transform: translateX(-50%);
        background: white;
        border: 2px solid #2E86C1;
        border-radius: 14px;
        padding: 22px 26px;
        width: 380px;
        z-index: 10001;
        box-shadow: 0 8px 32px rgba(0,0,0,0.15);
        font-family: Arial, sans-serif;
        animation: cpSlideUp 0.3s ease;
    `;

    function renderStep() {
        const f = fields[currentStep];
        const progress = Math.round((currentStep / fields.length) * 100);
        const isLast = currentStep === fields.length - 1;

        wizard.innerHTML = `
            <div style="font-size:12px;color:#888;margin-bottom:6px;text-align:right;">
                Шаг ${currentStep + 1} из ${fields.length}
            </div>
            <div style="background:#e8e8e8;border-radius:4px;height:4px;margin-bottom:16px;">
                <div style="background:#2E86C1;width:${progress}%;height:100%;
                            border-radius:4px;transition:width 0.4s ease;"></div>
            </div>
            <div style="font-size:17px;font-weight:700;color:#1E3A5F;margin-bottom:8px;">
                ${f.label}${f.required
                    ? ' <span style="color:#e74c3c;font-size:14px;">*</span>'
                    : ' <span style="color:#aaa;font-size:12px;">(необязательно)</span>'}
            </div>
            <div style="font-size:14px;color:#555;margin-bottom:18px;line-height:1.5;
                        background:#f0f7ff;border-radius:8px;padding:10px 12px;">
                💡 ${f.hint || 'Введите информацию в это поле'}
            </div>
            <div style="display:flex;gap:10px;">
                ${currentStep > 0 ? `
                    <button onclick="cpWizardPrev()"
                        style="flex:1;padding:11px;border:1px solid #ddd;border-radius:8px;
                               background:white;cursor:pointer;font-size:14px;color:#555;">
                        ← Назад
                    </button>` : ''}
                <button onclick="cpWizardNext()"
                    style="flex:2;padding:11px;background:#2E86C1;color:white;border:none;
                           border-radius:8px;cursor:pointer;font-size:15px;font-weight:600;">
                    ${isLast ? '✓ Готово' : 'Далее →'}
                </button>
            </div>
        `;

        // Подсветить текущее поле
        const input = document.querySelector(f.selector);
        if (input) {
            input.style.outline = '3px solid #2E86C1';
            input.style.boxShadow = '0 0 0 4px rgba(46,134,193,0.15)';
            input.scrollIntoView({ behavior: 'smooth', block: 'center' });
            setTimeout(() => input.focus(), 300);
        }
    }

    window.cpWizardNext = function() {
        // Убрать подсветку с текущего
        const curInput = document.querySelector(fields[currentStep].selector);
        if (curInput) { curInput.style.outline = ''; curInput.style.boxShadow = ''; }

        const curWrapper = getFieldWrapper(fields[currentStep].selector);
        if (curWrapper) curWrapper.style.display = 'none';

        currentStep++;

        if (currentStep >= fields.length) {
            wizard.remove();
            // Показать все поля обратно перед сабмитом
            document.querySelectorAll('[data-cp-wizard-hidden]').forEach(el => {
                el.style.display = '';
            });
            document.querySelector('form')?.requestSubmit?.();
            return;
        }

        const nextWrapper = getFieldWrapper(fields[currentStep].selector);
        if (nextWrapper) nextWrapper.style.display = '';
        renderStep();
    };

    window.cpWizardPrev = function() {
        const curInput = document.querySelector(fields[currentStep].selector);
        if (curInput) { curInput.style.outline = ''; curInput.style.boxShadow = ''; }

        const curWrapper = getFieldWrapper(fields[currentStep].selector);
        if (curWrapper) curWrapper.style.display = 'none';

        currentStep--;

        const prevWrapper = getFieldWrapper(fields[currentStep].selector);
        if (prevWrapper) prevWrapper.style.display = '';
        renderStep();
    };

    renderStep();
    document.body.appendChild(wizard);
}

// ---------------------------------------------------------------------------
// UI helpers
// ---------------------------------------------------------------------------

function showAgentMessage(result) {
    document.querySelector('.cp-toast')?.remove();

    const parts = [];

    if (result.last_visit_info) {
        const d = result.last_visit_info.days_ago;
        const when = d === 0 ? 'сегодня' : d === 1 ? 'вчера' : `${d} дней назад`;
        parts.push(`📅 Ты был здесь ${when}`);
    }

    if (result.agent_message) {
        parts.push(result.agent_message);
    }

    if (result.hard_terms?.length) {
        parts.push(`🔍 Упрощено: ${result.hard_terms.slice(0, 3).join(', ')}`);
    }

    if (!parts.length) return;

    const toast = document.createElement('div');
    toast.className = 'cp-toast';
    toast.style.cssText = `
        position: fixed;
        bottom: 20px; right: 20px;
        background: #1E3A5F;
        color: white;
        padding: 14px 18px;
        border-radius: 10px;
        z-index: 10001;
        max-width: 320px;
        font-size: 14px;
        line-height: 1.6;
        box-shadow: 0 6px 20px rgba(0,0,0,0.25);
        animation: cpSlideIn 0.3s ease;
        font-family: Arial, sans-serif;
    `;
    toast.innerHTML = `
        <div style="font-weight:700;margin-bottom:4px;font-size:15px;">🧠 ClearPath</div>
        ${parts.map(p => `<div>${p}</div>`).join('')}
    `;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 8000);
}

function showLoadingIndicator(step) {
    let indicator = document.getElementById('clearpath-loading');
    if (!indicator) {
        indicator = document.createElement('div');
        indicator.id = 'clearpath-loading';
        indicator.style.cssText = `
            position: fixed; top: 12px; right: 12px;
            background: #2E86C1; color: white;
            padding: 8px 14px; border-radius: 20px;
            z-index: 10002; font-size: 13px;
            font-family: Arial, sans-serif;
            box-shadow: 0 3px 12px rgba(46,134,193,0.4);
            animation: cpFadeIn 0.2s ease;
        `;
        document.body.appendChild(indicator);
    }
    indicator.textContent = STEP_LABELS[step] || '⏳ Обрабатываю...';
}

function hideLoadingIndicator() {
    document.getElementById('clearpath-loading')?.remove();
}

function addResetButton() {
    if (document.getElementById('clearpath-reset')) return;

    const btn = document.createElement('button');
    btn.id = 'clearpath-reset';
    btn.textContent = '↩ Reset';
    btn.style.cssText = `
        position: fixed; bottom: 20px; left: 20px;
        z-index: 10002;
        background: rgba(30,58,95,0.85);
        color: white; border: none;
        border-radius: 20px;
        padding: 8px 16px;
        cursor: pointer;
        font-size: 13px;
        font-family: Arial, sans-serif;
        backdrop-filter: blur(4px);
        box-shadow: 0 2px 10px rgba(0,0,0,0.2);
        transition: background 0.2s, transform 0.1s;
    `;

    btn.onclick = () => {
        // Убрать все оверлеи
        ['clearpath-simplified', 'clearpath-steps',
         'clearpath-wizard', 'clearpath-loading',
         'clearpath-reset', '.cp-toast'].forEach(sel => {
            const el = sel.startsWith('#')
                ? document.getElementById(sel.slice(1))
                : document.querySelector(sel);
            el?.remove();
        });

        // Восстановить скрытые элементы
        document.querySelectorAll('[data-clearpath-hidden]').forEach(el => {
            el.style.display = el.dataset.clearpathHidden === 'none' ? '' : el.dataset.clearpathHidden;
            delete el.dataset.clearpathHidden;
        });

        // Восстановить поля формы из wizard
        document.querySelectorAll('[data-cp-wizard-hidden]').forEach(el => {
            el.style.display = '';
            delete el.dataset.cpWizardHidden;
        });

        // Убрать подсветки wizard
        document.querySelectorAll('input[style*="outline"]').forEach(el => {
            el.style.outline = '';
            el.style.boxShadow = '';
        });

        // Остановить таймер
        if (_timerInterval) { clearInterval(_timerInterval); _timerInterval = null; }
    };

    document.body.appendChild(btn);
}

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------
init();
```

---

## Шаг 4 — `popup.html`: добавить секцию истории

Найди закрывающий тег `</body>` и добавь перед ним:

```html
  <div id="cp-history" style="margin-top:14px;display:none;border-top:1px solid #eee;padding-top:12px;">
    <div style="font-size:11px;color:#aaa;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:6px;">
      Последние визиты
    </div>
    <div id="cp-history-list" style="font-size:12px;color:#555;line-height:1.9;"></div>
  </div>
```

---

## Шаг 5 — `popup.js`: добавить загрузку истории

Добавить функцию в конец файла (перед `loadProfile()`):

```javascript
const BACKEND_URL = 'http://localhost:8001';

async function loadHistory(userId) {
    try {
        const r = await fetch(`${BACKEND_URL}/api/v1/profiles/${userId}/history`);
        if (!r.ok) return;
        const data = await r.json();
        if (!data.recent?.length) return;

        const list = document.getElementById('cp-history-list');
        const section = document.getElementById('cp-history');
        if (!list || !section) return;

        list.innerHTML = data.recent
            .slice(-3)
            .reverse()
            .map(h => {
                const d = Math.floor((Date.now() / 1000 - h.timestamp) / 86400);
                const when = d === 0 ? 'сегодня' : d === 1 ? 'вчера' : `${d}д назад`;
                let host = '';
                try { host = new URL(h.url).hostname.replace('www.', ''); } catch { host = h.url; }
                return `<div>• <span style="color:#1E3A5F;font-weight:600">${host}</span>
                            <span style="color:#aaa">(${when})</span></div>`;
            })
            .join('');

        section.style.display = '';
    } catch (e) {
        // Silently ignore if backend unreachable
    }
}

// Обновить loadProfile() — добавить вызов loadHistory в конце:
async function loadProfile() {
    const data = await chrome.storage.local.get(['userId', 'profileType', 'readingLevel']);
    if (data.profileType) document.getElementById('profileType').value = data.profileType;
    if (data.readingLevel) document.getElementById('readingLevel').value = data.readingLevel;
    if (data.userId) {
        document.getElementById('status').textContent = `✓ Активен — ID: ${data.userId.substring(0, 8)}...`;
        loadHistory(data.userId);  // ← добавить
    }
}
```

---

## Definition of Done

- [ ] **Первый коммит** с `schemas.py` запушен до начала работы над остальным
- [ ] Overlay на Wikipedia показывает красивый блок с кнопкой × и toggle оригинала
- [ ] Кнопка Reset восстанавливает страницу в исходное состояние полностью
- [ ] Step guide показывает карточку с нумерованными шагами и таймером Pomodoro
- [ ] Таймер: Start → отсчёт → Пауза → продолжение → по истечении "🎉 Готово!"
- [ ] На `httpbin.org/forms/post` wizard показывает поля по одному с подсветкой
- [ ] Toast в правом нижнем углу показывает last_visit_info и hard_terms (если есть)
- [ ] В popup'е отображается история последних 3 визитов
- [ ] Нет JavaScript ошибок в консоли при работе на Wikipedia и httpbin

---

## Тест wizard вручную

```
1. Открыть https://httpbin.org/forms/post
2. Нажать кнопку расширения → Activate
3. Подождать анализ (~25s)
4. Убедиться что появился wizard overlay снизу
5. Кликать "Далее →" — каждое поле открывается по одному
6. "← Назад" возвращает к предыдущему
7. На последнем поле кнопка называется "✓ Готово"
```
