/*
 * Interlinear glossed text (annotation_type: interlinear_gloss).
 *
 * One column per word: the word (read-only), its morpheme segmentation and
 * its gloss (editable), any configured tiers, then a free translation line.
 * Columns wrap like a printed interlinear example.
 *
 * The checks are the ones in potato/igt.py and must stay in step with it
 * (tests/unit/test_interlinear_gloss.py runs both on the same cases): per
 * word, the segmentation and the gloss need the same "-" and "=" boundaries
 * in the same order (Leipzig rule 2), every morpheme a gloss, and no spaces
 * inside a cell. Category labels (capitals) are printed in small caps and,
 * when the scheme lists abbreviations, unknown ones are flagged.
 *
 * The answer is the scheme's hidden input, as JSON:
 *   {"words": [{"word", "morphemes", "gloss", <tier>...}], "translation"}
 * Misaligned or half-filled words are declared on the form's
 * data-incomplete-reason, which validateRequiredFields reads.
 */
(function (root) {
    'use strict';

    // ------------------------------------------------------------------
    // Rules (mirrors potato/igt.py)
    // ------------------------------------------------------------------

    var EDGE_PUNCT = '.,;:!?"\'“”‘’«»()[]{}¿¡…–—';
    var ELEMENT = /[^.:;_\\()\[\]\s<>=\-]+/g;
    var CATEGORY = /^[0-9A-ZØ]+$/;
    var PERSON = /^([123]+)([0-9A-Z]*)$/;

    function stripEdges(word) {
        var start = 0, end = word.length;
        while (start < end && EDGE_PUNCT.indexOf(word[start]) !== -1) { start++; }
        while (end > start && EDGE_PUNCT.indexOf(word[end - 1]) !== -1) { end--; }
        return word.slice(start, end);
    }

    function tokenizeSentence(text) {
        return String(text || '').split(/\s+/).map(stripEdges).filter(function (w) {
            return w.replace(/[-=–—]/g, '') !== '';
        });
    }

    function splitCell(text) {
        text = String(text || '').trim();
        var infixes = (text.match(/<([^<>]*)>/g) || []).length;
        var flat = text.replace(/<([^<>]*)>/g, '');
        var parts = flat.split(/([-=])/);
        var pieces = [], bounds = [];
        parts.forEach(function (p, i) { (i % 2 ? bounds : pieces).push(p); });
        return {pieces: pieces, bounds: bounds, infixes: infixes};
    }

    function describe(bounds, infixes) {
        var n = bounds.length + 2 * infixes;
        if (!n) { return 'no boundaries'; }
        var kinds = bounds.join(' ') + (bounds.length && infixes ? ' ' : '');
        var inf = [];
        for (var i = 0; i < infixes; i++) { inf.push('<>'); }
        kinds += inf.join(' ');
        return n + ' boundar' + (n === 1 ? 'y' : 'ies') + ' (' + kinds + ')';
    }

    function positions(list) {
        var out = [];
        list.forEach(function (p, i) { if (!p.trim()) { out.push(String(i + 1)); } });
        return out;
    }

    function checkWord(morphemes, gloss) {
        var m = String(morphemes || '').trim(), g = String(gloss || '').trim();
        if (!m && !g) { return {status: 'empty', messages: []}; }
        if (!g) { return {status: 'incomplete', messages: ['no gloss yet']}; }
        if (!m) { return {status: 'incomplete', messages: ['no segmentation yet']}; }
        var messages = [];
        if (/\s/.test(m)) { messages.push('the segmentation holds a space: join morphemes with - or ='); }
        if (/\s/.test(g)) { messages.push('the gloss holds a space: join the words of one gloss with . (rule 4)'); }
        var ms = splitCell(m), gs = splitCell(g);
        if (ms.bounds.join('') !== gs.bounds.join('') || ms.infixes !== gs.infixes) {
            messages.push('segmentation has ' + describe(ms.bounds, ms.infixes) +
                          ', gloss has ' + describe(gs.bounds, gs.infixes));
        } else {
            var em = positions(ms.pieces), eg = positions(gs.pieces);
            if (em.length) { messages.push('empty morpheme at position ' + em.join(', ')); }
            if (eg.length) { messages.push('no gloss for morpheme ' + eg.join(', ')); }
        }
        return {status: messages.length ? 'misaligned' : 'ok', messages: messages};
    }

    function glossElements(gloss) {
        return String(gloss || '').match(ELEMENT) || [];
    }

    function isCategory(el) {
        if (el === '1' || el === '2' || el === '3') { return true; }
        if (/^[0-9]+$/.test(el)) { return false; }
        return CATEGORY.test(el);
    }

    function isKnown(el, known) {
        if (Object.prototype.hasOwnProperty.call(known, el) || el === 'Ø') { return true; }
        var person = PERSON.exec(el);
        if (person) {
            var digitsKnown = person[1].split('').every(function (d) {
                return Object.prototype.hasOwnProperty.call(known, d);
            });
            if (digitsKnown && (!person[2] || isKnown(person[2], known))) { return true; }
        }
        if (el.length > 1 && el[0] === 'N' && Object.prototype.hasOwnProperty.call(known, 'N')) {
            return isKnown(el.slice(1), known);
        }
        return false;
    }

    function unknownLabels(gloss, known) {
        if (!known) { return []; }
        var out = [];
        glossElements(gloss).forEach(function (el) {
            if (isCategory(el) && !isKnown(el, known) && out.indexOf(el) === -1) { out.push(el); }
        });
        return out;
    }

    function asList(value) {
        if (value === null || value === undefined) { return null; }
        if (Array.isArray(value)) { return value.map(function (v) { return v === null || v === undefined ? '' : String(v); }); }
        if (typeof value === 'string') { return value.split(/\s+/).filter(function (v) { return v; }); }
        return null;
    }

    function sourceWords(fields, cfg) {
        var value = (fields || {})[cfg.sourceField || 'text'];
        if (Array.isArray(value)) {
            return value.map(String).filter(function (w) { return w.trim(); });
        }
        return tokenizeSentence(typeof value === 'string' ? value : '');
    }

    function initialAnswer(fields, cfg) {
        fields = fields || {};
        var words = sourceWords(fields, cfg);
        var morphs = cfg.morphemesField ? asList(fields[cfg.morphemesField]) : null;
        var glosses = cfg.glossField ? asList(fields[cfg.glossField]) : null;
        var tiers = cfg.tiers || [];
        var tierValues = {};
        tiers.forEach(function (t) { tierValues[t] = Array.isArray(fields[t]) ? asList(fields[t]) : null; });
        var records = words.map(function (word, i) {
            var rec = {word: word,
                       morphemes: morphs && i < morphs.length ? morphs[i] : word,
                       gloss: glosses && i < glosses.length ? glosses[i] : ''};
            tiers.forEach(function (t) {
                var vals = tierValues[t];
                rec[t] = vals && i < vals.length ? vals[i] : '';
            });
            return rec;
        });
        var translation = cfg.translationField ? String(fields[cfg.translationField] || '') : '';
        return {words: records, translation: translation};
    }

    var core = {
        tokenizeSentence: tokenizeSentence, splitCell: splitCell, checkWord: checkWord,
        glossElements: glossElements, isCategory: isCategory, unknownLabels: unknownLabels,
        initialAnswer: initialAnswer
    };
    if (typeof module !== 'undefined' && module.exports) { module.exports = core; }
    if (typeof document === 'undefined') { return; }
    if (root.PotatoInterlinearGloss) { return; }

    // ------------------------------------------------------------------
    // Page
    // ------------------------------------------------------------------

    var STATES = new WeakMap();
    var TIER_LABELS = {morphemes: 'Morphemes', gloss: 'Gloss'};

    function el(tag, attrs, children) {
        var node = document.createElement(tag);
        Object.keys(attrs || {}).forEach(function (k) {
            var v = attrs[k];
            if (v === undefined || v === null || v === false) { return; }
            if (k === 'text') { node.textContent = v; }
            else if (k === 'className') { node.className = v; }
            else if (k.indexOf('on') === 0) { node.addEventListener(k.slice(2), v); }
            else { node.setAttribute(k, v === true ? '' : v); }
        });
        (children || []).forEach(function (c) { if (c) { node.appendChild(c); } });
        return node;
    }

    function instanceId() {
        var input = document.getElementById('instance_id');
        return input ? input.value : '';
    }

    function fieldsOf() {
        return typeof root.potatoInstanceFields === 'function' ? root.potatoInstanceFields() : {};
    }

    function parseStored(value) {
        if (!value) { return null; }
        try {
            var parsed = JSON.parse(value);
            return parsed && Array.isArray(parsed.words) ? parsed : null;
        } catch (e) { return null; }
    }

    function normalize(answer, cfg) {
        var tiers = cfg.tiers || [];
        return {
            words: answer.words.map(function (w) {
                var rec = {word: String(w.word || ''), morphemes: String(w.morphemes || ''),
                           gloss: String(w.gloss || '')};
                tiers.forEach(function (t) { rec[t] = w[t] === undefined || w[t] === null ? '' : String(w[t]); });
                return rec;
            }),
            translation: String(answer.translation || '')
        };
    }

    function hasPrefill(fields, cfg) {
        return [cfg.morphemesField, cfg.glossField, cfg.translationField].some(function (k) {
            var v = k ? fields[k] : null;
            return Array.isArray(v) ? v.some(function (x) { return String(x || '').trim(); })
                : !!String(v || '').trim();
        });
    }

    function lines(cfg) {
        return ['morphemes', 'gloss'].concat(cfg.tiers || []);
    }

    function cellWidth(state, i) {
        var w = state.answer.words[i];
        var longest = String(w.word).length;
        lines(state.cfg).forEach(function (k) { longest = Math.max(longest, String(w[k] || '').length); });
        return Math.min(Math.max(longest + 2, 6), 48) + 'ch';
    }

    function setup(form) {
        var prior = STATES.get(form);
        if (prior && prior.instance === instanceId()) { sync(prior); return; }
        var cfg = JSON.parse(form.getAttribute('data-igt-config') || '{}');
        var hidden = form.querySelector('.interlinear-gloss-input');
        var fields = fieldsOf();
        // Only a value the server rendered is an answer. A browser can put back
        // a cached value from an earlier visit, which annotation.js clears.
        var stored = hidden.getAttribute('data-server-set') === 'true' ? parseStored(hidden.value) : null;
        var state = {
            instance: instanceId(), cfg: cfg, form: form, hidden: hidden,
            root: form.querySelector('.igt-root'),
            answer: stored ? normalize(stored, cfg) : initialAnswer(fields, cfg),
            // An imported analysis the annotator has only to confirm: it is
            // written to the hidden input once the page has settled, so
            // pressing Next keeps it even when nothing was edited.
            prefilled: !stored && hasPrefill(fields, cfg),
            written: stored ? hidden.value : ''
        };
        STATES.set(form, state);
        render(state);
    }

    /* After annotation.js has loaded the instance. Its clearAllFormInputs()
       empties every text input on the page and every hidden input the server
       did not set, so repaint the cells from the state and put back what this
       widget wrote. */
    function sync(state) {
        var current = state.hidden.value || '';
        var stored = state.hidden.getAttribute('data-server-set') === 'true' ? parseStored(current) : null;
        if (stored && current !== state.written) {
            state.answer = normalize(stored, state.cfg);
            state.written = current;
            render(state);
            return;
        }
        paint(state);
        if (!current && (state.dirty || state.prefilled)) {
            write(state, false);
        }
    }

    function write(state, notify) {
        var json = JSON.stringify(state.answer);
        state.hidden.value = json;
        state.written = json;
        state.hidden.setAttribute('data-modified', 'true');
        if (notify) { state.hidden.dispatchEvent(new Event('change', {bubbles: true})); }
    }

    function render(state) {
        var cfg = state.cfg, root = state.root, words = state.answer.words;
        root.innerHTML = '';
        if (!words.length) {
            root.appendChild(el('p', {className: 'igt-error', role: 'alert',
                text: 'This item has no words to gloss in the field "' + (cfg.sourceField || 'text') + '".'}));
            declare(state);
            return;
        }
        state.summary = el('p', {className: 'igt-summary', role: 'status', 'aria-live': 'polite'});
        root.appendChild(state.summary);
        var list = el('ol', {className: 'igt-words', 'aria-label': 'Words'});
        // Row labels, in a first column with the same rows as a word column.
        var head = el('li', {className: 'igt-word igt-head', 'aria-hidden': 'true'});
        head.appendChild(el('span', {className: 'igt-cell igt-source', text: 'Word'}));
        lines(cfg).forEach(function (k) {
            head.appendChild(el('span', {className: 'igt-cell igt-head-label', text: TIER_LABELS[k] || k}));
            if (k === 'gloss') {
                head.appendChild(el('span', {className: 'igt-cell igt-render igt-head-label', text: ' '}));
            }
        });
        list.appendChild(head);
        state.columns = words.map(function (w, i) {
            var issueId = cfg.schema + '-igt-issue-' + i;
            var col = el('li', {className: 'igt-word', 'data-index': String(i)});
            col.appendChild(el('span', {className: 'igt-cell igt-source', lang: cfg.language || null,
                                        text: w.word}));
            var inputs = {};
            lines(cfg).forEach(function (k) {
                var isMeta = k !== 'morphemes';
                var input = el('input', {
                    type: 'text', className: 'igt-input igt-' + (k === 'morphemes' || k === 'gloss' ? k : 'tier'),
                    'data-tier': k, 'data-index': String(i), autocomplete: 'off', autocapitalize: 'off',
                    autocorrect: 'off', spellcheck: 'false',
                    lang: (isMeta ? cfg.metalanguage : cfg.language) || null,
                    placeholder: TIER_LABELS[k] ? TIER_LABELS[k].toLowerCase() : k,
                    'aria-label': (TIER_LABELS[k] || k) + ' of word ' + (i + 1) + ', ' + w.word,
                    'aria-describedby': k === 'morphemes' || k === 'gloss' ? issueId : null,
                    oninput: function () { onEdit(state, i, k, this.value); },
                    onkeydown: function (e) { onKey(state, i, k, e); }
                });
                inputs[k] = input;
                col.appendChild(input);
                if (k === 'gloss') {
                    inputs._render = el('span', {className: 'igt-cell igt-render', 'aria-hidden': 'true',
                                                 lang: cfg.metalanguage || null});
                    col.appendChild(inputs._render);
                }
            });
            inputs._issue = el('p', {className: 'igt-issue', id: issueId});
            col.appendChild(inputs._issue);
            list.appendChild(col);
            return {el: col, inputs: inputs};
        });
        root.appendChild(list);
        if (cfg.translation) {
            var tid = cfg.schema + '-igt-translation';
            state.translation = el('textarea', {className: 'igt-translation', id: tid, rows: '2',
                lang: cfg.metalanguage || null, spellcheck: 'true',
                oninput: function () {
                    state.answer.translation = this.value;
                    state.dirty = true;
                    write(state, true);
                    declare(state);
                }});
            root.appendChild(el('div', {className: 'igt-translation-row'}, [
                el('label', {'for': tid, text: 'Free translation'}), state.translation]));
        }
        root.appendChild(el('p', {className: 'igt-keys',
            text: 'Tab moves to the next cell. Enter moves to the same line of the next word, ' +
                  'Shift+Enter to the previous word. Separate morphemes with - (affix) or = (clitic) ' +
                  'and the glosses of one word the same way; join several meanings of one morpheme with "."'}));
        paint(state);
    }

    /* Put the state into the cells and refresh every word's status. Values
       are only written where they differ, so the caret stays put. */
    function paint(state) {
        if (!state.columns) { declare(state); return; }
        state.answer.words.forEach(function (w, i) {
            var inputs = state.columns[i].inputs;
            lines(state.cfg).forEach(function (k) {
                var v = String(w[k] || '');
                if (inputs[k].value !== v) { inputs[k].value = v; }
            });
            refreshWord(state, i);
        });
        if (state.translation && state.translation.value !== state.answer.translation) {
            state.translation.value = state.answer.translation;
        }
        declare(state);
    }

    function renderGloss(target, gloss) {
        target.textContent = '';
        var text = String(gloss || '');
        var re = /[^.:;_\\()\[\]\s<>=\-]+/g, last = 0, m;
        while ((m = re.exec(text)) !== null) {
            if (m.index > last) { target.appendChild(document.createTextNode(text.slice(last, m.index))); }
            if (isCategory(m[0]) && m[0] !== 'Ø') {
                target.appendChild(el('span', {className: 'igt-cat', text: m[0]}));
            } else {
                target.appendChild(document.createTextNode(m[0]));
            }
            last = m.index + m[0].length;
        }
        if (last < text.length) { target.appendChild(document.createTextNode(text.slice(last))); }
        if (!text) { target.appendChild(document.createTextNode(' ')); }
    }

    function refreshWord(state, i) {
        var w = state.answer.words[i], col = state.columns[i];
        var result = checkWord(w.morphemes, w.gloss);
        var unknown = unknownLabels(w.gloss, state.cfg.abbreviations);
        col.el.setAttribute('data-status', result.status);
        col.el.classList.toggle('igt-has-unknown', unknown.length > 0);
        var bad = result.status === 'misaligned';
        ['morphemes', 'gloss'].forEach(function (k) {
            if (bad) { col.inputs[k].setAttribute('aria-invalid', 'true'); }
            else { col.inputs[k].removeAttribute('aria-invalid'); }
        });
        var issue = col.inputs._issue;
        issue.textContent = '';
        if (bad || result.status === 'incomplete') {
            issue.appendChild(el('span', {className: bad ? 'igt-issue-error' : 'igt-issue-note',
                text: (bad ? 'Misaligned: ' : '') + result.messages.join('; ')}));
        }
        if (unknown.length) {
            issue.appendChild(el('span', {className: 'igt-issue-warn',
                text: 'Unknown label' + (unknown.length > 1 ? 's' : '') + ': ' + unknown.join(', ')}));
        }
        renderGloss(col.inputs._render, w.gloss);
        var width = cellWidth(state, i);
        lines(state.cfg).forEach(function (k) { col.inputs[k].style.width = width; });
    }

    function declare(state) {
        var words = state.answer.words, misaligned = [], unfinished = [], unknown = 0;
        words.forEach(function (w, i) {
            var r = checkWord(w.morphemes, w.gloss);
            if (r.status === 'misaligned') { misaligned.push(i + 1); }
            else if (r.status !== 'ok') { unfinished.push(i + 1); }
            if (unknownLabels(w.gloss, state.cfg.abbreviations).length) { unknown++; }
        });
        var reasons = [];
        if (!words.length) { reasons.push('no words to gloss'); }
        if (misaligned.length) {
            reasons.push('segmentation and gloss do not line up in word' +
                         (misaligned.length > 1 ? 's ' : ' ') + misaligned.join(', '));
        }
        if (unfinished.length) {
            reasons.push('segment and gloss word' + (unfinished.length > 1 ? 's ' : ' ') + unfinished.join(', '));
        }
        if (reasons.length) { state.form.setAttribute('data-incomplete-reason', reasons.join('; ')); }
        else { state.form.removeAttribute('data-incomplete-reason'); }
        if (state.summary) {
            var parts = [words.length + ' word' + (words.length === 1 ? '' : 's')];
            parts.push(misaligned.length ? misaligned.length + ' misaligned' : 'all aligned');
            if (unfinished.length) { parts.push(unfinished.length + ' not yet glossed'); }
            if (unknown) { parts.push(unknown + ' with unknown labels'); }
            state.summary.textContent = parts.join(' · ');
            state.summary.classList.toggle('igt-summary-bad', misaligned.length > 0);
        }
    }

    function onEdit(state, i, k, value) {
        state.answer.words[i][k] = value;
        state.dirty = true;
        refreshWord(state, i);
        write(state, true);
        declare(state);
    }

    function onKey(state, i, k, e) {
        if (e.key !== 'Enter') { return; }
        e.preventDefault();
        e.stopPropagation();
        var next = e.shiftKey ? i - 1 : i + 1;
        if (next >= 0 && next < state.columns.length) {
            var target = state.columns[next].inputs[k];
            target.focus();
            target.select();
        } else if (!e.shiftKey && state.translation) {
            state.translation.focus();
        }
    }

    function init() {
        document.querySelectorAll('form.interlinear-gloss').forEach(setup);
    }

    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); }
    else { init(); }
    document.addEventListener('instanceChanged', init);
    document.addEventListener('potato:instance-ready', init);

    root.PotatoInterlinearGloss = {init: init, core: core};
})(typeof window !== 'undefined' ? window : this);
