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

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  let grecaptcha = null;
  for (let i = 0; i < 40; i += 1) {
    grecaptcha = window.grecaptcha && window.grecaptcha.enterprise;
    if (grecaptcha) {
      break;
    }
    await sleep(500);
  }
  if (!grecaptcha) {
    console.warn('[TW App Check Helper] reCAPTCHA not ready yet.');
    return;
  }

  try {
    const ids = Object.keys((window.___grecaptcha_cfg || {}).clients || {});
    const widgetId = ids.length ? Number(ids[0]) : 0;
    const recaptcha = await new Promise((resolve, reject) => {
      grecaptcha.ready(() => {
        grecaptcha.execute(widgetId, { action: 'fire_app_check' }).then(resolve).catch(reject);
      });
    });

    const exchangeUrl =
      'https://content-firebaseappcheck.googleapis.com/v1/projects/' +
      'thermoworks-cloud-production/apps/1:78998049458:web:b41e9d405d8c7de95eefab' +
      ':exchangeRecaptchaEnterpriseToken?key=AIzaSyCf079iccUFc1k7VHdGXng22zXDy8Y3KEY';
    const resp = await fetch(exchangeUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ recaptcha_enterprise_token: recaptcha })
    });
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok || !body.token) {
      console.error('[TW App Check Helper] exchange failed', body);
      return;
    }

    // Normal HTTPS POST to Render — this is the server handoff (not the Console).
    const save = await fetch(job.submitUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({
        token: body.token,
        ttl: body.ttl || '3600s',
        bridge_id: job.bridgeId
      })
    });
    if (!save.ok) {
      const saved = await save.json().catch(() => ({}));
      console.error('[TW App Check Helper] submit failed', saved);
      return;
    }

    await chrome.storage.session.remove('twAppCheckJob');

    // Return to the same popup on our dashboard so the user never needs Console.
    if (job.returnUrl) {
      window.location.href = job.returnUrl;
    }
  } catch (err) {
    console.error('[TW App Check Helper]', err);
  }
})();
