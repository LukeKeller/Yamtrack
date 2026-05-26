// Offline write queue for HTMX-driven mutations.
//
// When the network is down or an HTMX mutation errors out before reaching
// the server, this module captures the request, stashes it in IndexedDB,
// and replays it on reconnect. It also registers a Background Sync tag
// (Chromium only) so the SW can drain the queue while the tab is closed.
//
// What gets queued:
//   - HTMX POSTs whose target carries `data-yt-offline`, OR
//   - HTMX POSTs to a small allowlist of mutation endpoints
//     (update-status / update-score / media_save / dismiss_item)
//
// Why these specific endpoints: they're naturally idempotent (replay
// applies the same status/score/save state) so a replay never produces
// duplicate side-effects.

(function () {
  const DB_NAME = 'yt-offline';
  const DB_VERSION = 1;
  const STORE = 'mutations';
  const SYNC_TAG = 'yt-replay';
  const TOAST_ID = 'yt-offline-queue-toast';
  const INDICATOR_ID = 'yt-offline-queue-indicator';

  if (!('indexedDB' in window)) return;

  function openDB() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(STORE)) {
          db.createObjectStore(STORE, { keyPath: 'id', autoIncrement: true });
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  function tx(db, mode) {
    return db.transaction(STORE, mode).objectStore(STORE);
  }

  async function addItem(item) {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const store = tx(db, 'readwrite');
      const req = store.add({ ...item, queued_at: Date.now() });
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  async function listItems() {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const req = tx(db, 'readonly').getAll();
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  async function removeItem(id) {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const req = tx(db, 'readwrite').delete(id);
      req.onsuccess = () => resolve();
      req.onerror = () => reject(req.error);
    });
  }

  async function queueSize() {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const req = tx(db, 'readonly').count();
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  function csrfFromCookie() {
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : null;
  }

  function showToast(text) {
    let el = document.getElementById(TOAST_ID);
    if (!el) {
      el = document.createElement('div');
      el.id = TOAST_ID;
      el.setAttribute('role', 'status');
      el.className = 'fixed right-4 z-50 bg-surface-0 border border-border-default rounded-md shadow-lg p-3 text-sm text-fg max-w-sm';
      el.style.bottom = 'calc(env(safe-area-inset-bottom) + 8rem)';
      document.body.appendChild(el);
    }
    el.textContent = text;
    clearTimeout(el._dismiss);
    el._dismiss = setTimeout(() => el.remove(), 4000);
  }

  async function refreshIndicator() {
    try {
      const n = await queueSize();
      const ind = document.getElementById(INDICATOR_ID);
      if (!ind) return;
      if (n > 0) {
        ind.hidden = false;
        ind.textContent = n === 1 ? '1 queued' : `${n} queued`;
      } else {
        ind.hidden = true;
      }
    } catch (_) { /* IDB unhappy — skip */ }
  }

  // Allowlist of mutation endpoints that are safe to replay. Anything
  // not on this list (or not explicitly tagged) is left to fail loudly.
  const REPLAYABLE = [
    /\/update-status\//,
    /\/update-score\//,
    /\/media_save\b/,
    /\/dismiss_item\b/,
    /\/episode_save\b/,
  ];

  function shouldQueue(elt, cfg) {
    if (!cfg) return false;
    const verb = (cfg.verb || '').toUpperCase();
    if (verb === 'GET') return false;
    if (elt && elt.hasAttribute && elt.hasAttribute('data-yt-offline')) return true;
    const path = cfg.path || '';
    return REPLAYABLE.some((re) => re.test(path));
  }

  async function replay() {
    let items;
    try {
      items = await listItems();
    } catch (_) {
      return;
    }
    if (!items.length) return;
    const token = csrfFromCookie();
    let drained = 0;
    for (const it of items) {
      const headers = { ...it.headers };
      if (token) headers['X-CSRFToken'] = token;
      try {
        const res = await fetch(it.url, {
          method: it.method,
          credentials: 'same-origin',
          headers,
          body: it.body,
        });
        if (res.ok) {
          await removeItem(it.id);
          drained++;
        } else if (res.status >= 400 && res.status < 500 && res.status !== 408 && res.status !== 429) {
          // 4xx (except request-timeout & rate-limit) is a permanent
          // client error — drop so we don't loop forever.
          await removeItem(it.id);
        }
        // 5xx + 408/429 stay queued; we'll retry next time.
      } catch (_) {
        // Network still flaky — stop and try again on next signal.
        break;
      }
    }
    if (drained > 0) {
      showToast(`Synced ${drained} queued change${drained === 1 ? '' : 's'}.`);
    }
    refreshIndicator();
  }

  // Capture HTMX errors. `htmx:sendError` fires when the request can't
  // reach the server at all (network down, CORS preflight failure, DNS).
  // We deliberately ignore HTTP-level errors here — those mean the server
  // saw the request and rejected it, so replaying won't change the outcome.
  document.body.addEventListener('htmx:sendError', async (e) => {
    const cfg = e.detail && e.detail.requestConfig;
    if (!shouldQueue(e.detail && e.detail.elt, cfg)) return;
    try {
      const body = new URLSearchParams(cfg.parameters || {}).toString();
      await addItem({
        url: cfg.path,
        method: (cfg.verb || 'POST').toUpperCase(),
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          'X-Requested-With': 'XMLHttpRequest',
        },
        body,
      });
      showToast('Offline — change saved locally and will sync when you reconnect.');
      refreshIndicator();
      try {
        const reg = await navigator.serviceWorker.ready;
        if (reg.sync) await reg.sync.register(SYNC_TAG);
      } catch (_) { /* sync unsupported (Firefox/Safari) — foreground replay covers it */ }
    } catch (_) { /* IDB unavailable — silent fail */ }
  });

  window.addEventListener('online', replay);

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.addEventListener('message', (event) => {
      if (event.data && event.data.type === 'YT_REPLAY_DONE') refreshIndicator();
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    refreshIndicator();
    if (navigator.onLine) replay();
  });
})();
