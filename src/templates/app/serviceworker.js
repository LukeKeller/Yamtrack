{% load static %}
// Yamtrack service worker.
//
// Served by app.views.service_worker so the {% templatetag openblock %} static {% templatetag closeblock %} tags below resolve
// to the correct asset paths under BASE_URL subpath deploys (e.g. /yamtrack/static/...).
// Registered from base.html with `scope: '/'` and the response sets
// `Service-Worker-Allowed: /` so the SW can claim the whole app.

const CACHE_NAME = 'yamtrack-v2';
const urlsToCache = [
  "{% static 'css/main.css' %}",
  "{% static 'favicon/android-chrome-192x192.png' %}",
  "{% static 'favicon/android-chrome-512x512.png' %}",
  "{% static 'fonts/roboto-flex.woff2' %}"
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      // addAll is atomic — a single 404 rejects the install. Cache entries
      // individually so a missing asset doesn't take down the whole SW.
      return Promise.allSettled(urlsToCache.map((url) => cache.add(url)));
    }),
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      await Promise.all(
        names.filter((n) => n !== CACHE_NAME).map((n) => caches.delete(n)),
      );
      await self.clients.claim();
    })(),
  );
});

self.addEventListener('fetch', (event) => {
  // Only handle GETs we know how to satisfy from the precache.
  if (event.request.method !== 'GET') return;
  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request)),
  );
});
