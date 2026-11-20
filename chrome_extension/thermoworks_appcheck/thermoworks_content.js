/**
 * Content scripts cannot see the page's window.grecaptcha (isolated world).
 * Inject a page-world script to mint App Check, then POST the token to Render.
 */
(async () => {
  const stored = await chrome.storage.session.get('twAppCheckJob');
  const job = stored && stored.twAppCheckJob;
  if (!job || !job.bridgeId || !job.submitUrl) {
    return;
  }
  if (Date.now() - (job.createdAt || 0) > 15 * 60 * 1000) {
    await chrome.storage.session.remove('twAppCheckJob');
    return;
  }

  function injectAndMint() {
    return new Promise((resolve) => {
      const marker = 'tw-appcheck-page-result';
      function onMessage(event) {
        if (event.source !== window || !event.data || event.data.source !== marker) {
          return;
        }
        window.removeEventListener('message', onMessage);
        resolve(event.data);
      }
      window.addEventListener('message', onMessage);

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
      post({ ok: false, error: 'reCAPTCHA not on this ThermoWorks page yet. Stay on the login page a few seconds.' });
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
      return;
    }

    const save = await fetch(job.submitUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({
        token: result.token,
        ttl: result.ttl || '3600s',
        bridge_id: job.bridgeId
      })
    });
    if (!save.ok) {
      const saved = await save.json().catch(() => ({}));
      console.error('[TW App Check Helper] submit to Render failed', saved);
      return;
    }

    await chrome.storage.session.remove('twAppCheckJob');
    if (job.returnUrl) {
      window.location.href = job.returnUrl;
    }
  } catch (err) {
    console.error('[TW App Check Helper]', err);
  }
})();
