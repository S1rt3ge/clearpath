// ClearPath Content Script
// Captures DOM, sends to backend, applies transformations

const BACKEND_URL = 'http://localhost:8001';

let userProfile = null;
let wsConnection = null;

// Initialize on page load
async function init() {
  userProfile = await chrome.storage.local.get(['userId', 'tenantId', 'profileType']);

  if (!userProfile.userId) {
    console.log('ClearPath: No profile configured. Open popup to set up.');
    return;
  }

  connectWebSocket();
}

function connectWebSocket() {
  wsConnection = new WebSocket(`ws://localhost:8001/api/v1/ws/analyze`);

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
    }
  };

  wsConnection.onerror = () => {
    console.log('ClearPath: WebSocket error, falling back to HTTP');
    analyzePageHTTP();
  };
}

function captureDOM() {
  // Extract meaningful text from DOM
  const body = document.body.cloneNode(true);

  // Remove scripts, styles, navs
  ['script', 'style', 'nav', 'header', 'footer', 'aside'].forEach(tag => {
    body.querySelectorAll(tag).forEach(el => el.remove());
  });

  return body.innerText.replace(/\s+/g, ' ').trim().substring(0, 5000);
}

async function captureScreenshot() {
  // Request screenshot from background script
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
    screenshot_base64: screenshot
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
      screenshot_base64: await captureScreenshot()
    };
  }

  try {
    const response = await fetch(`${BACKEND_URL}/api/v1/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    const result = await response.json();
    applyTransformations(result);
  } catch (error) {
    console.error('ClearPath: Analysis failed', error);
  }
}

function applyTransformations(result) {
  if (!result?.transformations) return;

  result.transformations.forEach(transformation => {
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
      }
    } catch (e) {
      console.warn('ClearPath: Transformation failed', transformation.action, e);
    }
  });

  // Show agent message
  if (result.agent_message) {
    showAgentMessage(result.agent_message);
  }
}

function applyFont(t) {
  const elements = t.selector ? document.querySelectorAll(t.selector) : [document.body];
  elements.forEach(el => {
    if (t.style) Object.assign(el.style, t.style);
  });
}

function hideElement(t) {
  if (!t.selector) return;
  document.querySelectorAll(t.selector).forEach(el => {
    el.style.display = 'none';
  });
}

function simplifyText(t) {
  if (!t.content || !t.selector) return;

  const targets = document.querySelectorAll(t.selector);
  if (targets.length === 0) return;

  // Create overlay with simplified text
  const overlay = document.createElement('div');
  overlay.id = 'clearpath-simplified';
  overlay.style.cssText = `
    background: #fff9f0;
    border: 2px solid #2E86C1;
    border-radius: 8px;
    padding: 20px;
    margin: 10px 0;
    font-size: 18px;
    line-height: 1.8;
    font-family: Arial, sans-serif;
    position: relative;
    z-index: 1000;
  `;
  overlay.innerHTML = `
    <div style="font-size:12px;color:#666;margin-bottom:8px;">✓ ClearPath: Simplified for you</div>
    <div>${t.content}</div>
  `;

  targets[0].insertAdjacentElement('beforebegin', overlay);
}

function addStepGuide(t) {
  if (!t.content) return;

  try {
    const steps = JSON.parse(t.content);
    const guide = document.createElement('div');
    guide.id = 'clearpath-steps';
    guide.style.cssText = `
      background: #EBF5FB;
      border: 2px solid #2E86C1;
      border-radius: 8px;
      padding: 20px;
      margin: 10px 0;
      position: fixed;
      top: 80px;
      right: 20px;
      width: 280px;
      z-index: 10000;
      box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    `;
    guide.innerHTML = `
      <div style="font-weight:bold;margin-bottom:12px;color:#1E3A5F;">📋 Your Preparation Steps</div>
      <ol style="margin:0;padding-left:20px;">
        ${steps.map(s => `<li style="margin-bottom:8px;font-size:14px;">${s}</li>`).join('')}
      </ol>
      <button onclick="this.parentElement.remove()" style="
        margin-top:12px;width:100%;padding:6px;
        background:#2E86C1;color:white;border:none;
        border-radius:4px;cursor:pointer;font-size:13px;">
        Got it! Start test
      </button>
    `;
    document.body.appendChild(guide);
  } catch (e) {
    console.warn('ClearPath: Could not parse steps', e);
  }
}

function showAgentMessage(message) {
  const toast = document.createElement('div');
  toast.style.cssText = `
    position: fixed;
    bottom: 20px;
    right: 20px;
    background: #1E3A5F;
    color: white;
    padding: 12px 20px;
    border-radius: 8px;
    z-index: 10001;
    max-width: 300px;
    font-size: 14px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    animation: slideIn 0.3s ease;
  `;
  toast.textContent = `🧠 ClearPath: ${message}`;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 5000);
}

function showLoadingIndicator(step) {
  let indicator = document.getElementById('clearpath-loading');
  if (!indicator) {
    indicator = document.createElement('div');
    indicator.id = 'clearpath-loading';
    indicator.style.cssText = `
      position: fixed; top: 10px; right: 10px;
      background: #2E86C1; color: white;
      padding: 8px 14px; border-radius: 6px;
      z-index: 10002; font-size: 13px;
    `;
    document.body.appendChild(indicator);
  }
  const steps = { analyzer: '🔍 Analyzing...', planner: '🧠 Planning...', writer: '✍️ Simplifying...', action: '⚡ Applying...' };
  indicator.textContent = steps[step] || '⏳ Processing...';
}

function hideLoadingIndicator() {
  document.getElementById('clearpath-loading')?.remove();
}

init();
