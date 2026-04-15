// Service Worker v4 — Offline-first com cache robusto
const CACHE_NAME = 'dashboard-fin-v4';
const STATIC_ASSETS = [
    './',
    './dashboard.html',
    './planilhas.html',
    './index.html',
    './config.js',
    './db.js',
    './manifest.json',
    'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css',
    'https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js',
];
const API_CACHE = 'dashboard-api-v1';

// Install — pre-cache static assets
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache =>
            cache.addAll(STATIC_ASSETS).catch(() => {
                return Promise.allSettled(STATIC_ASSETS.map(url =>
                    cache.add(url).catch(() => console.log('SW: skip', url))
                ));
            })
        )
    );
    self.skipWaiting();
});

// Activate — clean old caches
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE_NAME && k !== API_CACHE).map(k => caches.delete(k)))
        )
    );
    self.clients.claim();
});

// Fetch
self.addEventListener('fetch', event => {
    const url = new URL(event.request.url);

    // POST/PUT/DELETE — just pass through
    if (event.request.method !== 'GET') return;

    // API requests — network first, cache response for offline reads
    if (url.pathname.match(/\/(transactions|summary|spreadsheets|layout)/)) {
        event.respondWith(
            fetch(event.request)
                .then(response => {
                    const clone = response.clone();
                    caches.open(API_CACHE).then(cache => cache.put(event.request, clone));
                    return response;
                })
                .catch(() => caches.match(event.request).then(r => r || new Response(
                    JSON.stringify({offline: true, data: []}),
                    {headers: {'Content-Type': 'application/json'}}
                )))
        );
        return;
    }

    // Auth endpoints — never cache
    if (url.pathname.match(/\/(login|register)/)) return;

    // Static assets — cache first, network fallback
    event.respondWith(
        caches.match(event.request).then(cached => {
            if (cached) return cached;
            return fetch(event.request).then(response => {
                if (response && response.status === 200) {
                    const clone = response.clone();
                    caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
                }
                return response;
            }).catch(() => {
                if (event.request.mode === 'navigate') {
                    return caches.match('./dashboard.html');
                }
            });
        })
    );
});

// Background sync
self.addEventListener('sync', event => {
    if (event.tag === 'sync-data') {
        event.waitUntil(
            self.clients.matchAll().then(clients => {
                clients.forEach(client => client.postMessage({type: 'SYNC_NOW'}));
            })
        );
    }
});

self.addEventListener('message', event => {
    if (event.data === 'SKIP_WAITING') self.skipWaiting();
});
