// Service Worker para PWA — cache básico
const CACHE_NAME = 'dashboard-fin-v2';

// Instalar — não depende de cache pré-definido
self.addEventListener('install', (event) => {
    self.skipWaiting();
});

// Ativar — limpa caches antigos
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
        )
    );
    self.clients.claim();
});

// Fetch — Network first, fallback to cache
self.addEventListener('fetch', (event) => {
    // Não cacheia requisições da API
    if (event.request.url.includes('/login') ||
        event.request.url.includes('/register') ||
        event.request.url.includes('/transactions') ||
        event.request.url.includes('/summary') ||
        event.request.url.includes('/layout')) {
        return;
    }

    event.respondWith(
        fetch(event.request)
            .then(response => {
                const clone = response.clone();
                caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
                return response;
            })
            .catch(() => caches.match(event.request))
    );
});
