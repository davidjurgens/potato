/**
 * Shared PDF.js loader.
 *
 * PDF.js is vendored under /static/vendor/pdfjs so PDF annotation works on
 * offline / air-gapped deployments; the CDN is only a fallback if the local
 * copy is missing.
 *
 * Every consumer must go through this module. Two independent copies of this
 * logic existed before, and the one in pdf-viewer.js silently skipped the
 * vendored files and went straight to the CDN — which is exactly the failure
 * a second copy invites.
 */
(function () {
    'use strict';

    if (window.PotatoPDFJS) return;

    const LOCAL = '/static/vendor/pdfjs';
    const CDN = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174';

    function injectScript(src) {
        return new Promise((resolve, reject) => {
            const s = document.createElement('script');
            s.src = src;
            s.onload = () => resolve();
            s.onerror = () => reject(new Error('Failed to load ' + src));
            document.head.appendChild(s);
        });
    }

    // Shared across callers so several viewers on one page inject one script tag.
    let loading = null;

    function load() {
        if (window.pdfjsLib) return Promise.resolve();
        if (loading) return loading;
        loading = (async () => {
            try {
                await injectScript(`${LOCAL}/pdf.min.js`);
                window.pdfjsLib.GlobalWorkerOptions.workerSrc = `${LOCAL}/pdf.worker.min.js`;
            } catch (localErr) {
                console.warn('[PotatoPDFJS] local PDF.js unavailable, falling back to CDN', localErr);
                await injectScript(`${CDN}/pdf.min.js`);
                window.pdfjsLib.GlobalWorkerOptions.workerSrc = `${CDN}/pdf.worker.min.js`;
            }
        })();
        return loading;
    }

    window.PotatoPDFJS = { load, LOCAL, CDN };
})();
