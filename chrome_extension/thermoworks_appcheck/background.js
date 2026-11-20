chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || message.type !== 'tw-appcheck-start') {
    return;
  }

  const tabId = sender.tab && sender.tab.id;
  if (!tabId) {
    sendResponse({ ok: false, error: 'No tab to reuse' });
    return;
  }

  const job = {
    bridgeId: message.bridgeId,
    submitUrl: message.submitUrl,
    returnUrl: message.returnUrl || '',
    createdAt: Date.now()
  };

  chrome.storage.session.set({ twAppCheckJob: job }).then(async () => {
    // Same popup/tab. Prefer the login page where reCAPTCHA is present.
    await chrome.tabs.update(tabId, {
      url: 'https://cloud.thermoworks.com/auth/login',
      active: true
    });
    sendResponse({ ok: true, tabId });
  });
  return true;
});

// If ThermoWorks navigates within the SPA, retry while a job is pending.
chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (changeInfo.status !== 'complete' || !tab.url) {
    return;
  }
  if (!tab.url.startsWith('https://cloud.thermoworks.com/')) {
    return;
  }
  const stored = await chrome.storage.session.get('twAppCheckJob');
  if (!stored.twAppCheckJob) {
    return;
  }
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ['thermoworks_content.js']
    });
  } catch (e) {
    // Tab may not allow scripting yet; content_scripts match will still run on load.
  }
});
