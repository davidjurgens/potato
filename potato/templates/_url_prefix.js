// Deployment URL prefix helpers. Raw JavaScript, included inside a <script>
// tag -- see docs/deployment/reverse-proxy.md.
//
// Included by base_template_v2.html and by every standalone page that builds
// request URLs in JavaScript. Without it, a page behind a path prefix sends
// its fetch() calls to the public root and they return 404.
window.config = window.config || {};
window.config.url_prefix = {{ url_prefix | default('') | tojson }};
        window.potatoUrl = function(path) {
            var prefix = (window.config && window.config.url_prefix) || '';
            if (!prefix || typeof path !== 'string' || path.charAt(0) !== '/') {
                return path;
            }
            // Leave protocol-relative URLs ("//host/...") untouched — they are
            // absolute to another origin, not app-root-relative.
            if (path.charAt(1) === '/') {
                return path;
            }
            if (path.indexOf(prefix + '/') === 0 || path === prefix) {
                return path;
            }
            return prefix + path;
        };

        (function() {
            var prefix = (window.config && window.config.url_prefix) || '';
            if (!prefix) return;

            var originalFetch = window.fetch;
            if (originalFetch) {
                window.fetch = function(input, init) {
                    if (typeof input === 'string') {
                        input = window.potatoUrl(input);
                    } else if (input && typeof input.url === 'string') {
                        var prefixedUrl = window.potatoUrl(input.url);
                        if (prefixedUrl !== input.url) {
                            input = new Request(prefixedUrl, input);
                        }
                    }
                    return originalFetch.call(this, input, init);
                };
            }

            var originalSendBeacon = navigator.sendBeacon;
            if (originalSendBeacon) {
                navigator.sendBeacon = function(url, data) {
                    return originalSendBeacon.call(this, window.potatoUrl(url), data);
                };
            }

            // Server-Sent Events (live agent / live coding viewers) open
            // root-relative stream URLs that fetch/sendBeacon patching misses.
            // Wrap the constructor so new EventSource('/api/.../stream') resolves
            // under the mounted prefix. Note: SSE behind a path-prefix proxy also
            // needs `proxy_buffering off` on the stream location (see docs).
            var OriginalEventSource = window.EventSource;
            if (OriginalEventSource) {
                window.EventSource = function(url, config) {
                    return new OriginalEventSource(window.potatoUrl(url), config);
                };
                // Preserve instanceof checks and inherited members.
                window.EventSource.prototype = OriginalEventSource.prototype;
                ['CONNECTING', 'OPEN', 'CLOSED'].forEach(function(key) {
                    window.EventSource[key] = OriginalEventSource[key];
                });
            }

            function prefixAttribute(root, selector, attribute, isList) {
                var elements = [];
                if (root.matches && root.matches(selector)) {
                    elements.push(root);
                }
                root.querySelectorAll(selector).forEach(function(element) {
                    elements.push(element);
                });
                elements.forEach(function(element) {
                    var value = element.getAttribute(attribute);
                    if (!value) {
                        return;
                    }
                    if (isList) {
                        // srcset is "url descriptor, url descriptor". potatoUrl
                        // returns anything that is not root-relative unchanged.
                        element.setAttribute(attribute, value.split(',').map(
                            function(candidate) {
                                return window.potatoUrl(candidate.trim());
                            }).join(', '));
                    } else if (value.charAt(0) === '/') {
                        element.setAttribute(attribute, window.potatoUrl(value));
                    }
                });
            }

            function rewriteRootRelativeUrls(root) {
                root = root || document;
                prefixAttribute(root, 'a[href^="/"]', 'href');
                prefixAttribute(root, 'form[action^="/"]', 'action');
                prefixAttribute(root, 'img[src^="/"]', 'src');
                prefixAttribute(root, 'video[src^="/"]', 'src');
                prefixAttribute(root, 'audio[src^="/"]', 'src');
                prefixAttribute(root, 'source[src^="/"]', 'src');
                prefixAttribute(root, 'track[src^="/"]', 'src');
                prefixAttribute(root, 'video[poster^="/"]', 'poster');
                prefixAttribute(root, 'source[srcset]', 'srcset', true);
            }

            document.addEventListener('DOMContentLoaded', function() {
                rewriteRootRelativeUrls(document);
                if (window.MutationObserver) {
                    new MutationObserver(function(mutations) {
                        mutations.forEach(function(mutation) {
                            mutation.addedNodes.forEach(function(node) {
                                if (node.nodeType === 1) {
                                    rewriteRootRelativeUrls(node);
                                }
                            });
                        });
                    }).observe(document.documentElement, {childList: true, subtree: true});
                }
            });
        })();
