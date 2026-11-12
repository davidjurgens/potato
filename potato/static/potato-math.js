/**
 * Math rendering for item text, display fields and trace steps (KaTeX).
 *
 * Loaded only when the config has `math: {enabled: true}`; the page carries the
 * settings in <script type="application/json" id="potato-math-config">, built
 * by potato/math_rendering.py.
 *
 * Runs on the DOM the server already sanitized. Each text node is scanned for
 * the configured delimiters and every match is handed to katex.render() with
 * trust: false, so \href, \url, \includegraphics and \htmlClass/\htmlId/
 * \htmlStyle/\htmlData produce no link, image or attribute. KaTeX builds its
 * output through DOM calls and escapes text, so nothing in an item becomes
 * markup by passing through here.
 *
 * Never rendered: span targets (`[data-span-target="true"]`, and #text-content
 * when the server says a text-selection scheme reads it), code (`pre`, `code`),
 * form controls, and anything under `[data-math="off"]`. Span offsets index
 * the characters of those elements, so they stay as LaTeX source.
 *
 * Delimiter rules (the inline `$` rule is pandoc's):
 *   - `\$` is a literal dollar sign, inside or outside math.
 *   - An opening `$` must be followed by a non-space character; the closing
 *     `$` must follow a non-space character and must not be followed by a
 *     digit. The first unescaped `$` after an opener decides: if it cannot
 *     close, the opener is a plain dollar sign. So "$5 and $10" stays text.
 *   - `$$...$$`, `\[...\]` are display math; `$...$`, `\(...\)` inline.
 */
(function () {
    'use strict';

    var CONFIG_ID = 'potato-math-config';
    // Text inside schemes that is item content: process_reward and
    // trajectory_eval steps (built in the browser after load) and cloze passages.
    var STEP_SELECTOR = '.prm-step-text, .traj-step-text, .traj-step-thought, .cloze-passage';
    var SKIP_SELECTOR = [
        '.potato-math', '.potato-math-literal', '.katex',
        'script', 'style', 'textarea', 'input', 'select', 'option', 'button',
        'pre', 'code', 'kbd', 'samp', '[contenteditable="true"]',
        '[data-span-target="true"]', '#span-overlays', '.span-overlays-field',
        '[data-math="off"]'
    ].join(', ');
    // Strict-mode codes that only say "not what LaTeX would do" for input that
    // models and people write all the time. Everything else fails closed: the
    // source is shown with an error mark rather than a guess.
    var LENIENT_CODES = {
        unicodeTextInMathMode: true,
        symbolNotInFont: true,
        newLineInDisplayMode: true
    };

    var settings = null;
    var observer = null;
    var pending = [];
    var scheduled = false;

    function readConfig() {
        var el = document.getElementById(CONFIG_ID);
        if (!el) return null;
        try {
            return JSON.parse(el.textContent || 'null');
        } catch (e) {
            console.warn('[potato-math] unreadable config', e);
            return null;
        }
    }

    function isSpace(ch) {
        return ch === undefined || /\s/.test(ch);
    }

    // Index of the closing delimiter for an opener ending at `from`, or -1.
    function findClose(text, from, delim) {
        var right = delim.right;
        var inlineDollar = delim.left === '$';
        var j = from;
        while (j < text.length) {
            // Escaped characters are stepped over below, so a `$` reached here
            // is unescaped.
            if (text.startsWith(right, j)) {
                if (!inlineDollar) return j;
                // pandoc: closer follows a non-space and is not followed by a digit.
                var ok = !isSpace(text.charAt(j - 1)) && !/[0-9]/.test(text.charAt(j + 1));
                return ok ? j : -1;
            }
            if (inlineDollar && text.startsWith('\n\n', j)) return -1;
            j += text.charAt(j) === '\\' ? 2 : 1;
        }
        return -1;
    }

    /**
     * Split one string into segments:
     *   {type: 'text', value}, {type: 'literal', value: '$'},
     *   {type: 'math', tex, display, source}
     * Exposed as PotatoMath.scan for tests.
     */
    function scan(text, delimiters) {
        var out = [];
        var buf = '';
        var i = 0;
        var hasDollar = delimiters.some(function (d) { return d.left.charAt(0) === '$'; });
        function flush() { if (buf) { out.push({ type: 'text', value: buf }); buf = ''; } }
        outer:
        while (i < text.length) {
            if (hasDollar && text.charAt(i) === '\\' && text.charAt(i + 1) === '$') {
                flush();
                out.push({ type: 'literal', value: '$' });
                i += 2;
                continue;
            }
            for (var k = 0; k < delimiters.length; k++) {
                var d = delimiters[k];
                if (!text.startsWith(d.left, i)) continue;
                var start = i + d.left.length;
                if (d.left === '$' && (isSpace(text.charAt(start)) || text.charAt(start) === '$')) continue;
                var end = findClose(text, start, d);
                if (end < 0) continue;
                var tex = text.slice(start, end);
                if (!tex.trim()) continue;
                flush();
                out.push({
                    type: 'math', tex: tex, display: !!d.display,
                    source: d.left + tex + d.right
                });
                i = end + d.right.length;
                continue outer;
            }
            buf += text.charAt(i);
            i += 1;
        }
        flush();
        return out;
    }

    function katexOptions(display) {
        return {
            displayMode: display,
            throwOnError: true,
            trust: false,
            strict: function (code) { return LENIENT_CODES[code] ? 'ignore' : 'error'; },
            output: 'htmlAndMathml',
            maxSize: 20,
            maxExpand: 500,
            // A fresh copy per expression: \gdef in one item cannot leak into
            // the next expression or alter the configured macros.
            macros: Object.assign({}, settings.macros || {})
        };
    }

    function renderSegment(seg) {
        var span = document.createElement('span');
        span.className = 'potato-math' + (seg.display ? ' potato-math-display' : ' potato-math-inline');
        span.setAttribute('data-tex', seg.tex);
        try {
            window.katex.render(seg.tex, span, katexOptions(seg.display));
        } catch (err) {
            span.textContent = seg.source;
            span.className += ' potato-math-error';
            span.title = 'Math could not be rendered: ' + (err && err.message ? err.message : err);
        }
        return span;
    }

    function inScope(el) {
        if (!el || !el.closest) return false;
        if (el.closest(SKIP_SELECTOR)) return false;
        if (el.closest(STEP_SELECTOR)) return true;
        var field = el.closest('.instance-area .display-field');
        if (field) {
            if (!settings.fields) return true;
            var key = field.getAttribute('data-field-key');
            return settings.fields.indexOf(key) !== -1;
        }
        if (settings.instance_text && el.closest('#text-content')) return true;
        return false;
    }

    function renderTextNode(node) {
        var text = node.nodeValue;
        if (!text || (text.indexOf('$') === -1 && text.indexOf('\\') === -1)) return false;
        var segs = scan(text, settings.delimiters);
        if (!segs.some(function (s) { return s.type !== 'text'; })) return false;
        var frag = document.createDocumentFragment();
        segs.forEach(function (seg, k) {
            if (seg.type === 'text') {
                var value = seg.value;
                // Display math is its own line; in a pre-wrap container the
                // space or newline that followed it in the source would show
                // as an indent on the next line. Display only: span targets
                // are never rendered, so no offset depends on this text.
                if (k > 0 && segs[k - 1].type === 'math' && segs[k - 1].display) {
                    value = value.replace(/^[ \t]*\n?/, '');
                }
                if (value) frag.appendChild(document.createTextNode(value));
            } else if (seg.type === 'literal') {
                var lit = document.createElement('span');
                lit.className = 'potato-math-literal';
                lit.textContent = seg.value;
                frag.appendChild(lit);
            } else {
                frag.appendChild(renderSegment(seg));
            }
        });
        node.parentNode.replaceChild(frag, node);
        return true;
    }

    function renderWithin(root) {
        if (!root || root.nodeType !== 1) return 0;
        var nodes = [];
        var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
        var n;
        while ((n = walker.nextNode())) {
            if (inScope(n.parentElement)) nodes.push(n);
        }
        var count = 0;
        nodes.forEach(function (node) { if (renderTextNode(node)) count += 1; });
        return count;
    }

    function rootsIn(el) {
        if (inScope(el)) return [el];
        var sel = [STEP_SELECTOR, '.instance-area .display-field'];
        if (settings.instance_text) sel.push('#text-content');
        return Array.prototype.slice.call(el.querySelectorAll(sel.join(', ')));
    }

    function renderAll(scope) {
        var count = 0;
        rootsIn(scope || document.body).forEach(function (r) { count += renderWithin(r); });
        if (observer) observer.takeRecords();  // our own insertions
        return count;
    }

    function flushPending() {
        scheduled = false;
        var batch = pending;
        pending = [];
        batch.forEach(function (el) {
            if (el.isConnected) renderAll(el);
        });
    }

    function schedule(el) {
        if (!el || el.nodeType !== 1) return;
        if (el.closest && el.closest('.potato-math, .katex')) return;
        pending.push(el);
        if (!scheduled) {
            scheduled = true;
            // setTimeout, not requestAnimationFrame: rAF does not fire in a
            // background tab, and steps are often built while it is hidden.
            setTimeout(flushPending, 0);
        }
    }

    function start() {
        settings = readConfig();
        if (!settings) return;
        if (typeof window.katex === 'undefined' || !window.katex.render) {
            console.warn('[potato-math] KaTeX did not load; math is shown as source');
            return;
        }
        renderAll(document.body);
        observer = new MutationObserver(function (records) {
            records.forEach(function (r) {
                r.addedNodes.forEach(function (node) {
                    schedule(node.nodeType === 1 ? node : node.parentElement);
                });
            });
        });
        observer.observe(document.body, { childList: true, subtree: true });
    }

    window.PotatoMath = {
        scan: scan,
        render: function (scope) { return settings ? renderAll(scope) : 0; },
        _settings: function () { return settings; }
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();
