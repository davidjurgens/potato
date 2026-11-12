/**
 * Ontology term picker for schemes with `label_source`
 * (radio, multiselect, span, image_annotation).
 *
 * The box is a combobox (ARIA 1.2 pattern): typing searches
 * /api/ontology/search, Up/Down move through the matches, Enter picks one,
 * Escape closes the list (a second Escape clears the box). The browser only
 * talks to Potato; for OLS4 the server makes the remote call.
 *
 * A picked term becomes an ordinary option of the scheme, so the page's own
 * save/restore code handles it:
 *   radio / multiselect -> a radio or checkbox: label_name = term id,
 *                          value = {"obo_id","label","iri","ontology_version"}
 *   span                -> a span-label chip whose label is the term id
 *   image_annotation    -> a .label-btn whose data-label is the term id
 * The server builds the same markup for stored terms when it renders the page
 * (potato/ontology/picker.py), so restoring needs nothing from this file.
 */
(function () {
    'use strict';

    // Same palette and hash as potato/ontology/picker.py.
    var PALETTE = ['#4E79A7', '#F28E2B', '#E15759', '#76B7B2', '#59A14F',
                   '#EDC948', '#B07AA1', '#FF9DA7', '#9C755F', '#BAB0AC'];
    var CURIE = /^[A-Za-z][A-Za-z0-9_.\-]*:[A-Za-z0-9_.\-]+$/;
    var TERM_KEYS = ['obo_id', 'label', 'iri', 'ontology_version'];
    var DEBOUNCE_MS = 180;

    // schema -> {term id -> record}, for relabelling span chips.
    var termMaps = {};

    function fnv1a(text) {
        var bytes = new TextEncoder().encode(String(text));
        var h = 0x811c9dc5;
        for (var i = 0; i < bytes.length; i++) {
            h ^= bytes[i];
            h = Math.imul(h, 0x01000193) >>> 0;
        }
        return h >>> 0;
    }

    function termColor(id) { return PALETTE[fnv1a(id) % PALETTE.length]; }

    function slug(text) { return String(text).replace(/[^A-Za-z0-9_-]/g, '_'); }

    function el(tag, attrs, text) {
        var node = document.createElement(tag);
        Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    function record(term) {
        var out = {};
        TERM_KEYS.forEach(function (k) { out[k] = term[k] == null ? '' : String(term[k]); });
        return out;
    }

    function remember(schema, rec) {
        if (!termMaps[schema]) termMaps[schema] = {};
        termMaps[schema][rec.obo_id] = rec;
    }

    function labelContent(rec) {
        var frag = document.createDocumentFragment();
        frag.appendChild(el('span', { 'class': 'ontology-term-label' }, rec.label || rec.obo_id));
        frag.appendChild(document.createTextNode(' '));
        frag.appendChild(el('span', { 'class': 'ontology-term-id' }, rec.obo_id));
        return frag;
    }

    function findByAttr(scope, selector, attr, value) {
        var nodes = scope.querySelectorAll(selector);
        for (var i = 0; i < nodes.length; i++) {
            if (nodes[i].getAttribute(attr) === value) return nodes[i];
        }
        return null;
    }

    // ---- turning a term into an option -----------------------------------

    function choiceInput(picker, form, rec) {
        var type = picker.dataset.annotationType;
        var schema = picker.dataset.schema;
        var existing = findByAttr(form, 'input.annotation-input', 'label_name', rec.obo_id);
        if (existing) return existing;
        var container = form.querySelector(type === 'radio' ? '.shadcn-radio-options'
                                                            : '.shadcn-multiselect-grid');
        if (!container) return null;
        var id = slug(schema) + '__onto__' + slug(rec.obo_id);
        var wrap = el('div', {
            'class': (type === 'radio' ? 'shadcn-radio-option' : 'shadcn-multiselect-item')
                     + ' ontology-term-option',
            'data-ontology-term': rec.obo_id
        });
        var input = el('input', {
            'class': schema + (type === 'radio' ? ' shadcn-radio-input annotation-input'
                                                : ' shadcn-multiselect-checkbox annotation-input'),
            type: type === 'radio' ? 'radio' : 'checkbox',
            id: id,
            name: type === 'radio' ? schema : schema + ':::' + rec.obo_id,
            schema: schema,
            label_name: rec.obo_id,
            validation: picker.dataset.validation || ''
        });
        if (type === 'radio') input.setAttribute('selection_constraint', 'single');
        input.value = JSON.stringify(record(rec));
        input.addEventListener('click', function () {
            if (type === 'radio') { if (typeof onlyOne === 'function') onlyOne(input); }
            else if (typeof whetherNone === 'function') whetherNone(input);
            if (typeof registerAnnotation === 'function') registerAnnotation(input);
        });
        var label = el('label', {
            'for': id,
            'class': type === 'radio' ? 'shadcn-radio-label' : 'shadcn-multiselect-label'
        });
        if (type !== 'radio') label.setAttribute('schema', schema);
        label.appendChild(labelContent(rec));
        wrap.appendChild(input);
        wrap.appendChild(label);
        container.appendChild(wrap);
        return input;
    }

    function spanChip(picker, form, rec) {
        var schema = picker.dataset.schema;
        var existing = findByAttr(form, 'input.shadcn-span-checkbox', 'value', rec.obo_id);
        if (existing) return existing;
        var container = form.querySelector('.shadcn-span-options');
        if (!container) return null;
        var targetField = picker.dataset.targetField || '';
        var id = slug(schema) + '__onto__' + slug(rec.obo_id);
        var wrap = el('div', { 'class': 'shadcn-span-option ontology-term-option',
                               'data-ontology-term': rec.obo_id });
        var input = el('input', {
            'class': schema + ' shadcn-span-checkbox',
            for_span: 'true',
            type: 'checkbox',
            id: id,
            name: 'span_label:::' + schema,
            'data-target-field': targetField
        });
        input.value = rec.obo_id;
        input.addEventListener('click', function () {
            if (typeof onlyOne === 'function') onlyOne(input);
            // '' colour: span-core derives it from the label, as it does for
            // codebook-minted labels.
            if (typeof changeSpanLabel === 'function') {
                changeSpanLabel(input, schema, rec.obo_id, rec.label || rec.obo_id, '', targetField);
            }
        });
        var label = el('label', { 'for': id, 'class': 'shadcn-span-label',
                                  title: (rec.label || rec.obo_id) + ' (' + rec.obo_id + ')' });
        var swatch = el('span', null, null);
        swatch.appendChild(labelContent(rec));
        var mgr = window.spanManager;
        var triple = mgr && typeof mgr.paletteColorFor === 'function'
            ? mgr.paletteColorFor(rec.obo_id) : '';
        if (triple) swatch.style.backgroundColor = 'rgba' + String(triple).replace(')', ', 0.4)');
        label.appendChild(swatch);
        wrap.appendChild(input);
        wrap.appendChild(label);
        container.appendChild(wrap);
        return input;
    }

    function labelButton(picker, form, rec) {
        var existing = findByAttr(form, '.label-btn', 'data-label', rec.obo_id);
        var container = form.querySelector('.image-annotation-container');
        var group = form.querySelector('.label-group');
        if (existing || !group) return existing;
        var color = termColor(rec.obo_id);
        var btn = el('button', {
            type: 'button', 'class': 'label-btn ontology-term-btn',
            'data-label': rec.obo_id, 'data-color': color, 'aria-pressed': 'false',
            title: (rec.label || rec.obo_id) + ' (' + rec.obo_id + ')',
            style: '--label-color: ' + color + ';'
        });
        var dot = el('span', { 'class': 'label-color-dot', 'aria-hidden': 'true' });
        dot.style.backgroundColor = color;
        btn.appendChild(dot);
        btn.appendChild(document.createTextNode(rec.label || rec.obo_id));
        btn.addEventListener('click', function () {
            var manager = container && container.annotationManager;
            if (manager) {
                if (manager.config && Array.isArray(manager.config.labels)
                        && !manager.config.labels.some(function (l) {
                            return (l && l.name) === rec.obo_id; })) {
                    manager.config.labels.push({ name: rec.obo_id, color: color });
                }
                manager.setLabel(rec.obo_id, color);
            }
            form.querySelectorAll('.label-btn').forEach(function (b) {
                b.classList.remove('active');
                b.setAttribute('aria-pressed', 'false');
            });
            btn.classList.add('active');
            btn.setAttribute('aria-pressed', 'true');
        });
        var after = group.querySelectorAll('.label-btn');
        if (after.length) {
            after[after.length - 1].insertAdjacentElement('afterend', btn);
        } else {
            group.appendChild(btn);
        }
        return btn;
    }

    function updateSentinel(picker, form) {
        var sentinel = picker.querySelector('.ontology-required-sentinel');
        if (!sentinel) return;
        var any = Array.prototype.some.call(
            form.querySelectorAll('input.annotation-input'),
            function (i) { return i.checked; });
        sentinel.value = any ? '1' : '';
    }

    // ---- the combobox ----------------------------------------------------

    function Picker(root) {
        this.root = root;
        this.form = root.closest('form');
        this.schema = root.dataset.schema;
        this.type = root.dataset.annotationType;
        this.minQuery = parseInt(root.dataset.minQuery, 10) || 2;
        this.input = root.querySelector('.ontology-picker-input');
        this.list = root.querySelector('.ontology-picker-results');
        this.status = root.querySelector('.ontology-picker-status');
        this.results = [];
        this.active = -1;
        this.timer = null;
        this.seq = 0;
        this.controller = null;
        this.bind();
        var self = this;
        if (this.form) {
            this.form.addEventListener('change', function () { updateSentinel(root, self.form); });
            updateSentinel(root, this.form);
        }
    }

    Picker.prototype.bind = function () {
        var self = this;
        this.input.addEventListener('input', function () { self.schedule(); });
        this.input.addEventListener('keydown', function (e) { self.onKey(e); });
        this.input.addEventListener('blur', function () {
            // Long enough for a tap on an option to land first.
            setTimeout(function () { self.close(); }, 200);
        });
        this.input.addEventListener('focus', function () {
            if (self.results.length && self.input.value.trim().length >= self.minQuery) self.open();
        });
        // Keep focus in the box while an option is pressed.
        this.list.addEventListener('mousedown', function (e) { e.preventDefault(); });
        this.list.addEventListener('click', function (e) {
            var li = e.target.closest('[role="option"]');
            if (!li) return;
            self.pick(parseInt(li.dataset.index, 10));
        });
    };

    Picker.prototype.schedule = function () {
        var self = this;
        clearTimeout(this.timer);
        var q = this.input.value.trim();
        if (q.length < this.minQuery) {
            this.results = [];
            this.render();
            this.say(q.length ? 'Type at least ' + this.minQuery + ' characters.' : '');
            return;
        }
        this.timer = setTimeout(function () { self.search(q); }, DEBOUNCE_MS);
    };

    Picker.prototype.search = function (q) {
        var self = this;
        var seq = ++this.seq;
        if (this.controller) this.controller.abort();
        this.controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
        this.root.setAttribute('aria-busy', 'true');
        var url = '/api/ontology/search?schema=' + encodeURIComponent(this.schema)
            + '&q=' + encodeURIComponent(q);
        fetch(url, { credentials: 'same-origin',
                     signal: this.controller ? this.controller.signal : undefined })
            .then(function (r) {
                return r.json().catch(function () { return {}; })
                    .then(function (body) { return { ok: r.ok, body: body }; });
            })
            .then(function (res) {
                if (seq !== self.seq) return;
                self.root.removeAttribute('aria-busy');
                if (!res.ok) {
                    self.results = [];
                    self.render();
                    self.say('Search failed: ' + ((res.body && res.body.error) || 'server error') + '.', true);
                    return;
                }
                self.results = (res.body.results || []).filter(function (t) { return t && t.obo_id; });
                self.active = self.results.length ? 0 : -1;
                self.render();
                var onto = self.root.dataset.ontology || 'ontology';
                if (!self.results.length) {
                    self.say('No ' + onto + ' term matches “' + q + '”.');
                } else if (res.body.truncated) {
                    self.say(self.results.length + ' of ' + res.body.total
                             + ' matches shown. Type more to narrow the list.');
                } else {
                    self.say(self.results.length + (self.results.length === 1 ? ' match.' : ' matches.'));
                }
            })
            .catch(function (err) {
                if (err && err.name === 'AbortError') return;
                if (seq !== self.seq) return;
                self.root.removeAttribute('aria-busy');
                self.results = [];
                self.render();
                self.say('Search failed: the server could not be reached.', true);
            });
    };

    Picker.prototype.say = function (text, isError) {
        this.status.textContent = text || '';
        this.status.classList.toggle('is-error', !!isError);
    };

    Picker.prototype.isPicked = function (id) {
        if (this.type === 'radio' || this.type === 'multiselect') {
            var input = findByAttr(this.form, 'input.annotation-input', 'label_name', id);
            return !!(input && input.checked);
        }
        return false;
    };

    Picker.prototype.render = function () {
        var self = this;
        var list = this.list;
        list.textContent = '';
        var base = this.input.id.replace(/-input$/, '');
        this.results.forEach(function (term, i) {
            var li = el('li', { role: 'option', id: base + '-opt-' + i,
                                'class': 'ontology-picker-option',
                                'aria-selected': i === self.active ? 'true' : 'false' });
            li.dataset.index = String(i);
            var head = el('span', { 'class': 'ontology-result-head' });
            head.appendChild(el('span', { 'class': 'ontology-result-label' }, term.label));
            head.appendChild(el('span', { 'class': 'ontology-result-id' }, term.obo_id));
            if (self.isPicked(term.obo_id)) {
                head.appendChild(el('span', { 'class': 'ontology-result-picked' }, 'selected'));
            }
            li.appendChild(head);
            if (term.synonym) {
                li.appendChild(el('span', { 'class': 'ontology-result-meta' },
                                  'synonym: ' + term.synonym));
            }
            if (term.definition) {
                li.appendChild(el('span', { 'class': 'ontology-result-def' }, term.definition));
            }
            list.appendChild(li);
        });
        if (this.results.length) this.open(); else this.close();
        this.highlight();
    };

    Picker.prototype.open = function () {
        this.list.hidden = false;
        this.input.setAttribute('aria-expanded', 'true');
    };

    Picker.prototype.close = function () {
        this.list.hidden = true;
        this.input.setAttribute('aria-expanded', 'false');
        this.input.removeAttribute('aria-activedescendant');
    };

    Picker.prototype.highlight = function () {
        var opts = this.list.querySelectorAll('[role="option"]');
        var self = this;
        opts.forEach(function (o, i) { o.setAttribute('aria-selected', i === self.active ? 'true' : 'false'); });
        if (this.active >= 0 && opts[this.active] && !this.list.hidden) {
            this.input.setAttribute('aria-activedescendant', opts[this.active].id);
            var o = opts[this.active];
            if (o.offsetTop < this.list.scrollTop) this.list.scrollTop = o.offsetTop;
            else if (o.offsetTop + o.offsetHeight > this.list.scrollTop + this.list.clientHeight) {
                this.list.scrollTop = o.offsetTop + o.offsetHeight - this.list.clientHeight;
            }
        } else {
            this.input.removeAttribute('aria-activedescendant');
        }
    };

    Picker.prototype.onKey = function (e) {
        var n = this.results.length;
        var open = !this.list.hidden;
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            if (!n) return;
            if (!open) { this.open(); } else { this.active = (this.active + 1) % n; }
            if (this.active < 0) this.active = 0;
            this.highlight();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            if (!n) return;
            if (!open) { this.open(); } else { this.active = (this.active - 1 + n) % n; }
            this.highlight();
        } else if (e.key === 'Enter') {
            // Never submit or navigate from the search box.
            e.preventDefault();
            e.stopPropagation();
            if (open && this.active >= 0) this.pick(this.active);
        } else if (e.key === 'Escape') {
            e.preventDefault();
            e.stopPropagation();
            if (open) { this.close(); }
            else if (this.input.value) {
                this.input.value = '';
                this.results = [];
                this.render();
                this.say('');
            }
        } else if (e.key === 'Tab') {
            this.close();
        }
    };

    Picker.prototype.pick = function (index) {
        var term = this.results[index];
        if (!term || !this.form) return;
        var rec = record(term);
        remember(this.schema, rec);
        var target = null;
        if (this.type === 'radio' || this.type === 'multiselect') {
            target = choiceInput(this.root, this.form, rec);
            if (target && !target.checked) target.click();
        } else if (this.type === 'span') {
            target = spanChip(this.root, this.form, rec);
            if (target && !target.checked) target.click();
        } else if (this.type === 'image_annotation') {
            target = labelButton(this.root, this.form, rec);
            if (target) target.click();
        }
        updateSentinel(this.root, this.form);
        this.input.value = '';
        this.results = [];
        this.render();
        var what = rec.label + ' (' + rec.obo_id + ')';
        if (!target) {
            this.say('Could not add ' + what + ' to this question.', true);
        } else if (this.type === 'span') {
            this.say('Selected ' + what + '. Now highlight the text.');
        } else if (this.type === 'image_annotation') {
            this.say('Selected ' + what + '. Now draw on the image.');
        } else {
            this.say('Selected ' + what + '.');
        }
        this.input.focus();
    };

    // ---- span chips: show the term name over the text ---------------------

    var spanSchemas = {};
    var pendingIds = {};
    var relabelQueued = false;

    function relabelSpans() {
        relabelQueued = false;
        Object.keys(spanSchemas).forEach(function (schema) {
            var sel = '[data-schema="' + (window.CSS && CSS.escape ? CSS.escape(schema) : schema) + '"]';
            var overlays = document.querySelectorAll('.span-overlay-pure' + sel + ', .span-overlay' + sel);
            var missing = [];
            overlays.forEach(function (ov) {
                var id = ov.getAttribute('data-label');
                var chip = ov.querySelector('.span-label');
                if (!id || !chip || !CURIE.test(id)) return;
                var rec = termMaps[schema] && termMaps[schema][id];
                if (!rec) { missing.push(id); return; }
                var text = rec.label || id;
                if (chip.textContent !== text) chip.textContent = text;
                var title = text + ' (' + id + ')';
                if (chip.title !== title) chip.title = title;
            });
            fetchTerms(schema, missing);
        });
    }

    function queueRelabel() {
        if (relabelQueued) return;
        relabelQueued = true;
        (window.requestAnimationFrame || setTimeout)(relabelSpans);
    }

    function fetchTerms(schema, ids) {
        var key = schema + '\u0000';
        var todo = ids.filter(function (id) {
            if (pendingIds[key + id]) return false;
            pendingIds[key + id] = true;
            return true;
        });
        if (!todo.length) return;
        fetch('/api/ontology/terms?schema=' + encodeURIComponent(schema)
              + '&ids=' + encodeURIComponent(todo.join(',')), { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : { terms: {} }; })
            .then(function (body) {
                var terms = (body && body.terms) || {};
                Object.keys(terms).forEach(function (id) { remember(schema, record(terms[id])); });
                queueRelabel();
            })
            .catch(function () { /* the id stays on the chip */ });
    }

    function init() {
        var roots = document.querySelectorAll('[data-ontology-picker="true"]');
        roots.forEach(function (root) {
            if (root.dataset.ontologyReady) return;
            root.dataset.ontologyReady = 'true';
            new Picker(root);
            if (root.dataset.annotationType === 'span') spanSchemas[root.dataset.schema] = true;
        });
        if (Object.keys(spanSchemas).length && typeof MutationObserver !== 'undefined') {
            new MutationObserver(queueRelabel).observe(document.body,
                { childList: true, subtree: true, characterData: true });
            queueRelabel();
        }
    }

    window.potatoOntologyPicker = { init: init, termColor: termColor, fnv1a: fnv1a };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
