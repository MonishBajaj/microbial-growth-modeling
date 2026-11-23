// Watches the signed-in user's runs from any page that loads it (base.html).
//
// 1. No-data alert: /api/jobs marks a collecting run "stalled" when no new
//    reading has arrived for a few sampling intervals (app._with_data_watch).
//    This shows a banner, a desktop notification and a short beep, and again
//    when readings come back. Works for MEATER, ThermoWorks and every Arduino source.
// 2. ThermoWorks App Check: while a Signals run is active, the ~1 h token is
//    renewed through the Chrome helper (v1.3+) in a hidden background tab
//    before it expires. Without the helper, the banner offers "Renew now".
//
// Browsers slow timers in background tabs to about once a minute, which is
// still well inside the 15-minute renewal margin. The computer must stay awake.

(function () {
    const cfg = window.RUN_WATCH;
    const box = document.getElementById('run-alerts');
    if (!cfg || !box) {
        return;
    }

    const POLL_MS = 30000;
    const RENEW_BEFORE_SEC = 15 * 60;
    const RENEW_RETRY_MS = 3 * 60 * 1000;
    const RENEW_TIMEOUT_MS = 120000;
    const LOCK_KEY = 'twRenewLockUntil';
    const NOTIFIED_KEY = 'runWatchStalled';

    const baseTitle = document.title;
    let jobs = [];
    let stalledIds = new Set(loadNotified());
    let appcheck = null;  // {message, canAutoRenew} when the token needs attention
    let renewing = false;
    let lastRenewFailure = 0;  // retry wait applies only after a failed renewal
    let timer = null;
    let stopped = false;

    // ---- storage helpers (may throw in private windows) ----
    function loadNotified() {
        try {
            return JSON.parse(sessionStorage.getItem(NOTIFIED_KEY) || '[]');
        } catch (e) {
            return [];
        }
    }

    function saveNotified() {
        try {
            sessionStorage.setItem(NOTIFIED_KEY, JSON.stringify(Array.from(stalledIds)));
        } catch (e) {}
    }

    function takeRenewLock() {
        // Several open tabs share one renewal.
        try {
            const until = Number(localStorage.getItem(LOCK_KEY) || 0);
            if (until > Date.now()) {
                return false;
            }
            localStorage.setItem(LOCK_KEY, String(Date.now() + RENEW_TIMEOUT_MS));
        } catch (e) {}
        return true;
    }

    function releaseRenewLock() {
        try {
            localStorage.removeItem(LOCK_KEY);
        } catch (e) {}
    }

    // ---- network ----
    async function getJson(url, options) {
        const response = await fetch(url, Object.assign({
            credentials: 'same-origin',
            headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }
        }, options || {}));
        if (response.status === 401) {
            stopped = true;
            throw new Error('signed out');
        }
        const data = await response.json().catch(function () { return {}; });
        return { ok: response.ok, data: data };
    }

    // ---- formatting ----
    function formatAgo(seconds) {
        const s = Math.max(0, Math.floor(seconds || 0));
        if (s < 90) {
            return s + ' s';
        }
        const m = Math.floor(s / 60);
        if (m < 90) {
            return m + ' min';
        }
        return Math.floor(m / 60) + ' h ' + (m % 60) + ' min';
    }

    function jobName(job) {
        return job.label || job.source || 'Temperature source';
    }

    function runUrl(job) {
        return cfg.statusUrl.replace('__ID__', encodeURIComponent(job.task_id));
    }

    // ---- alerts ----
    function beep() {
        try {
            const Ctx = window.AudioContext || window.webkitAudioContext;
            if (!Ctx) {
                return;
            }
            const ctx = new Ctx();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.frequency.value = 880;
            gain.gain.value = 0.15;
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start();
            osc.stop(ctx.currentTime + 0.35);
            osc.onended = function () { ctx.close(); };
        } catch (e) {}
    }

    function notify(title, body, tag, url, sticky) {
        if (!('Notification' in window) || Notification.permission !== 'granted') {
            return;
        }
        try {
            const n = new Notification(title, { body: body, tag: tag, requireInteraction: !!sticky });
            n.onclick = function () {
                window.focus();
                if (url) {
                    window.location.href = url;
                }
                n.close();
            };
        } catch (e) {}
    }

    function checkTransitions() {
        const running = new Map(jobs.filter(function (j) { return j.running; }).map(function (j) {
            return [j.task_id, j];
        }));
        const nowStalled = new Set();
        jobs.forEach(function (job) {
            if (!job.stalled) {
                return;
            }
            nowStalled.add(job.task_id);
            if (!stalledIds.has(job.task_id)) {
                notify(
                    'No data: ' + jobName(job),
                    'No new temperature reading for ' + formatAgo(job.seconds_since_data) + '. Check the device and its connection.',
                    'run-data-' + job.task_id,
                    runUrl(job),
                    true
                );
                beep();
            }
        });
        stalledIds.forEach(function (id) {
            const job = running.get(id);
            if (!nowStalled.has(id) && job) {
                notify('Data is back: ' + jobName(job), 'Readings are arriving again.', 'run-data-' + id, runUrl(job), false);
            }
        });
        stalledIds = nowStalled;
        saveNotified();
    }

    function button(text, onClick, primary) {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'btn ' + (primary ? 'btn-primary' : 'btn-secondary') + ' run-alert-btn';
        b.textContent = text;
        b.addEventListener('click', onClick);
        return b;
    }

    function alertRow(kind, message, actions) {
        const row = document.createElement('div');
        row.className = 'run-alert run-alert-' + kind;
        row.setAttribute('role', kind === 'warn' ? 'alert' : 'status');
        const text = document.createElement('p');
        text.textContent = message;
        row.appendChild(text);
        if (actions.length) {
            const bar = document.createElement('div');
            bar.className = 'run-alert-actions';
            actions.forEach(function (a) { bar.appendChild(a); });
            row.appendChild(bar);
        }
        return row;
    }

    function openRenewPopup() {
        const popup = window.open(cfg.appcheckPageUrl, 'thermoworksAppCheck', 'popup=yes,width=520,height=640');
        if (!popup) {
            alert('Popup blocked. Allow popups for this site, then click Renew now again.');
            return;
        }
        lastRenewFailure = 0;
        schedule(20000);
    }

    function render() {
        box.innerHTML = '';
        const anyRunning = jobs.some(function (j) { return j.running; });

        jobs.filter(function (j) { return j.stalled; }).forEach(function (job) {
            const actions = [];
            if (!window.location.pathname.endsWith('/' + job.task_id)) {
                const link = document.createElement('a');
                link.href = runUrl(job);
                link.className = 'btn btn-secondary run-alert-btn';
                link.textContent = 'Open run';
                actions.push(link);
            }
            if (job.needs_appcheck) {
                actions.push(button('Renew ThermoWorks access', openRenewPopup, false));
            }
            box.appendChild(alertRow(
                'warn',
                'No new data from ' + jobName(job) + ' for ' + formatAgo(job.seconds_since_data) +
                '. The run is still going and will pick up readings when the source sends again.',
                actions
            ));
        });

        if (appcheck) {
            box.appendChild(alertRow('warn', appcheck.message, [button('Renew now', openRenewPopup, true)]));
        }

        if (anyRunning && 'Notification' in window && Notification.permission === 'default') {
            box.appendChild(alertRow(
                'info',
                'Turn on desktop alerts to hear about a run that stops getting data while this tab is in the background.',
                [button('Enable alerts', function () {
                    Notification.requestPermission().then(render, render);
                }, false)]
            ));
        }

        box.hidden = !box.children.length;
        document.title = stalledIds.size ? '⚠ No data · ' + baseTitle : baseTitle;
    }

    // ---- ThermoWorks App Check renewal ----
    function helperCanRenew() {
        return document.documentElement.dataset.twAppcheckHelperRenew === '1';
    }

    function askHelperToRenew(bridgeId) {
        return new Promise(function (resolve) {
            const requestId = Math.random().toString(36).slice(2);
            let settled = false;
            function finish(result) {
                if (settled) {
                    return;
                }
                settled = true;
                window.removeEventListener('message', onMessage);
                clearTimeout(timeoutId);
                resolve(result);
            }
            function onMessage(event) {
                const d = event.data || {};
                if (event.source !== window || d.source !== 'tw-helper' ||
                    d.type !== 'tw-appcheck-renew-result' || d.requestId !== requestId) {
                    return;
                }
                finish({ ok: !!d.ok, error: d.error });
            }
            window.addEventListener('message', onMessage);
            const timeoutId = setTimeout(function () {
                finish({ ok: false, error: 'the Chrome helper did not answer in time' });
            }, RENEW_TIMEOUT_MS);
            window.postMessage({
                source: 'tw-dashboard',
                type: 'tw-appcheck-renew',
                requestId: requestId,
                bridgeId: bridgeId,
                submitUrl: new URL(cfg.appcheckSubmitPath, window.location.origin).href
            }, '*');
        });
    }

    async function maintainAppCheck() {
        if (!jobs.some(function (j) { return j.needs_appcheck; })) {
            appcheck = null;
            return;
        }
        if (renewing) {
            return;
        }
        const status = await getJson(cfg.appcheckStatusUrl);
        if (!status.ok) {
            return;
        }
        const expiresIn = Number(status.data.expires_in || 0);
        if (status.data.ready && expiresIn > RENEW_BEFORE_SEC) {
            appcheck = null;
            return;
        }
        const when = status.data.ready
            ? 'ThermoWorks access expires in ' + formatAgo(expiresIn) + '.'
            : 'ThermoWorks access has expired, so the ThermoWorks run is not getting readings.';

        if (!helperCanRenew()) {
            appcheck = {
                message: when + ' Install or reload the Chrome helper (v1.3) to renew it automatically, or click Renew now.'
            };
            return;
        }
        if (Date.now() - lastRenewFailure < RENEW_RETRY_MS || !takeRenewLock()) {
            return;
        }

        renewing = true;
        try {
            const bridge = await getJson(cfg.appcheckBridgeUrl, {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }
            });
            if (!bridge.ok || !bridge.data.bridge_id) {
                throw new Error(bridge.data.error || 'could not start renewal');
            }
            const result = await askHelperToRenew(bridge.data.bridge_id);
            if (!result.ok) {
                throw new Error(result.error || 'renewal failed');
            }
            appcheck = null;
            lastRenewFailure = 0;
        } catch (err) {
            lastRenewFailure = Date.now();
            appcheck = {
                message: when + ' Automatic renewal failed (' + (err && err.message ? err.message : err) +
                    '). It will retry in a few minutes, or click Renew now.'
            };
        } finally {
            renewing = false;
            releaseRenewLock();
        }
    }

    // ---- loop ----
    async function tick() {
        timer = null;
        if (stopped) {
            return;
        }
        try {
            const result = await getJson(cfg.jobsUrl);
            if (result.ok) {
                jobs = result.data.jobs || [];
                checkTransitions();
                render();
                await maintainAppCheck();
                render();
            }
        } catch (e) {}
        if (!stopped) {
            schedule(POLL_MS);
        }
    }

    function schedule(ms) {
        if (timer) {
            clearTimeout(timer);
        }
        timer = setTimeout(tick, ms);
    }

    document.addEventListener('visibilitychange', function () {
        if (document.visibilityState === 'visible' && !stopped) {
            schedule(0);
        }
    });

    // Let the helper's content script mark the page before the first check.
    schedule(1500);
})();
