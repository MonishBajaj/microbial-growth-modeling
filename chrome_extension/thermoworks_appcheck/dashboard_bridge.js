(() => {
  document.documentElement.dataset.twAppcheckHelper = '1';

  window.addEventListener('message', (event) => {
    if (event.source !== window || !event.data || event.data.source !== 'tw-dashboard') {
      return;
    }
    if (event.data.type !== 'tw-appcheck-request') {
      return;
    }
    const bridgeId = event.data.bridgeId;
    const submitUrl = event.data.submitUrl;
    const returnUrl = event.data.returnUrl;
    if (!bridgeId || !submitUrl) {
      return;
    }
    chrome.runtime.sendMessage(
      {
        type: 'tw-appcheck-start',
        bridgeId,
        submitUrl,
        returnUrl
      },
      (response) => {
        window.postMessage(
          {
            source: 'tw-helper',
            type: 'tw-appcheck-helper-result',
            ok: !!(response && response.ok),
            error: chrome.runtime.lastError ? chrome.runtime.lastError.message : null
          },
          '*'
        );
      }
    );
  });
})();
