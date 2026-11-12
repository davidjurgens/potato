/**
 * Live sessions: chemical_structure shows a teammate's structure without a
 * reload (chemistry/chemical-structure.js registers the applier).
 *
 * OpenChemLib is a WebAssembly bundle jsdom cannot run, so window.PotatoChem
 * hands the widget a small stand-in: the editor records the molecule it was
 * given on its host element, and identifiersOCL reports it as SMILES. The
 * readout and the editor host are what the test reads, as an annotator would.
 */

const { loadStatic, bootCollab, applyTeam, watchSaves, countChanges, flush } = require('./misc-collab-harness');

const MARKUP = `
    <form id="mol" class="annotation-form chemical-structure" action="javascript:void(0)"
          data-annotation-type="chemical_structure" data-schema-name="mol"
          data-chem-config='{&quot;schema&quot;: &quot;mol&quot;, &quot;oclUrl&quot;: &quot;/static/vendor/openchemlib-9.25.0/openchemlib.js&quot;, &quot;oclVersion&quot;: &quot;9.25.0&quot;, &quot;rdkit&quot;: null, &quot;rdkitMode&quot;: &quot;auto&quot;, &quot;prefillField&quot;: null, &quot;prefillFormat&quot;: &quot;auto&quot;, &quot;requireValid&quot;: true, &quot;allowEmpty&quot;: false}' data-grid-columns="1">
        <fieldset schema="mol">
            <legend class="cs-title">Draw</legend>
            
            <div class="cs-editor-wrap" style="height: 380px">
                <div class="cs-editor" role="application"
                     aria-label="Structure editor: draw with the mouse, or paste a SMILES or molfile below"></div>
                <p class="cs-loading" role="status">Loading the structure editor…</p>
            </div>
            <div class="cs-row">
                <label class="cs-paste-label" for="cs-mol-paste">SMILES or molfile</label>
                <textarea id="cs-mol-paste" class="cs-paste cs-mono" rows="1" spellcheck="false"
                          autocomplete="off" placeholder="Paste or type, then Load"></textarea>
                <div class="cs-actions">
                    <button type="button" class="cs-btn cs-load">Load</button>
                    
                    <button type="button" class="cs-btn cs-clear">Clear</button>
                </div>
            </div>
            <dl class="cs-readout" aria-label="Identifiers of the drawn structure"><div><dt>SMILES</dt><dd class="cs-smiles cs-mono">–</dd></div><div><dt>Formula</dt><dd class="cs-formula">–</dd></div><div><dt>InChIKey</dt><dd class="cs-inchikey cs-mono"><span class="cs-muted">needs RDKit.js (potato vendor fetch rdkit); filled in at export when the rdkit package is installed</span></dd></div></dl>
            <p class="cs-problems" role="status" aria-live="polite"></p>
            <input type="hidden" class="annotation-input chemical-structure-input"
                   id="mol_mol_hidden" name="mol:::mol"
                   schema="mol" label_name="mol"
                   validation="" value="">
        </fieldset>
    </form>
    `;

function fakeOCL() {
    const mol = (src) => ({ src, getAllAtoms: () => (src ? 3 : 0), getIDCode: () => 'id:' + src });
    function CanvasEditor(host) {
        this.host = host;
        this.mol = null;
        this.listeners = 0;
        host.setAttribute('data-mol', '');
    }
    CanvasEditor.prototype.setMolecule = function (m) { this.mol = m; this.host.setAttribute('data-mol', m.src); };
    CanvasEditor.prototype.clearAll = function () { this.mol = null; this.host.setAttribute('data-mol', ''); };
    CanvasEditor.prototype.getMolecule = function () { return this.mol || mol(''); };
    CanvasEditor.prototype.setOnChangeListener = function (fn) { this.listeners += 1; this.onChange = fn; };
    CanvasEditor.prototype.destroy = function () {};
    return { CanvasEditor, Molecule: { fromMolfile: mol, fromSmiles: mol } };
}

const stored = (src) => JSON.stringify({ molfile: src, smiles: 'S:' + src, idcode: 'id:' + src,
    formula: 'F', problems: [], changed: true, toolkits: { openchemlib: '9.25.0' } });

let client, calls, OCL;

async function boot(initial, prefill) {
    const markup = prefill
        ? MARKUP.replace('&quot;prefillField&quot;: null', '&quot;prefillField&quot;: &quot;given&quot;')
        : MARKUP;
    document.body.innerHTML = '<input type="hidden" id="instance_id" value="item-1">' + markup;
    // The prefill is read from the item before collab.js boots.
    window.fetch = jest.fn(() => Promise.resolve({
        ok: true, status: 200, json: () => Promise.resolve({ given: prefill || null }) }));
    if (initial) {
        const h = document.getElementById('mol_mol_hidden');
        h.value = initial;
        h.setAttribute('data-server-set', 'true');
    }
    OCL = fakeOCL();
    window.PotatoChem = {
        loadOCL: () => Promise.resolve(OCL),
        loadRDKitScript: () => Promise.resolve(null),
        looksLikeMolfile: (t) => /M {2}END/.test(t),
        identifiersOCL: (_ocl, m) => (m && m.src
            ? { empty: false, molfile: m.src, smiles: 'S:' + m.src, idcode: 'id:' + m.src, formula: 'F', problems: [] }
            : { empty: true, problems: [] }),
    };
    delete window.PotatoChemicalStructure;
    delete window.potatoCollabWidgets;
    loadStatic('chemistry/chemical-structure.js');
    await flush();            // init runs on a timeout
    await flush();            // the editor loads
    ({ client, calls } = bootCollab());
}

const host = () => document.querySelector('.cs-editor');
const smiles = () => document.querySelector('.cs-smiles').textContent;

describe('chemical_structure live applier', () => {
    test('the page draws its stored structure first', async () => {
        await boot(stored('benzene'));
        expect(host().getAttribute('data-mol')).toBe('benzene');
        expect(smiles()).toBe('S:benzene');
    });

    test("a teammate's structure replaces the one drawn", async () => {
        await boot(stored('benzene'));
        const shown = applyTeam(client, 'mol', { mol: stored('ethanol') });
        expect(shown.has('L:mol:::mol')).toBe(true);
        expect(host().getAttribute('data-mol')).toBe('ethanol');
        expect(smiles()).toBe('S:ethanol');
    });

    test('no answer clears the canvas and the readout', async () => {
        await boot(stored('benzene'));
        const shown = applyTeam(client, 'mol', null, ['mol']);
        expect(shown.has('L:mol:::mol')).toBe(true);
        expect(host().getAttribute('data-mol')).toBe('');
        expect(smiles()).toBe('–');
        expect(document.getElementById('mol').getAttribute('data-incomplete-reason')).toBe('draw a structure');
    });

    test('applying saves nothing and twice binds nothing twice', async () => {
        await boot(stored('benzene'));
        const watch = watchSaves(calls);
        const input = document.getElementById('mol_mol_hidden');
        const changes = countChanges(input);
        const editor = window.PotatoChemicalStructure._states.get(document.getElementById('mol')).editor;
        applyTeam(client, 'mol', { mol: stored('ethanol') });
        applyTeam(client, 'mol', { mol: stored('ethanol') });
        await flush();
        expect(changes.n).toBe(0);
        expect(input.hasAttribute('data-modified')).toBe(false);
        expect(input.value).toBe(stored('ethanol'));
        expect(watch.posts()).toHaveLength(0);
        expect(watch.saveAnnotations).not.toHaveBeenCalled();
        expect(editor.listeners).toBe(1);
        expect(host().getAttribute('data-mol')).toBe('ethanol');
    });

    test("the editor's late report of a cleared answer is not saved as an edit", async () => {
        // OpenChemLib reports clearAll() after it returns, flagged as a user
        // event; that used to write '' back as this member's answer.
        await boot(stored('benzene'));
        const watch = watchSaves(calls);
        const input = document.getElementById('mol_mol_hidden');
        const editor = window.PotatoChemicalStructure._states.get(document.getElementById('mol')).editor;
        applyTeam(client, 'mol', null, ['mol']);
        editor.onChange({ isUserEvent: true });
        await new Promise((r) => setTimeout(r, 300));
        expect(input.hasAttribute('data-modified')).toBe(false);
        expect(watch.posts()).toHaveLength(0);
        expect(watch.saveAnnotations).not.toHaveBeenCalled();

        // A drawing after it is an edit.
        editor.mol = { src: 'water', getAllAtoms: () => 3, getIDCode: () => 'id:water' };
        editor.onChange({ isUserEvent: true });
        await new Promise((r) => setTimeout(r, 300));
        expect(input.getAttribute('data-modified')).toBe('true');
        expect(JSON.parse(input.value).molfile).toBe('water');
    });
});

describe('chemical_structure live applier with a prefill', () => {
    test('a cleared answer shows the prefill, as a fresh load of the item does', async () => {
        await boot(null, 'CCO');
        const fresh = [host().getAttribute('data-mol'), smiles(),
            document.getElementById('mol').getAttribute('data-incomplete-reason')];
        expect(fresh[0]).toBe('CCO');

        await boot(stored('benzene'), 'CCO');
        const watch = watchSaves(calls);
        const input = document.getElementById('mol_mol_hidden');
        const changes = countChanges(input);
        applyTeam(client, 'mol', null, ['mol']);
        await flush();
        expect([host().getAttribute('data-mol'), smiles(),
            document.getElementById('mol').getAttribute('data-incomplete-reason')]).toEqual(fresh);
        // Shown, not saved: the cleared answer stays the team's answer.
        expect(changes.n).toBe(0);
        expect(input.hasAttribute('data-modified')).toBe(false);
        expect(input.value).toBe('');
        expect(watch.posts()).toHaveLength(0);
        expect(watch.saveAnnotations).not.toHaveBeenCalled();
    });
});
