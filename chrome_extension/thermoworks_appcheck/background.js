async function getJob() {
  const stored = await chrome.storage.session.get('twAppCheckJob');
  const job = stored && stored.twAppCheckJob;
  if (!job || !job.bridgeId || !job.submitUrl) {
    return null;
  }
  if (Date.now() - (job.createdAt || 0) > 15 * 60 * 1000) {
    await chrome.storage.session.remove('twAppCheckJob');
    return null;
  }
  return job;
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || !message.type) {
    return;
  }

  if (message.type === 'tw-appcheck-start') {
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
      await chrome.tabs.update(tabId, {
        url: 'https://cloud.thermoworks.com/auth/login',
        active: true
      });
      sendResponse({ ok: true, tabId });
    });
    return true;
  }

  if (message.type === 'tw-appcheck-get-job') {
    getJob().then((job) => sendResponse({ ok: true, job }));
    return true;
  }

  if (message.type === 'tw-appcheck-submit') {
    (async () => {
      const job = await getJob();
      if (!job) {
        sendResponse({ ok: false, error: 'No pending App Check job' });
        return;
      }
      try {
        const save = await fetch(job.submitUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({
            token: message.token,
            ttl: message.ttl || '3600s',
            bridge_id: job.bridgeId
          })
        });
        const body = await save.json().catch(() => ({}));
        if (!save.ok) {
          sendResponse({ ok: false, error: body.error || ('HTTP ' + save.status) });
          return;
        }
        await chrome.storage.session.remove('twAppCheckJob');
        const tabId = sender.tab && sender.tab.id;
        if (tabId && job.returnUrl) {
          await chrome.tabs.update(tabId, { url: job.returnUrl, active: true });
        }
        sendResponse({ ok: true });
      } catch (err) {
        sendResponse({ ok: false, error: String(err && err.message ? err.message : err) });
      }
    })();
    return true;
  }
});

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (changeInfo.status !== 'complete' || !tab.url) {
    return;
  }
  if (!tab.url.startsWith('https://cloud.thermoworks.com/')) {
    return;
  }
  const job = await getJob();
  if (!job) {
    return;
  }
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ['thermoworks_content.js']
    });
  } catch (e) {
    // content_scripts match still covers normal loads
  }
});
