/**
 * Per-object attributes (occlusion, truncation, ...) for objects that are not
 * image shapes: video tracks and point-cloud cuboids.
 *
 * The rules match the image tool's panel (image-annotation.js), which came
 * first: definitions scoped to labels, `show_if`, defaults applied once to an
 * object a person made, `required` checked through the form's
 * data-incomplete-reason. Definitions are normalized on the server by
 * schemas/object_attributes.py.
 */
(function () {
    'use strict';

    function defsFor(defs, label) {
        return (defs || []).filter(d => !Array.isArray(d.labels) || d.labels.includes(label));
    }

    function visible(def, values) {
        if (!def.show_if) return true;
        const actual = (values || {})[def.show_if.attribute];
        const wanted = def.show_if.equals;
        if (Array.isArray(actual)) return actual.includes(wanted);
        return actual === wanted;
    }

    function missing(def, values) {
        const v = (values || {})[def.name];
        if (v === undefined || v === null || v === '') return true;
        return Array.isArray(v) && v.length === 0;
    }

    /** The declared defaults for a new object with this label. */
    function defaults(defs, label) {
        const out = {};
        defsFor(defs, label).forEach(def => {
            if (def.default !== undefined) {
                out[def.name] = Array.isArray(def.default) ? def.default.slice() : def.default;
            }
        });
        return out;
    }

    /** Whether an object still lacks a required, visible attribute. */
    function incomplete(defs, label, values) {
        return defsFor(defs, label).some(def =>
            def.required && visible(def, values || {}) && missing(def, values || {}));
    }

    /**
     * Tell the scheme's form how many objects lack required attributes, the
     * way the image tool does: the form's data-incomplete-reason, read by
     * validateRequiredFields(), and the panel's status line.
     */
    function updateRequirement(panel, form, count, noun) {
        const reason = count
            ? `${count} ${noun}${count === 1 ? '' : 's'} still need${count === 1 ? 's' : ''} required attributes`
            : '';
        if (form) {
            if (count) form.setAttribute('data-incomplete-reason', reason);
            else form.removeAttribute('data-incomplete-reason');
        }
        const status = panel && panel.querySelector('.attribute-panel-status');
        if (status) status.textContent = reason;
        if (typeof validateRequiredFields === 'function') {
            try { validateRequiredFields(); } catch (e) { /* never block editing */ }
        }
    }

    /**
     * Fill a panel (the markup schemas/object_attributes.panel_html makes)
     * with controls for one object's attributes.
     *
     * options: {panel, defs, label, values, idPrefix, noun, onChange(values)}.
     * `values` is edited in place; onChange runs after every edit.
     */
    function render(options) {
        const panel = options.panel;
        if (!panel) return;
        const fields = panel.querySelector('.attribute-fields');
        const hint = panel.querySelector('.attribute-panel-hint');
        fields.innerHTML = '';
        const noun = options.noun || 'object';
        if (options.label === null || options.label === undefined) {
            panel.classList.remove('has-selection');
            hint.textContent = `Select ${/^[aeiou]/i.test(noun) ? 'an' : 'a'} ${noun} to set its attributes.`;
            return;
        }
        const defs = defsFor(options.defs, options.label);
        if (!defs.length) {
            panel.classList.remove('has-selection');
            hint.textContent = `No attributes for "${options.label}".`;
            return;
        }
        panel.classList.add('has-selection');
        hint.textContent = `Attributes for the selected "${options.label}"`;
        const values = options.values;

        defs.forEach(def => {
            const row = document.createElement('div');
            row.className = 'attribute-field';
            row.dataset.attribute = def.name;
            if (!visible(def, values)) row.hidden = true;
            const id = `${options.idPrefix}-${def.name}`.replace(/[^A-Za-z0-9_-]/g, '_');
            const caption = def.name + (def.required ? ' *' : '');
            const value = values[def.name];

            const commit = (newValue) => {
                if (newValue === undefined) delete values[def.name];
                else values[def.name] = newValue;
                fields.querySelectorAll('.attribute-field').forEach(other => {
                    const otherDef = defs.find(d => d.name === other.dataset.attribute);
                    other.hidden = !visible(otherDef, values);
                });
                if (options.onChange) options.onChange(values);
            };

            if (def.type === 'multi') {
                const group = document.createElement('fieldset');
                group.className = 'attribute-multi';
                const legend = document.createElement('legend');
                legend.textContent = caption;
                group.appendChild(legend);
                const chosen = Array.isArray(value) ? value : [];
                def.options.forEach(option => {
                    const label = document.createElement('label');
                    const box = document.createElement('input');
                    box.type = 'checkbox';
                    box.value = option;
                    box.checked = chosen.includes(option);
                    box.addEventListener('change', () => {
                        const picked = [...group.querySelectorAll('input:checked')].map(b => b.value);
                        commit(picked.length ? picked : undefined);
                    });
                    label.appendChild(box);
                    label.appendChild(document.createTextNode(' ' + option));
                    group.appendChild(label);
                });
                row.appendChild(group);
            } else {
                const label = document.createElement('label');
                label.setAttribute('for', id);
                label.textContent = caption;
                row.appendChild(label);
                let control;
                if (def.type === 'select') {
                    control = document.createElement('select');
                    const blank = document.createElement('option');
                    blank.value = '';
                    blank.textContent = '—';
                    control.appendChild(blank);
                    def.options.forEach(option => {
                        const opt = document.createElement('option');
                        opt.value = option;
                        opt.textContent = option;
                        control.appendChild(opt);
                    });
                    control.value = value === undefined ? '' : value;
                    control.addEventListener('change', () =>
                        commit(control.value === '' ? undefined : control.value));
                } else if (def.type === 'bool') {
                    control = document.createElement('input');
                    control.type = 'checkbox';
                    control.checked = value === true;
                    control.addEventListener('change', () => commit(control.checked));
                } else if (def.type === 'number') {
                    control = document.createElement('input');
                    control.type = 'number';
                    if (def.min !== undefined) control.min = def.min;
                    if (def.max !== undefined) control.max = def.max;
                    control.value = value === undefined ? '' : value;
                    control.addEventListener('change', () => {
                        const n = parseFloat(control.value);
                        commit(Number.isFinite(n) ? n : undefined);
                    });
                } else {
                    control = document.createElement('input');
                    control.type = 'text';
                    control.value = value === undefined ? '' : value;
                    control.addEventListener('change', () =>
                        commit(control.value === '' ? undefined : control.value));
                }
                control.id = id;
                control.className = 'attribute-control';
                // Keys typed here are the annotator's, not the tool's shortcuts.
                control.addEventListener('keydown', e => e.stopPropagation());
                row.appendChild(control);
            }
            if (def.description) {
                const help = document.createElement('small');
                help.className = 'attribute-help';
                help.textContent = def.description;
                row.appendChild(help);
            }
            fields.appendChild(row);
        });
    }

    const api = { defsFor, visible, missing, defaults, incomplete, updateRequirement, render };
    if (typeof window !== 'undefined') window.ObjectAttributes = api;
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
})();
