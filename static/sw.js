// BabyGuard AI Service Worker (PWA Offline Shell & Instant OTA Auto-Update)
const CACHE_NAME = 'babyguard-v2.1';
const STATIC_ASSETS = [
  '/',
  '/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png'
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((k) => {
          if (k !== CACHE_NAME) return caches.delete(k);
        })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  // Do NOT cache live video feed or streaming audio or API endpoints
  if (url.pathname.includes('/video_feed') || 
      url.pathname.includes('/audio_feed') || 
      url.pathname.startsWith('/api/') || 
      url.pathname.startsWith('/ws')) {
    return;
  }

  // Network-First for Navigation (HTML pages) to ensure instant Over-The-Air updates
  if (e.request.mode === 'navigate' || url.pathname === '/' || url.pathname.endsWith('.html')) {
    e.respondWith(
      fetch(e.request)
        .then((response) => {
          if (response && response.status === 200) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(e.request, clone));
          }
          return response;
        })
        .catch(() => caches.match(e.request))
    );
    return;
  }

  // Stale-While-Revalidate for other static assets
  e.respondWith(
    caches.match(e.request).then((cachedRes) => {
      const fetchPromise = fetch(e.request).then((networkRes) => {
        if (networkRes && networkRes.status === 200) {
          caches.open(CACHE_NAME).then((cache) => cache.put(e.request, networkRes.clone()));
        }
        return networkRes;
      }).catch(() => cachedRes);
      return cachedRes || fetchPromise;
    })
  );
});
