/* Potato Pocket service worker — app-shell caching for offline annotation.
 * Served from /pocket/sw.js so its scope covers /pocket. Cache-first for the
 * shell and static assets; network-only for APIs (saves are queued in
 * localStorage by pocket.js, not here). */

var CACHE = 'potato-pocket-v1';
var SHELL = [
    '/pocket',
    '/static/css/pocket.css?v=1',
    '/static/pocket.js?v=1',
    '/static/pocket-icon.svg'
];

self.addEventListener('install', function (event) {
    event.waitUntil(
        caches.open(CACHE).then(function (cache) {
            return cache.addAll(SHELL);
        }).then(function () { return self.skipWaiting(); })
    );
});

self.addEventListener('activate', function (event) {
    event.waitUntil(
        caches.keys().then(function (keys) {
            return Promise.all(keys.filter(function (k) {
                return k !== CACHE;
            }).map(function (k) { return caches.delete(k); }));
        }).then(function () { return self.clients.claim(); })
    );
});

self.addEventListener('fetch', function (event) {
    var url = new URL(event.request.url);
    if (event.request.method !== 'GET') return;                 // saves: network only
    if (url.pathname.indexOf('/api/') !== -1) return;           // data: network only
    if (url.pathname !== '/pocket' &&
        url.pathname.indexOf('/static/') !== 0) return;

    event.respondWith(
        caches.match(event.request).then(function (cached) {
            var network = fetch(event.request).then(function (response) {
                if (response.ok) {
                    var copy = response.clone();
                    caches.open(CACHE).then(function (cache) {
                        cache.put(event.request, copy);
                    });
                }
                return response;
            }).catch(function () { return cached; });
            return cached || network;
        })
    );
});
