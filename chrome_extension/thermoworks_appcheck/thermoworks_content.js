/**
 * Do not use chrome.storage here — it throws
 * "Access to storage is not allowed from this context" on some ThermoWorks pages.
 * Job + Render POST live in the background service worker.
 *
 * Page-world injection is required because content scripts cannot see window.grecaptcha.
 */
(async () => {
  if (window.__twAppCheckRunning) {
    return;
  }
  window.__twAppCheckRunning = true;

  function ask(type, extra) {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage(Object.assign({ type }, extra || {}), (response) => {
        if (chrome.runtime.lastError) {
          resolve({ ok: false, error: chrome.runtime.lastError.message });
          return;
        }
        resolve(response || { ok: false });
      });
    });
  }

  const jobResp = await ask('tw-appcheck-get-job');
  if (!jobResp.ok || !jobResp.job) {
    window.__twAppCheckRunning = false;
    return;
  }

  function injectAndMint() {
    return new Promise((resolve) => {
      const marker = 'tw-appcheck-page-result';
      let settled = false;
      function finish(data) {
        if (settled) return;
        settled = true;
        window.removeEventListener('message', onMessage);
        resolve(data);
      }
      function onMessage(event) {
        if (event.source !== window || !event.data || event.data.source !== marker) {
          return;
        }
        finish(event.data);
      }
      window.addEventListener('message', onMessage);
      setTimeout(() => finish({ ok: false, error: 'Timed out waiting for reCAPTCHA on ThermoWorks' }), 25000);

      const script = document.createElement('script');
      script.textContent = `
(() => {
  const marker = ${JSON.stringify(marker)};
  const post = (payload) => window.postMessage(Object.assign({ source: marker }, payload), '*');
  (async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    let g = null;
    for (let i = 0; i < 50; i++) {
      g = window.grecaptcha && window.grecaptcha.enterprise;
      if (g) break;
      await sleep(400);
    }
    if (!g) {
      post({ ok: false, error: 'reCAPTCHA not on this page. Stay on the ThermoWorks login screen.' });
      return;
    }
    try {
      const ids = Object.keys((window.___grecaptcha_cfg || {}).clients || {});
      const widgetId = ids.length ? Number(ids[0]) : 0;
      const recaptcha = await new Promise((resolve, reject) => {
        g.ready(() => g.execute(widgetId, { action: 'fire_app_check' }).then(resolve).catch(reject));
      });
      const url = 'https://content-firebaseappcheck.googleapis.com/v1/projects/'
        + 'thermoworks-cloud-production/apps/1:78998049458:web:b41e9d405d8c7de95eefab'
        + ':exchangeRecaptchaEnterpriseToken?key=AIzaSyCf079iccUFc1k7VHdGXng22zXDy8Y3KEY';
      const resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ recaptcha_enterprise_token: recaptcha })
      });
      const body = await resp.json().catch(() => ({}));
      if (!resp.ok || !body.token) {
        post({ ok: false, error: (body.error && body.error.message) || ('exchange HTTP ' + resp.status) });
        return;
      }
      post({ ok: true, token: body.token, ttl: body.ttl || '3600s' });
    } catch (err) {
      post({ ok: false, error: String(err && err.message ? err.message : err) });
    }
  })();
})();`;
      (document.documentElement || document.head || document.body).appendChild(script);
      script.remove();
    });
  }

  try {
    const result = await injectAndMint();
    if (!result || !result.ok || !result.token) {
      console.error('[TW App Check Helper]', result && result.error);
      window.__twAppCheckRunning = false;
      return;
    }
    const saved = await ask('tw-appcheck-submit', {
      token: result.token,
      ttl: result.ttl || '3600s'
    });
    if (!saved.ok) {
      console.error('[TW App Check Helper] submit failed', saved.error);
    }
  } catch (err) {
    console.error('[TW App Check Helper]', err);
  } finally {
    window.__twAppCheckRunning = false;
  }
})();
