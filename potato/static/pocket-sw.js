/* Potato Pocket service worker — app-shell caching for offline annotation.
 * Served from /pocket/sw.js and registered with scope '/pocket' (the route
 * sends Service-Worker-Allowed), so it controls the page itself.
 *
 * - The page (/pocket): network first, cached copy only when the network
 *   fails. It must not be cache-first: a signed-out visitor has to reach the
 *   server's login redirect, and a deploy has to show on the next load. The
 *   page holds no per-user content (pocket.js fetches that), so the cached copy
 *   is safe to hand to whoever is signed in.
 * - Static assets: cache first. Their URLs carry a version (?v=N).
 * - APIs and saves: network only (saves are queued in localStorage by
 *   pocket.js, not here). */

var CACHE = 'potato-pocket-v3';
var PAGE = '/pocket';
var SHELL = [
    PAGE,
    '/static/css/pocket.css?v=4',
    '/static/pocket.js?v=3',
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
    var request = event.request;
    var url = new URL(request.url);
    if (request.method !== 'GET') return;                       // saves: network only
    if (url.pathname.indexOf('/api/') !== -1) return;           // data: network only

    if (url.pathname === PAGE) {
        event.respondWith(
            fetch(request).then(function (response) {
                // A login redirect is opaque and not ok: passed through, not cached.
                if (response.ok && response.type === 'basic') {
                    var copy = response.clone();
                    caches.open(CACHE).then(function (cache) { cache.put(PAGE, copy); });
                }
                return response;
            }).catch(function () {
                return caches.match(PAGE).then(function (cached) {
                    return cached || Response.error();
                });
            })
        );
        return;
    }

    if (url.pathname.indexOf('/static/') !== 0) return;
    event.respondWith(
        caches.match(request).then(function (cached) {
            var network = fetch(request).then(function (response) {
                if (response.ok) {
                    var copy = response.clone();
                    caches.open(CACHE).then(function (cache) {
                        cache.put(request, copy);
                    });
                }
                return response;
            }).catch(function () { return cached; });
            return cached || network;
        })
    );
});
