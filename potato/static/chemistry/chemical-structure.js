/*
 * chemical_structure scheme: draw or correct a structure in OpenChemLib's
 * canvas editor, or paste a SMILES / molfile.
 *
 * The answer is one hidden input holding JSON: molfile V3000, OpenChemLib
 * canonical SMILES, ID code and formula, plus RDKit SMILES, InChI and
 * InChIKey when RDKit.js is installed. A pre-filled structure (prefill_field)
 * is saved as the answer with changed: false until the annotator edits it.
 * Valence problems and an empty canvas are reported on the form's
 * data-incomplete-reason, which the page's required-field check reads.
 */
(function () {
    'use strict';
    if (window.PotatoChemicalStructure) { return; }
    var CHEM = window.PotatoChem;
    var STATES = new WeakMap();

    function instanceId() {
        var input = document.getElementById('instance_id');
        return input ? input.value : '';
    }

    function readStored(input) {
        if (!input || !input.value) { return null; }
        try {
            var v = JSON.parse(input.value);
            return v && typeof v === 'object' ? v : null;
        } catch (e) { return null; }
    }

    function fetchInstance() {
        return fetch('/api/instance_data', {credentials: 'same-origin'}).then(function (r) {
            return r.ok ? r.json() : {};
        }).catch(function () { return {}; });
    }

    function isStructurePath(v) {
        return typeof v === 'string' && v.indexOf('\n') < 0 && /\.(mol|sdf|smi|smiles)\s*$/i.test(v);
    }

    /* The prefill text for this item: inline, or a file in the media directory. */
    function prefillText(state) {
        var field = state.cfg.prefillField;
        if (!field) { return Promise.resolve(null); }
        return fetchInstance().then(function (data) {
            var value = data ? data[field] : null;
            if (value === null || value === undefined || value === '') { return null; }
            if (!isStructurePath(value)) { return String(value); }
            var url = window.PotatoViewerFramework ? window.PotatoViewerFramework.resolveMedia(value, false)
                : '/media/' + String(value).replace(/^media\//, '');
            if (!url) { return null; }
            return fetch(url, {credentials: 'same-origin'}).then(function (r) {
                if (!r.ok) { throw new Error('HTTP ' + r.status); }
                return r.text();
            }).then(function (text) {
                if (text.length > 1000000) { throw new Error('the file is over 1 MB'); }
                if (/\.sdf\s*$/i.test(value)) { return text.split('$$$$')[0]; }
                if (/\.(smi|smiles)\s*$/i.test(value)) {
                    var line = text.split(/\r?\n/).filter(function (l) { return l.trim(); })[0] || '';
                    return line.trim().split(/\s+/)[0];
                }
                return text;
            });
        });
    }

    function parse(state, text, format) {
        var OCL = state.OCL;
        var t = String(text || '');
        if (!t.trim()) { return null; }
        var fmt = format && format !== 'auto' ? format : (CHEM.looksLikeMolfile(t) ? 'molfile' : 'smiles');
        return fmt === 'molfile' ? OCL.Molecule.fromMolfile(t) : OCL.Molecule.fromSmiles(t.trim());
    }

    /* A done message, unless the structure has problems: those stay on screen. */
    function notice(state, value, text) {
        if (value && value.problems && value.problems.length) {
            say(state, text + ' ' + value.problems.join(' '), 'warn');
        } else {
            say(state, text, 'ok');
        }
    }

    function say(state, text, kind) {
        state.problems.textContent = text || '';
        state.problems.className = 'cs-problems' + (kind ? ' cs-' + kind : '');
    }

    // ------------------------------------------------------------------
    // Reading the drawing
    // ------------------------------------------------------------------

    function describe(state) {
        var mol = state.editor.getMolecule();
        var ids = CHEM.identifiersOCL(state.OCL, mol);
        if (ids.empty) { return null; }
        var out = {
            molfile: ids.molfile, smiles: ids.smiles, idcode: ids.idcode, formula: ids.formula,
            problems: ids.problems.slice(),
            toolkits: {openchemlib: state.cfg.oclVersion}
        };
        if (state.RDKit) {
            var r = CHEM.identifiersRDKit(state.RDKit, ids.molfile);
            out.toolkits.rdkit = state.RDKit.version();
            if (r.valid) {
                out.rdkit_smiles = r.rdkit_smiles;
                if (r.inchi) { out.inchi = r.inchi; out.inchikey = r.inchikey; }
            } else {
                out.problems.push('RDKit cannot sanitize this structure (check valences, charges and aromatic rings).');
            }
        }
        return out;
    }

    function showReadout(state, value) {
        var f = state.form;
        var set = function (sel, text) {
            var node = f.querySelector(sel);
            if (node && text !== null) { node.textContent = text; }
        };
        set('.cs-smiles', value ? value.smiles : '–');
        set('.cs-formula', value ? (value.formula || '–') : '–');
        if (state.RDKit) { set('.cs-inchikey', value && value.inchikey ? value.inchikey : '–'); }
    }

    function declare(state, value) {
        var reasons = [];
        if (!value && !state.cfg.allowEmpty) { reasons.push('draw a structure'); }
        if (value && state.cfg.requireValid && value.problems && value.problems.length) {
            reasons.push('fix the structure: ' + value.problems[0]);
        }
        if (state.failed) { reasons.push('the structure editor did not load'); }
        if (reasons.length) { state.form.setAttribute('data-incomplete-reason', reasons.join('; ')); }
        else { state.form.removeAttribute('data-incomplete-reason'); }
    }

    function write(state, value, userMade) {
        state.input.value = value ? JSON.stringify(value) : '';
        if (userMade || value) {
            state.input.setAttribute('data-modified', 'true');
            state.input.dispatchEvent(new Event('change', {bubbles: true}));
        }
    }

    function refresh(state, userMade, quiet) {
        var value = describe(state);
        if (value) {
            var changed = state.prefillIdcode ? value.idcode !== state.prefillIdcode : true;
            if (!userMade && state.storedChanged !== undefined) { changed = state.storedChanged; }
            value.changed = changed;
        }
        showReadout(state, value);
        if (value && value.problems.length) { say(state, value.problems.join(' '), 'warn'); }
        else if (!state.keepMessage) { say(state, ''); }
        state.keepMessage = false;
        var reset = state.form.querySelector('.cs-reset');
        if (reset) { reset.disabled = !state.prefillIdcode || !value || value.idcode === state.prefillIdcode; }
        declare(state, value);
        if (!quiet) { write(state, value, userMade); }
        return value;
    }

    // ------------------------------------------------------------------
    // Setup
    // ------------------------------------------------------------------

    function setMolecule(state, mol) {
        state.applying = true;
        try {
            if (mol) { state.editor.setMolecule(mol); }
            else { state.editor.clearAll(); }
        } finally {
            state.applying = false;
        }
    }

    /* Wired once per form; each handler acts on the form's current state
       (a new item replaces the state, not the listeners). */
    function wireControls(form) {
        if (form.__csWired) { return; }
        form.__csWired = true;
        var paste = form.querySelector('.cs-paste');
        var current = function () {
            var s = STATES.get(form);
            return s && s.editor ? s : null;
        };
        form.querySelector('.cs-load').addEventListener('click', function () {
            var state = current();
            if (!state) { return; }
            var text = paste.value;
            if (!text.trim()) { say(state, 'Paste or type a SMILES string or a molfile first.', 'warn'); return; }
            var mol;
            try { mol = parse(state, text, 'auto'); } catch (e) { mol = null; }
            if (!mol || mol.getAllAtoms() === 0) {
                say(state, 'That is not a SMILES string or molfile OpenChemLib can read.', 'warn');
                return;
            }
            setMolecule(state, mol);
            state.storedChanged = undefined;
            notice(state, refresh(state, true), 'Loaded the structure from the text box.');
            state.keepMessage = true;
        });
        paste.addEventListener('keydown', function (e) {
            // The page binds the arrow keys and Enter; typing here must not navigate.
            e.stopPropagation();
            if (e.key === 'Enter' && !e.shiftKey && !CHEM.looksLikeMolfile(paste.value)) {
                e.preventDefault();
                form.querySelector('.cs-load').click();
            }
        });
        form.querySelector('.cs-clear').addEventListener('click', function () {
            var state = current();
            if (!state) { return; }
            setMolecule(state, null);
            state.storedChanged = undefined;
            refresh(state, true);
            say(state, 'Cleared the drawing.', 'ok');
            state.keepMessage = true;
        });
        var reset = form.querySelector('.cs-reset');
        if (reset) {
            reset.addEventListener('click', function () {
                var state = current();
                if (!state || !state.prefillText) { return; }
                setMolecule(state, parse(state, state.prefillText, state.cfg.prefillFormat));
                state.storedChanged = undefined;
                notice(state, refresh(state, true), 'Restored the given structure.');
                state.keepMessage = true;
            });
        }
    }

    function start(state) {
        var cfg = state.cfg;
        var rdkit = cfg.rdkit && cfg.rdkitMode !== false ? CHEM.loadRDKitScript(cfg.rdkit).catch(function (e) {
            console.warn('RDKit.js is installed but did not start; continuing with OpenChemLib only.', e);
            return null;
        }) : Promise.resolve(null);
        return Promise.all([CHEM.loadOCL(cfg.oclUrl), rdkit, prefillText(state).catch(function (e) {
            say(state, 'The given structure could not be read (' + e.message + ').', 'warn');
            return null;
        })]).then(function (r) {
            state.OCL = r[0];
            state.RDKit = r[1];
            state.prefillText = r[2];
            var host = state.form.querySelector('.cs-editor');
            host.innerHTML = '';
            state.editor = new state.OCL.CanvasEditor(host, {initialMode: 'molecule'});
            state.loading.hidden = true;
            if (state.prefillText) {
                try {
                    var pre = parse(state, state.prefillText, cfg.prefillFormat);
                    state.prefillIdcode = pre && pre.getAllAtoms() ? pre.getIDCode() : null;
                } catch (e) {
                    state.prefillText = null;
                    say(state, 'The given structure is not a SMILES string or molfile OpenChemLib can read.', 'warn');
                }
            }
            var stored = readStored(state.input);
            var startText = stored && stored.molfile ? stored.molfile : state.prefillText;
            if (stored) { state.storedChanged = stored.changed; }
            if (startText) {
                try { setMolecule(state, parse(state, startText, stored && stored.molfile ? 'molfile' : cfg.prefillFormat)); }
                catch (e) { console.error('chemical_structure: could not read the stored structure', e); }
            }
            // A stored answer is already on the server: show it, write nothing.
            // An untouched prefill is written, so Next saves it as the answer.
            if (stored || state.prefillText) { refresh(state, false, !!stored); }
            else { showReadout(state, null); declare(state, null); }
            var timer = null;
            state.editor.setOnChangeListener(function (event) {
                if (state.applying || !event || !event.isUserEvent) { return; }
                clearTimeout(timer);
                timer = setTimeout(function () {
                    state.storedChanged = undefined;
                    refresh(state, true);
                }, 250);
            });
            if (cfg.rdkitMode === true && !state.RDKit) {
                say(state, 'RDKit.js is required by this task but is not available; InChIKeys are not computed.', 'warn');
            }
        }).catch(function (err) {
            console.error('chemical_structure failed to start', err);
            state.failed = true;
            state.loading.hidden = false;
            state.loading.textContent = 'The structure editor could not load: ' + (err && err.message ? err.message : err);
            state.loading.classList.add('cs-error');
            declare(state, readStored(state.input));
        });
    }

    function setup(form) {
        var prior = STATES.get(form);
        if (prior && prior.instance === instanceId()) { return; }
        if (prior && prior.editor) {
            try { prior.editor.destroy(); } catch (e) { /* already gone */ }
        }
        var cfg;
        try { cfg = JSON.parse(form.getAttribute('data-chem-config') || '{}'); }
        catch (e) { cfg = {}; }
        var state = {
            form: form, cfg: cfg, instance: instanceId(),
            input: form.querySelector('.chemical-structure-input'),
            problems: form.querySelector('.cs-problems'),
            loading: form.querySelector('.cs-loading')
        };
        STATES.set(form, state);
        declare(state, readStored(state.input));
        wireControls(form);
        start(state);
    }

    function init() {
        if (!CHEM) { return; }
        document.querySelectorAll('form.chemical-structure').forEach(setup);
    }

    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); }
    else { setTimeout(init, 0); }
    document.addEventListener('instanceChanged', init);
    document.addEventListener('potato:instance-ready', init);

    window.PotatoChemicalStructure = {init: init, _states: STATES};
})();
