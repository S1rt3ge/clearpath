// ClearPath Content Script v2
// Captures DOM, sends it to the backend, and applies accessible transformations.

const BACKEND_URL = 'http://localhost:8001';

const STEP_LABELS = {
  analyzer: '🔍 Анализирую страницу...',
  planner_and_writer: '🧠 Адаптирую под твой профиль...',
  action: '⚡ Применяю изменения...',
  cache: '⚡ Загружаю из кэша...',
};

let userProfile = null;
let wsConnection = null;
let timerInterval = null;
let timerSeconds = 25 * 60;

injectClearPathStyles();

async function init() {
  userProfile = await chrome.storage.local.get(['userId', 'tenantId', 'profileType']);

  if (!userProfile.userId) {
    console.log('ClearPath: No profile configured. Open popup to set up.');
    return;
  }

  connectWebSocket();
}

function connectWebSocket() {
  wsConnection = new WebSocket('ws://localhost:8001/api/v1/ws/analyze');

  wsConnection.onopen = () => {
    console.log('ClearPath: Connected to backend');
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
    console.log('ClearPath: WebSocket error, falling back to HTTP');
    analyzePageHTTP();
  };
}

function captureDOM() {
  const body = document.body.cloneNode(true);
  ['script', 'style', 'nav', 'header', 'footer', 'aside'].forEach((tag) => {
    body.querySelectorAll(tag).forEach((el) => el.remove());
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
  const payload = {
    user_id: userProfile.userId,
    tenant_id: userProfile.tenantId || 'default',
    url: window.location.href,
    page_title: document.title,
    dom_text: captureDOM(),
    screenshot_base64: await captureScreenshot(),
  };

  if (wsConnection?.readyState === WebSocket.OPEN) {
    wsConnection.send(JSON.stringify(payload));
  } else {
    analyzePageHTTP(payload);
  }
}

async function analyzePageHTTP(payload = null) {
  const requestPayload = payload || {
    user_id: userProfile.userId,
    tenant_id: userProfile.tenantId || 'default',
    url: window.location.href,
    page_title: document.title,
    dom_text: captureDOM(),
    screenshot_base64: await captureScreenshot(),
  };

  try {
    const response = await fetch(`${BACKEND_URL}/api/v1/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestPayload),
    });

    const result = await response.json();
    applyTransformations(result);
  } catch (error) {
    console.error('ClearPath: Analysis failed', error);
  }
}

function applyTransformations(result) {
  if (!result?.transformations) return;

  result.transformations.forEach((transformation) => {
    try {
      switch (transformation.action) {
        case 'apply_font':
          applyFont(transformation);
          break;
        case 'hide_element':
          hideElement(transformation);
          break;
        case 'simplify_text':
          simplifyText(transformation);
          break;
        case 'add_step_guide':
          addStepGuide(transformation);
          break;
        case 'wizard_form':
          wizardForm(transformation);
          break;
        default:
          console.debug('ClearPath: unknown transformation', transformation.action);
      }
    } catch (error) {
      console.warn('ClearPath: Transformation failed', transformation.action, error);
    }
  });

  showAgentMessage(result);
  addResetButton();
}

function applyFont(t) {
  const elements = t.selector ? safeQueryAll(t.selector) : [document.body];
  elements.forEach((el) => {
    if (!el.dataset.cpOriginalStyle) {
      el.dataset.cpOriginalStyle = el.getAttribute('style') || '';
    }
    if (t.style) Object.assign(el.style, t.style);
  });
}

function hideElement(t) {
  if (!t.selector) return;

  safeQueryAll(t.selector).forEach((el) => {
    if (!el.dataset.clearpathHidden) {
      el.dataset.clearpathHidden = el.style.display || getComputedStyle(el).display || 'block';
      el.style.display = 'none';
    }
  });
}

function simplifyText(t) {
  removeById('clearpath-simplified');
  if (!t.content) return;

  const paragraphs = String(t.content)
    .split('\n')
    .filter((paragraph) => paragraph.trim())
    .map((paragraph) => `<p>${escapeHTML(paragraph.trim())}</p>`)
    .join('');

  const overlay = document.createElement('div');
  overlay.id = 'clearpath-simplified';
  overlay.className = 'cp-panel cp-simplified';
  overlay.innerHTML = `
    <div class="cp-panel-header">
      <span>✓ ClearPath — упрощено для тебя</span>
      <button type="button" class="cp-icon-btn" data-cp-close title="Закрыть">×</button>
    </div>
    <div id="cp-simplified-text">${paragraphs}</div>
    <div id="cp-original-text" class="cp-original" hidden></div>
  `;

  overlay.querySelector('[data-cp-close]').addEventListener('click', () => overlay.remove());

  if (t.originalText) {
    const original = overlay.querySelector('#cp-original-text');
    original.textContent = t.originalText;

    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'cp-secondary-btn';
    toggle.textContent = 'Показать оригинал';
    toggle.addEventListener('click', () => {
      const simplified = overlay.querySelector('#cp-simplified-text');
      const showingOriginal = !original.hidden;
      original.hidden = showingOriginal;
      simplified.hidden = !showingOriginal;
      toggle.textContent = showingOriginal ? 'Показать оригинал' : 'Скрыть оригинал';
    });
    overlay.appendChild(toggle);
  }

  const target = safeQuery(t.selector || 'main, article, .content, #content');
  if (target) target.insertAdjacentElement('beforebegin', overlay);
  else document.body.prepend(overlay);
}

function addStepGuide(t) {
  removeById('clearpath-steps');
  if (!t.content) return;
  timerSeconds = 25 * 60;

  let steps;
  try {
    steps = JSON.parse(t.content);
  } catch {
    steps = [String(t.content)];
  }
  if (!Array.isArray(steps) || steps.length === 0) return;

  const guide = document.createElement('div');
  guide.id = 'clearpath-steps';
  guide.className = 'cp-panel cp-steps';
  guide.innerHTML = `
    <div class="cp-panel-header">
      <strong>План подготовки</strong>
      <button type="button" class="cp-icon-btn" data-cp-close title="Закрыть">×</button>
    </div>
    <ol class="cp-step-list">
      ${steps.map((step, index) => `
        <li>
          <span>${index + 1}</span>
          <p>${escapeHTML(String(step))}</p>
        </li>
      `).join('')}
    </ol>
    <div class="cp-timer">
      <div id="cp-timer-display">25:00</div>
      <small>Таймер фокуса</small>
      <button type="button" id="cp-timer-btn">Старт</button>
    </div>
    <button type="button" class="cp-primary-btn" id="cp-steps-done">Готов! Начать</button>
  `;

  guide.querySelector('[data-cp-close]').addEventListener('click', closeStepGuide);
  guide.querySelector('#cp-steps-done').addEventListener('click', closeStepGuide);
  guide.querySelector('#cp-timer-btn').addEventListener('click', toggleTimer);

  document.body.appendChild(guide);
}

function closeStepGuide() {
  if (timerInterval) {
    clearInterval(timerInterval);
    timerInterval = null;
  }
  timerSeconds = 25 * 60;
  removeById('clearpath-steps');
}

function wizardForm(t) {
  removeById('clearpath-wizard');
  if (!t.content) return;

  let fields;
  try {
    fields = JSON.parse(t.content);
  } catch {
    return;
  }
  if (!Array.isArray(fields) || fields.length === 0) return;

  const wrappers = fields.map((field) => getFieldWrapper(field.selector));
  wrappers.forEach((wrapper, index) => {
    if (!wrapper) return;
    wrapper.dataset.cpWizardWrapper = 'true';
    if (index > 0) wrapper.style.display = 'none';
  });

  let currentStep = 0;
  const wizard = document.createElement('div');
  wizard.id = 'clearpath-wizard';
  wizard.className = 'cp-panel cp-wizard';

  const renderStep = () => {
    clearWizardHighlights(fields);
    const field = fields[currentStep];
    const isLast = currentStep === fields.length - 1;
    const progress = Math.round(((currentStep + 1) / fields.length) * 100);

    wizard.innerHTML = `
      <div class="cp-wizard-count">Шаг ${currentStep + 1} из ${fields.length}</div>
      <div class="cp-progress"><span style="width:${progress}%"></span></div>
      <div class="cp-wizard-title">
        ${escapeHTML(field.label || 'Поле формы')}
        ${field.required ? '<b>*</b>' : '<small>(необязательно)</small>'}
      </div>
      <div class="cp-wizard-hint">${escapeHTML(field.hint || 'Введите информацию в это поле.')}</div>
      <div class="cp-wizard-actions">
        ${currentStep > 0 ? '<button type="button" class="cp-secondary-btn" id="cp-wizard-prev">Назад</button>' : ''}
        <button type="button" class="cp-primary-btn" id="cp-wizard-next">
          ${isLast ? 'Готово' : 'Далее'}
        </button>
      </div>
    `;

    const prevButton = wizard.querySelector('#cp-wizard-prev');
    if (prevButton) prevButton.addEventListener('click', () => moveWizard(-1));
    wizard.querySelector('#cp-wizard-next').addEventListener('click', () => moveWizard(1));

    const input = safeQuery(field.selector);
    if (input) {
      input.style.outline = '3px solid #2E86C1';
      input.style.boxShadow = '0 0 0 4px rgba(46,134,193,0.15)';
      input.scrollIntoView({ behavior: 'smooth', block: 'center' });
      setTimeout(() => input.focus(), 250);
    }
  };

  const moveWizard = (direction) => {
    const nextStep = currentStep + direction;

    if (nextStep >= fields.length) {
      finishWizard(fields, wizard);
      return;
    }
    if (nextStep < 0) return;

    if (wrappers[currentStep]) wrappers[currentStep].style.display = 'none';
    currentStep = nextStep;
    if (wrappers[currentStep]) wrappers[currentStep].style.display = '';
    renderStep();
  };

  renderStep();
  document.body.appendChild(wizard);
}

function getFieldWrapper(selector) {
  const input = safeQuery(selector);
  if (!input) return null;
  return (
    input.closest('.form-group, .field, .form-row, li, p, div[class*="field"]')
    || input.parentElement
  );
}

function finishWizard(fields, wizard) {
  document.querySelectorAll('[data-cp-wizard-wrapper]').forEach((wrapper) => {
    wrapper.style.display = '';
    delete wrapper.dataset.cpWizardWrapper;
  });
  clearWizardHighlights(fields);
  wizard.remove();
  document.querySelector('form')?.requestSubmit?.();
}

function clearWizardHighlights(fields) {
  fields.forEach((field) => {
    const input = safeQuery(field.selector);
    if (!input) return;
    input.style.outline = '';
    input.style.boxShadow = '';
  });
}

function showAgentMessage(result) {
  document.querySelector('.cp-toast')?.remove();

  const parts = [];
  if (result.last_visit_info) {
    const daysAgo = result.last_visit_info.days_ago;
    const when = daysAgo === 0 ? 'сегодня' : daysAgo === 1 ? 'вчера' : `${daysAgo} дней назад`;
    parts.push(`Ты был здесь ${when}`);
  }
  if (result.agent_message) parts.push(result.agent_message);
  if (result.hard_terms?.length) {
    parts.push(`Упрощено: ${result.hard_terms.slice(0, 3).join(', ')}`);
  }
  if (!parts.length) return;

  const toast = document.createElement('div');
  toast.className = 'cp-toast';
  toast.innerHTML = `
    <strong>ClearPath</strong>
    ${parts.map((part) => `<div>${escapeHTML(String(part))}</div>`).join('')}
  `;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 8000);
}

function showLoadingIndicator(step) {
  let indicator = document.getElementById('clearpath-loading');
  if (!indicator) {
    indicator = document.createElement('div');
    indicator.id = 'clearpath-loading';
    document.body.appendChild(indicator);
  }
  indicator.textContent = STEP_LABELS[step] || '⏳ Обрабатываю...';
}

function hideLoadingIndicator() {
  removeById('clearpath-loading');
}

function addResetButton() {
  if (document.getElementById('clearpath-reset')) return;

  const button = document.createElement('button');
  button.id = 'clearpath-reset';
  button.type = 'button';
  button.textContent = 'Reset';
  button.addEventListener('click', resetClearPath);
  document.body.appendChild(button);
}

function resetClearPath() {
  [
    'clearpath-simplified',
    'clearpath-steps',
    'clearpath-wizard',
    'clearpath-loading',
    'clearpath-reset',
  ].forEach(removeById);
  document.querySelector('.cp-toast')?.remove();

  document.querySelectorAll('[data-clearpath-hidden]').forEach((el) => {
    el.style.display = el.dataset.clearpathHidden === 'none' ? '' : el.dataset.clearpathHidden;
    delete el.dataset.clearpathHidden;
  });

  document.querySelectorAll('[data-cp-original-style]').forEach((el) => {
    const original = el.dataset.cpOriginalStyle;
    if (original) el.setAttribute('style', original);
    else el.removeAttribute('style');
    delete el.dataset.cpOriginalStyle;
  });

  document.querySelectorAll('[data-cp-wizard-wrapper]').forEach((el) => {
    el.style.display = '';
    delete el.dataset.cpWizardWrapper;
  });

  document.querySelectorAll('[style*="outline"]').forEach((el) => {
    el.style.outline = '';
    el.style.boxShadow = '';
  });

  if (timerInterval) {
    clearInterval(timerInterval);
    timerInterval = null;
  }
  timerSeconds = 25 * 60;
}

function toggleTimer() {
  const display = document.getElementById('cp-timer-display');
  const button = document.getElementById('cp-timer-btn');
  if (!display || !button) return;

  if (timerInterval) {
    clearInterval(timerInterval);
    timerInterval = null;
    button.textContent = 'Старт';
    return;
  }

  button.textContent = 'Пауза';
  timerInterval = setInterval(() => {
    timerSeconds -= 1;
    if (timerSeconds <= 0) {
      clearInterval(timerInterval);
      timerInterval = null;
      display.textContent = 'Готово!';
      button.textContent = 'Заново';
      timerSeconds = 25 * 60;
      return;
    }
    display.textContent = formatTimer(timerSeconds);
  }, 1000);
}

function formatTimer(seconds) {
  const minutes = String(Math.floor(seconds / 60)).padStart(2, '0');
  const rest = String(seconds % 60).padStart(2, '0');
  return `${minutes}:${rest}`;
}

function injectClearPathStyles() {
  if (document.getElementById('clearpath-style')) return;

  const style = document.createElement('style');
  style.id = 'clearpath-style';
  style.textContent = `
    @keyframes cpFadeIn {
      from { opacity: 0; transform: translateY(-8px); }
      to { opacity: 1; transform: none; }
    }
    @keyframes cpSlideIn {
      from { opacity: 0; transform: translateX(20px); }
      to { opacity: 1; transform: none; }
    }
    @keyframes cpSlideUp {
      from { opacity: 0; transform: translate(-50%, 20px); }
      to { opacity: 1; transform: translateX(-50%); }
    }
    .cp-panel {
      box-sizing: border-box;
      font-family: Arial, sans-serif;
      color: #1E3A5F;
      z-index: 10000;
    }
    .cp-panel *, .cp-toast *, #clearpath-reset {
      box-sizing: border-box;
    }
    .cp-panel-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
      font-size: 13px;
      font-weight: 700;
      color: #2E86C1;
    }
    .cp-icon-btn {
      border: 0;
      background: transparent;
      color: #667;
      cursor: pointer;
      font-size: 22px;
      line-height: 1;
      padding: 0 4px;
    }
    .cp-primary-btn, .cp-secondary-btn, #cp-timer-btn {
      border-radius: 8px;
      cursor: pointer;
      font-size: 14px;
      padding: 9px 14px;
    }
    .cp-primary-btn, #cp-timer-btn {
      background: #2E86C1;
      border: 1px solid #2E86C1;
      color: white;
      font-weight: 700;
    }
    .cp-secondary-btn {
      background: white;
      border: 1px solid #ccd5dd;
      color: #46515c;
    }
    .cp-simplified {
      background: rgba(255,249,240,0.97);
      border: 2px solid #2E86C1;
      border-radius: 12px;
      box-shadow: 0 4px 20px rgba(46,134,193,0.15);
      font-size: 17px;
      line-height: 1.85;
      margin: 16px 0;
      padding: 20px 24px;
      position: relative;
      animation: cpFadeIn 0.3s ease;
    }
    .cp-simplified p {
      margin: 0 0 10px;
    }
    .cp-original {
      border-top: 1px solid #e0e0e0;
      color: #666;
      font-size: 15px;
      margin-top: 12px;
      padding-top: 12px;
      white-space: pre-line;
    }
    .cp-steps {
      background: #EBF5FB;
      border: 2px solid #2E86C1;
      border-radius: 12px;
      box-shadow: 0 8px 24px rgba(0,0,0,0.12);
      padding: 20px;
      position: fixed;
      right: 20px;
      top: 80px;
      width: 300px;
      animation: cpSlideIn 0.3s ease;
    }
    .cp-step-list {
      list-style: none;
      margin: 0 0 16px;
      padding: 0;
    }
    .cp-step-list li {
      align-items: flex-start;
      display: flex;
      gap: 10px;
      margin-bottom: 10px;
    }
    .cp-step-list span {
      align-items: center;
      background: #2E86C1;
      border-radius: 50%;
      color: white;
      display: flex;
      flex: 0 0 22px;
      font-size: 12px;
      font-weight: 700;
      height: 22px;
      justify-content: center;
    }
    .cp-step-list p {
      color: #26323d;
      font-size: 14px;
      line-height: 1.45;
      margin: 0;
    }
    .cp-timer {
      background: white;
      border-radius: 8px;
      margin-bottom: 12px;
      padding: 12px;
      text-align: center;
    }
    #cp-timer-display {
      color: #1E3A5F;
      font-size: 26px;
      font-variant-numeric: tabular-nums;
      font-weight: 700;
    }
    .cp-timer small {
      color: #667;
      display: block;
      margin-bottom: 8px;
    }
    .cp-wizard {
      background: white;
      border: 2px solid #2E86C1;
      border-radius: 14px;
      bottom: 24px;
      box-shadow: 0 8px 32px rgba(0,0,0,0.15);
      left: 50%;
      max-width: calc(100vw - 32px);
      padding: 22px 26px;
      position: fixed;
      transform: translateX(-50%);
      width: 380px;
      animation: cpSlideUp 0.3s ease;
    }
    .cp-wizard-count {
      color: #667;
      font-size: 12px;
      margin-bottom: 6px;
      text-align: right;
    }
    .cp-progress {
      background: #e8edf2;
      border-radius: 4px;
      height: 4px;
      margin-bottom: 16px;
      overflow: hidden;
    }
    .cp-progress span {
      background: #2E86C1;
      display: block;
      height: 100%;
      transition: width 0.25s ease;
    }
    .cp-wizard-title {
      color: #1E3A5F;
      font-size: 17px;
      font-weight: 700;
      margin-bottom: 8px;
    }
    .cp-wizard-title b {
      color: #d14;
    }
    .cp-wizard-title small {
      color: #778;
      font-size: 12px;
      font-weight: 400;
    }
    .cp-wizard-hint {
      background: #f0f7ff;
      border-radius: 8px;
      color: #46515c;
      font-size: 14px;
      line-height: 1.5;
      margin-bottom: 18px;
      padding: 10px 12px;
    }
    .cp-wizard-actions {
      display: flex;
      gap: 10px;
    }
    .cp-wizard-actions button {
      flex: 1;
    }
    .cp-toast {
      animation: cpSlideIn 0.3s ease;
      background: #1E3A5F;
      border-radius: 10px;
      bottom: 20px;
      box-shadow: 0 6px 20px rgba(0,0,0,0.25);
      color: white;
      font-family: Arial, sans-serif;
      font-size: 14px;
      line-height: 1.6;
      max-width: 320px;
      padding: 14px 18px;
      position: fixed;
      right: 20px;
      z-index: 10001;
    }
    .cp-toast strong {
      display: block;
      font-size: 15px;
      margin-bottom: 4px;
    }
    #clearpath-loading {
      animation: cpFadeIn 0.2s ease;
      background: #2E86C1;
      border-radius: 20px;
      box-shadow: 0 3px 12px rgba(46,134,193,0.4);
      color: white;
      font-family: Arial, sans-serif;
      font-size: 13px;
      padding: 8px 14px;
      position: fixed;
      right: 12px;
      top: 12px;
      z-index: 10002;
    }
    #clearpath-reset {
      background: rgba(30,58,95,0.88);
      border: 0;
      border-radius: 20px;
      bottom: 20px;
      box-shadow: 0 2px 10px rgba(0,0,0,0.2);
      color: white;
      cursor: pointer;
      font-family: Arial, sans-serif;
      font-size: 13px;
      left: 20px;
      padding: 8px 16px;
      position: fixed;
      transition: background 0.2s, transform 0.1s;
      z-index: 10002;
    }
    #clearpath-reset:hover {
      background: rgba(30,58,95,0.98);
      transform: scale(1.05);
    }
  `;
  document.head.appendChild(style);
}

function safeQuery(selector) {
  if (!selector) return null;
  try {
    return document.querySelector(selector);
  } catch {
    return null;
  }
}

function safeQueryAll(selector) {
  if (!selector) return [];
  try {
    return Array.from(document.querySelectorAll(selector));
  } catch {
    return [];
  }
}

function removeById(id) {
  document.getElementById(id)?.remove();
}

function escapeHTML(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

init();
