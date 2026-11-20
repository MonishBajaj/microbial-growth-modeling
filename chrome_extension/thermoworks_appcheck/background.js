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
    // Stay in the same popup/tab — do not open a second browser window.
    await chrome.tabs.update(tabId, {
      url: 'https://cloud.thermoworks.com/auth/login',
      active: true
    });
    sendResponse({ ok: true, tabId });
  });
  return true;
});
