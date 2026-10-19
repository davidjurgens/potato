/*
 * The light/dark toggle on annotator pages.
 *
 * templates/_theme_head.html has already set data-theme on <html> before the
 * first paint. This file wires every [data-theme-toggle] button: a press flips
 * the theme and remembers the choice in localStorage ('potato-theme'). Until
 * the annotator chooses, the page follows the browser's preference as it
 * changes. When ui.theme forces a theme (data-theme-mode light or dark), the
 * toggles are hidden and nothing here runs.
 */
(function () {
    'use strict';

    var KEY = 'potato-theme';
    var root = document.documentElement;
    var mode = root.getAttribute('data-theme-mode');

    function toggles() {
        return document.querySelectorAll('[data-theme-toggle]');
    }

    if (mode === 'light' || mode === 'dark') {
        toggles().forEach(function (button) { button.hidden = true; });
        return;
    }

    function stored() {
        try {
            var value = window.localStorage.getItem(KEY);
            return value === 'light' || value === 'dark' ? value : null;
        } catch (e) {
            return null;
        }
    }

    function sync() {
        var dark = root.getAttribute('data-theme') === 'dark';
        toggles().forEach(function (button) {
            button.setAttribute('aria-pressed', dark ? 'true' : 'false');
        });
    }

    function apply(theme) {
        root.setAttribute('data-theme', theme);
        root.setAttribute('data-bs-theme', theme);
        root.style.colorScheme = theme;
        sync();
        document.dispatchEvent(new CustomEvent('potato:themechange', {detail: {theme: theme}}));
    }

    toggles().forEach(function (button) {
        button.addEventListener('click', function () {
            var next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
            try { window.localStorage.setItem(KEY, next); } catch (e) { /* private mode */ }
            apply(next);
        });
    });

    if (window.matchMedia) {
        var query = window.matchMedia('(prefers-color-scheme: dark)');
        var follow = function (event) {
            if (!stored()) { apply(event.matches ? 'dark' : 'light'); }
        };
        if (query.addEventListener) { query.addEventListener('change', follow); }
        else if (query.addListener) { query.addListener(follow); }
    }

    sync();
})();
