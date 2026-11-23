// Runs on the dashboard origin. Listens for window messages from the page
// (source tw-dashboard) and forwards them to background.js:
//   tw-appcheck-request  interactive mint in the same tab (Refresh / popup)
//   tw-appcheck-renew    background renewal during a run (static/run_watch.js)

(() => {
  document.documentElement.dataset.twAppcheckHelper = '1';
  document.documentElement.dataset.twAppcheckHelperRenew = '1';

  window.addEventListener('message', (event) => {
    if (event.source !== window || !event.data || event.data.source !== 'tw-dashboard') {
      return;
    }
    const bridgeId = event.data.bridgeId;
    const submitUrl = event.data.submitUrl;
    if (!bridgeId || !submitUrl) {
      return;
    }

    if (event.data.type === 'tw-appcheck-renew') {
      const requestId = event.data.requestId;
      chrome.runtime.sendMessage(
        { type: 'tw-appcheck-renew', bridgeId, submitUrl },
        (response) => {
          const lastError = chrome.runtime.lastError ? chrome.runtime.lastError.message : null;
          window.postMessage(
            {
              source: 'tw-helper',
              type: 'tw-appcheck-renew-result',
              requestId,
              ok: !!(response && response.ok),
              error: lastError || (response && response.error) || null
            },
            '*'
          );
        }
      );
      return;
    }

    if (event.data.type !== 'tw-appcheck-request') {
      return;
    }
    const returnUrl = event.data.returnUrl;
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
