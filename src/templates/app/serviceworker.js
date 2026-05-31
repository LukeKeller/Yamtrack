{% load static %}
// Yamtrack service worker.
//
// Served by app.views.service_worker so the {% templatetag openblock %} static {% templatetag closeblock %} / {% templatetag openblock %} url {% templatetag closeblock %} tags
// below resolve under BASE_URL subpath deploys (e.g. /yamtrack/...).
// Registered from base.html; the response sets `Service-Worker-Allowed: /`
// so the SW scope can be widened past its own URL.
//
// Strategies:
//   - app shell (offline page, core CSS, font, app icons): precached
//   - navigations: NetworkFirst with offline-page fallback
//   - same-origin /static/ assets: CacheFirst (versioned URLs)
//   - images (including cross-origin posters): CacheFirst, capped LRU
//   - everything else GET: NetworkFirst, cache fallback
//   - non-GET: passthrough
//
// Update flow: install does NOT call skipWaiting. The page detects a
// waiting worker, shows a toast, and posts {type: 'SKIP_WAITING'} when
// the user accepts the update.

const VERSION = 'v8';
const CACHE_SHELL = 'yamtrack-shell-' + VERSION;
const CACHE_PAGES = 'yamtrack-pages-' + VERSION;
const CACHE_STATIC = 'yamtrack-static-' + VERSION;
const CACHE_IMAGES = 'yamtrack-images-' + VERSION;
const KEEP = new Set([CACHE_SHELL, CACHE_PAGES, CACHE_STATIC, CACHE_IMAGES]);

const OFFLINE_URL = "{% url 'offline' %}";

const SHELL_ASSETS = [
  OFFLINE_URL,
  "{% static 'css/main.css' %}",
  "{% static 'css/themes.css' %}",
  "{% static 'favicon/android-chrome-192x192.png' %}",
  "{% static 'favicon/android-chrome-512x512.png' %}",
  "{% static 'fonts/roboto-flex.woff2' %}"
];

// LRU caps. Opaque (cross-origin) responses can each occupy ~7 MB of
// quota in Chromium, so keep image cache modest.
const MAX_PAGES = 60;
const MAX_IMAGES = 120;

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_SHELL).then((cache) =>
      // Individual cache.add so a single 404 doesn't abort install.
      Promise.allSettled(SHELL_ASSETS.map((url) => cache.add(url))),
    ),
  );
  // Intentionally no skipWaiting() — the page handshakes the upgrade.
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    if (self.registration.navigationPreload) {
      try { await self.registration.navigationPreload.enable(); } catch (_) {}
    }
    const names = await caches.keys();
    await Promise.all(
      names.filter((n) => !KEEP.has(n)).map((n) => caches.delete(n)),
    );
    await self.clients.claim();
  })());
});

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

// Background Sync (Chromium only). Drains the same IndexedDB queue the
// page-side offlineQueue.js writes to. Limitation: the SW can't read
// `document.cookie`, so replays here use the X-CSRFToken from the queued
// request (potentially stale). If a replay fails 403, it's dropped; the
// page-driven replay path will pick it up with a fresh token on next
// page load.
const OFFLINE_DB_NAME = 'yt-offline';
const OFFLINE_DB_VERSION = 1;
const OFFLINE_STORE = 'mutations';
const SYNC_TAG = 'yt-replay';

function openOfflineDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(OFFLINE_DB_NAME, OFFLINE_DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(OFFLINE_STORE)) {
        db.createObjectStore(OFFLINE_STORE, { keyPath: 'id', autoIncrement: true });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function drainOfflineQueue() {
  const db = await openOfflineDB();
  const all = await new Promise((resolve, reject) => {
    const tx = db.transaction(OFFLINE_STORE, 'readonly');
    const req = tx.objectStore(OFFLINE_STORE).getAll();
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  for (const it of all) {
    try {
      const res = await fetch(it.url, {
        method: it.method,
        credentials: 'include',
        headers: it.headers,
        body: it.body,
      });
      const drop = res.ok || (res.status >= 400 && res.status < 500 && res.status !== 408 && res.status !== 429);
      if (drop) {
        await new Promise((resolve, reject) => {
          const tx = db.transaction(OFFLINE_STORE, 'readwrite');
          tx.objectStore(OFFLINE_STORE).delete(it.id);
          tx.oncomplete = () => resolve();
          tx.onerror = () => reject(tx.error);
        });
      }
    } catch (_) {
      // Network still down — Background Sync will retry later.
      break;
    }
  }
  const clients = await self.clients.matchAll({ type: 'window' });
  for (const c of clients) c.postMessage({ type: 'YT_REPLAY_DONE' });
}

self.addEventListener('sync', (event) => {
  if (event.tag === SYNC_TAG) {
    event.waitUntil(drainOfflineQueue());
  }
});

async function trimCache(cacheName, maxEntries) {
  const cache = await caches.open(cacheName);
  const keys = await cache.keys();
  const overflow = keys.length - maxEntries;
  if (overflow <= 0) return;
  // FIFO trim — oldest insertions are at the front of keys().
  for (let i = 0; i < overflow; i++) await cache.delete(keys[i]);
}

async function networkFirstNav(event) {
  const cache = await caches.open(CACHE_PAGES);
  try {
    const preload = await event.preloadResponse;
    const response = preload || await fetch(event.request);
    if (response && response.ok && response.type === 'basic') {
      const copy = response.clone();
      event.waitUntil(
        cache.put(event.request, copy).then(() => trimCache(CACHE_PAGES, MAX_PAGES)),
      );
    }
    return response;
  } catch (_) {
    const cached = await cache.match(event.request);
    if (cached) return cached;
    const shell = await caches.open(CACHE_SHELL);
    const offline = await shell.match(OFFLINE_URL);
    if (offline) return offline;
    return Response.error();
  }
}

async function cacheFirstStatic(request) {
  const cache = await caches.open(CACHE_STATIC);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response && response.ok) cache.put(request, response.clone());
  return response;
}

async function cacheFirstImage(request) {
  const cache = await caches.open(CACHE_IMAGES);
  const cached = await cache.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    // Allow opaque responses (cross-origin posters without CORS) into cache.
    if (response && (response.ok || response.type === 'opaque')) {
      const copy = response.clone();
      // Fire-and-forget trim; do not block the response.
      cache.put(request, copy).then(() => trimCache(CACHE_IMAGES, MAX_IMAGES));
    }
    return response;
  } catch (_) {
    return cached || Response.error();
  }
}

async function networkFirstDefault(request) {
  try {
    return await fetch(request);
  } catch (_) {
    const cached = await caches.match(request);
    if (cached) return cached;
    return Response.error();
  }
}

// Web Push (VAPID). The push event delivers a JSON payload; the
// notificationclick handler focuses an existing app window (or opens
// one) and navigates to the linked URL.
self.addEventListener('push', (event) => {
  let data = {};
  if (event.data) {
    try { data = event.data.json(); }
    catch (_) { data = { title: 'Stackwise', body: event.data.text() }; }
  }
  const title = data.title || 'Stackwise';
  const opts = {
    body: data.body || '',
    icon: data.icon || "{% static 'favicon/android-chrome-192x192.png' %}",
    badge: "{% static 'favicon/favicon-32x32.png' %}",
    data: { url: data.url || '/' },
    requireInteraction: false,
  };
  event.waitUntil(self.registration.showNotification(title, opts));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const client of all) {
      // Prefer focusing an existing window over opening a new one.
      if ('focus' in client) {
        try { await client.navigate(target); } catch (_) {}
        return client.focus();
      }
    }
    if (self.clients.openWindow) return self.clients.openWindow(target);
    return null;
  })());
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  // Top-level navigations get the offline-aware path.
  if (req.mode === 'navigate') {
    event.respondWith(networkFirstNav(event));
    return;
  }

  const url = new URL(req.url);
  const sameOrigin = url.origin === self.location.origin;

  if (req.destination === 'image') {
    event.respondWith(cacheFirstImage(req));
    return;
  }

  if (sameOrigin && (
    url.pathname.includes('/static/') ||
    url.pathname.includes('/media/') ||
    req.destination === 'style' ||
    req.destination === 'script' ||
    req.destination === 'font'
  )) {
    event.respondWith(cacheFirstStatic(req));
    return;
  }

  event.respondWith(networkFirstDefault(req));
});
