// ClearPath Background Service Worker

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'captureScreenshot') {
    chrome.tabs.captureVisibleTab(null, { format: 'png', quality: 80 }, (dataUrl) => {
      if (chrome.runtime.lastError) {
        sendResponse({ screenshot: null });
        return;
      }
      // Strip data:image/png;base64, prefix
      const base64 = dataUrl.split(',')[1];
      sendResponse({ screenshot: base64 });
    });
    return true; // async response
  }
});
