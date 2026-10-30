// BabyGuard AI Service Worker (PWA Offline Shell & Fast Assets Caching)
const CACHE_NAME = 'babyguard-v1.0';
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

  e.respondWith(
    caches.match(e.request).then((res) => {
      return res || fetch(e.request);
    })
  );
});
