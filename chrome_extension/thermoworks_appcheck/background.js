chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || message.type !== 'tw-appcheck-start') {
    return;
  }
  const job = {
    bridgeId: message.bridgeId,
    submitUrl: message.submitUrl,
    createdAt: Date.now()
  };
  chrome.storage.session.set({ twAppCheckJob: job }).then(async () => {
    const tab = await chrome.tabs.create({
      url: 'https://cloud.thermoworks.com/auth/login',
      active: true
    });
    sendResponse({ ok: true, tabId: tab.id });
  });
  return true;
});
