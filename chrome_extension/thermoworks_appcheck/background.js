// Chrome extension service worker.
// dashboard_bridge.js asks it to open cloud.thermoworks.com in the same tab,
// mint a Firebase App Check token in the page, and POST {token, ttl, bridge_id}
// to the dashboard submit URL. A stored job older than 15 minutes is dropped.
// During a run, static/run_watch.js asks for 'tw-appcheck-renew' before the
// ~1 h token expires; that mints in a hidden background tab instead.

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

async function saveJob(job) {
  await chrome.storage.session.set({ twAppCheckJob: job });
}

async function mintInPage(tabId) {
  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId },
    world: 'MAIN',
    func: async () => {
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      let g = null;
      for (let i = 0; i < 40; i += 1) {
        g = window.grecaptcha && window.grecaptcha.enterprise;
        if (g) {
          break;
        }
        await sleep(400);
      }
      if (!g) {
        return { ok: false, error: 'reCAPTCHA not found on this page' };
      }
      try {
        const ids = Object.keys((window.___grecaptcha_cfg || {}).clients || {});
        const widgetId = ids.length ? Number(ids[0]) : 0;
        const recaptcha = await new Promise((resolve, reject) => {
          g.ready(() => {
            g.execute(widgetId, { action: 'fire_app_check' }).then(resolve).catch(reject);
          });
        });
        const url =
          'https://content-firebaseappcheck.googleapis.com/v1/projects/' +
          'thermoworks-cloud-production/apps/1:78998049458:web:b41e9d405d8c7de95eefab' +
          ':exchangeRecaptchaEnterpriseToken?key=AIzaSyCf079iccUFc1k7VHdGXng22zXDy8Y3KEY';
        const resp = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ recaptcha_enterprise_token: recaptcha })
        });
        const body = await resp.json().catch(() => ({}));
        if (!resp.ok || !body.token) {
          return {
            ok: false,
            error: (body.error && body.error.message) || ('exchange HTTP ' + resp.status)
          };
        }
        return { ok: true, token: body.token, ttl: body.ttl || '3600s' };
      } catch (err) {
        return { ok: false, error: String(err && err.message ? err.message : err) };
      }
    }
  });
  return result || { ok: false, error: 'No result from page' };
}

async function postToken(job, token, ttl) {
  const save = await fetch(job.submitUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({
      token,
      ttl: ttl || '3600s',
      bridge_id: job.bridgeId
    })
  });
  const body = await save.json().catch(() => ({}));
  if (!save.ok) {
    throw new Error(body.error || ('Submit HTTP ' + save.status + ' to ' + job.submitUrl));
  }
}

async function submitAndReturn(tabId, job, token, ttl) {
  await postToken(job, token, ttl);
  await chrome.storage.session.remove('twAppCheckJob');
  if (job.returnUrl) {
    await chrome.tabs.update(tabId, { url: job.returnUrl, active: true });
  }
}

const mintingTabs = new Set();
// Hidden tabs opened by renewInBackground; the interactive flow leaves them alone.
const renewTabs = new Set();
let renewRunning = null;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function waitForTabComplete(tabId, timeoutMs) {
  return new Promise((resolve, reject) => {
    let finished = false;
    const finish = (err) => {
      if (finished) {
        return;
      }
      finished = true;
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(listener);
      if (err) {
        reject(err);
      } else {
        resolve();
      }
    };
    const timer = setTimeout(
      () => finish(new Error('cloud.thermoworks.com did not finish loading')),
      timeoutMs
    );
    function listener(id, info) {
      if (id === tabId && info.status === 'complete') {
        finish();
      }
    }
    chrome.tabs.onUpdated.addListener(listener);
    // The tab may have finished before the listener was added.
    chrome.tabs.get(tabId).then((tab) => {
      if (tab && tab.status === 'complete') {
        finish();
      }
    }).catch((err) => finish(err));
  });
}

// Renew the token during a run without touching the user's tabs: open
// ThermoWorks in a background tab, mint there, POST to the dashboard, close it.
async function renewInBackground(job, windowId) {
  const create = { url: 'https://cloud.thermoworks.com/auth/login', active: false };
  if (windowId !== undefined) {
    create.windowId = windowId;
  }
  const tab = await chrome.tabs.create(create);
  renewTabs.add(tab.id);
  try {
    await waitForTabComplete(tab.id, 45000);
    await sleep(2000);
    let minted = await mintInPage(tab.id);
    if (!minted.ok) {
      // reCAPTCHA can load late in a background tab; give it one more try.
      await sleep(4000);
      minted = await mintInPage(tab.id);
    }
    if (!minted.ok) {
      throw new Error(minted.error || 'App Check mint failed');
    }
    await postToken(job, minted.token, minted.ttl);
    console.info('[TW App Check Helper] background renewal posted to', job.submitUrl);
    return { ok: true };
  } finally {
    renewTabs.delete(tab.id);
    chrome.tabs.remove(tab.id).catch(() => {});
  }
}

async function tryMintForTab(tabId, tabUrl) {
  if (mintingTabs.has(tabId) || renewTabs.has(tabId)) {
    return;
  }
  if (!tabUrl || !tabUrl.startsWith('https://cloud.thermoworks.com/')) {
    return;
  }
  const job = await getJob();
  if (!job) {
    return;
  }

  mintingTabs.add(tabId);
  try {
    // Give SPA a moment to load reCAPTCHA widgets.
    await new Promise((r) => setTimeout(r, 1500));
    const minted = await mintInPage(tabId);
    if (minted.ok) {
      await submitAndReturn(tabId, job, minted.token, minted.ttl);
      console.info('[TW App Check Helper] token posted to', job.submitUrl);
      return;
    }

    console.warn('[TW App Check Helper] mint failed:', minted.error);

    // One redirect to login if reCAPTCHA missing on /home (already signed in).
    const needLogin =
      String(minted.error || '').includes('reCAPTCHA') &&
      !tabUrl.includes('/auth/login') &&
      (job.loginRedirects || 0) < 1;
    if (needLogin) {
      job.loginRedirects = (job.loginRedirects || 0) + 1;
      await saveJob(job);
      await chrome.tabs.update(tabId, {
        url: 'https://cloud.thermoworks.com/auth/login',
        active: true
      });
    }
  } catch (err) {
    console.error('[TW App Check Helper]', err);
  } finally {
    mintingTabs.delete(tabId);
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || message.type !== 'tw-appcheck-renew') {
    return;
  }
  if (!message.bridgeId || !message.submitUrl) {
    sendResponse({ ok: false, error: 'bridgeId and submitUrl are required' });
    return;
  }
  // Several open dashboard tabs may ask at once; share one renewal.
  if (!renewRunning) {
    const job = { bridgeId: message.bridgeId, submitUrl: message.submitUrl };
    const windowId = sender.tab ? sender.tab.windowId : undefined;
    renewRunning = renewInBackground(job, windowId)
      .catch((err) => ({ ok: false, error: String(err && err.message ? err.message : err) }))
      .finally(() => {
        renewRunning = null;
      });
  }
  renewRunning.then(sendResponse);
  return true;
});

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
    createdAt: Date.now(),
    loginRedirects: 0
  };
  chrome.storage.session.set({ twAppCheckJob: job }).then(async () => {
    await chrome.tabs.update(tabId, {
      url: 'https://cloud.thermoworks.com/auth/login',
      active: true
    });
    sendResponse({ ok: true, tabId });
  });
  return true;
});

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (changeInfo.status !== 'complete') {
    return;
  }
  await tryMintForTab(tabId, tab.url || '');
});
