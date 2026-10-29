/*
 * Chemistry toolkits for the chemical_structure scheme and the molecule
 * display: loading OpenChemLib (an ES module, committed) and RDKit.js (a
 * WebAssembly build fetched with `potato vendor fetch rdkit`), the SMILES
 * atom tokenizer that pins atom indices to the source as written, and the
 * SVG sanitizer and theming both drawings go through.
 *
 * window.PotatoChem = {
 *   loadOCL(url) -> Promise<OCL>, loadRDKit(wasmUrl) -> Promise<RDKit>,
 *   smilesAtoms(smiles) -> [{element, bracket, hydrogen}],
 *   looksLikeMolfile(text), depict(engine, toolkit, source, format, size)
 *     -> {svg: SVGElement, atoms: [{atom, element, x, y, selectable}], note}
 *   identifiersOCL(OCL, mol), identifiersRDKit(RDKit, molfile)
 * }
 */
(function () {
    'use strict';
    if (window.PotatoChem) { return; }

    var oclPromise = null, rdkitPromise = null;

    function loadOCL(url) {
        if (!oclPromise) {
            // A dynamic import: the build is an ES module (export {...}).
            oclPromise = import(url).then(function (mod) {
                return mod && mod.Molecule ? mod : (mod && mod.default) || mod;
            }).catch(function (err) {
                oclPromise = null;
                throw new Error('OpenChemLib did not load (' + (err && err.message || err) + ')');
            });
        }
        return oclPromise;
    }

    function loadRDKit(wasmUrl) {
        if (!rdkitPromise) {
            if (typeof window.initRDKitModule !== 'function') {
                return Promise.reject(new Error('RDKit.js did not load'));
            }
            rdkitPromise = window.initRDKitModule({
                locateFile: function () { return wasmUrl; }
            }).catch(function (err) {
                rdkitPromise = null;
                throw new Error('RDKit.js did not start (' + (err && err.message || err) + ')');
            });
        }
        return rdkitPromise;
    }

    function loadScript(src) {
        return new Promise(function (resolve, reject) {
            if (document.querySelector('script[data-chem-src="' + src + '"]')) {
                if (typeof window.initRDKitModule === 'function') { resolve(); return; }
            }
            var node = document.createElement('script');
            node.src = src;
            node.async = false;
            node.setAttribute('data-chem-src', src);
            node.onload = function () { resolve(); };
            node.onerror = function () { reject(new Error('Could not load ' + src)); };
            document.head.appendChild(node);
        });
    }

    function loadRDKitScript(urls) {
        if (typeof window.initRDKitModule === 'function') { return loadRDKit(urls.wasm); }
        return loadScript(urls.js).then(function () { return loadRDKit(urls.wasm); });
    }

    function looksLikeMolfile(text) {
        return typeof text === 'string' && (text.indexOf('M  END') >= 0 ||
            text.indexOf('V2000') >= 0 || text.indexOf('V3000') >= 0);
    }

    // ------------------------------------------------------------------
    // SMILES atoms in source order
    // ------------------------------------------------------------------

    var ORGANIC = /^(Cl|Br|B|C|N|O|P|S|F|I|b|c|n|o|p|s|\*)/;

    /* The atoms of a SMILES string, in the order written. Bracket atoms
       ([NH4+], [2H], [C@@H]) are one atom each; ring-closure digits, bonds,
       branches and dots are not atoms. */
    function smilesAtoms(smiles) {
        var out = [], i = 0, s = String(smiles || '');
        while (i < s.length) {
            var ch = s.charAt(i);
            if (ch === '[') {
                var end = s.indexOf(']', i);
                if (end < 0) { break; }
                var body = s.slice(i + 1, end);
                var m = /^(\d*)([A-Z][a-z]?|[a-z][a-z]?|\*)/.exec(body);
                var el = m ? m[2] : '?';
                if (el.length === 2 && el === el.toLowerCase() && !/^(se|as|te)$/.test(el)) {
                    el = el.charAt(0);
                }
                var symbol = el.charAt(0).toUpperCase() + el.slice(1);
                out.push({element: symbol, bracket: true,
                          // A plain hydrogen ([H], [H+] excluded): OpenChemLib folds it away.
                          hydrogen: symbol === 'H' && !m[1] && /^H(?![+-])/.test(body.slice(m[1].length))});
                i = end + 1;
                continue;
            }
            var om = ORGANIC.exec(s.slice(i));
            if (om) {
                var e = om[1];
                out.push({element: e === '*' ? '*' : e.charAt(0).toUpperCase() + e.slice(1),
                          bracket: false, hydrogen: false});
                i += e.length;
                continue;
            }
            if (ch === '%') { i += 3; continue; }
            i += 1;
        }
        return out;
    }

    // ------------------------------------------------------------------
    // SVG sanitizing and theming
    // ------------------------------------------------------------------

    var SVG_NS = 'http://www.w3.org/2000/svg';
    var ALLOWED_TAGS = {svg: 1, g: 1, line: 1, polygon: 1, polyline: 1, path: 1, circle: 1,
                        ellipse: 1, rect: 1, text: 1, tspan: 1};
    var ALLOWED_ATTRS = {x: 1, y: 1, x1: 1, y1: 1, x2: 1, y2: 1, cx: 1, cy: 1, r: 1, rx: 1, ry: 1,
                         d: 1, points: 1, width: 1, height: 1, viewBox: 1, fill: 1, stroke: 1,
                         'stroke-width': 1, 'stroke-linecap': 1, 'stroke-linejoin': 1,
                         'stroke-dasharray': 1, 'font-size': 1, 'font-family': 1, 'font-weight': 1,
                         'text-anchor': 1, 'dominant-baseline': 1, opacity: 1, 'fill-opacity': 1,
                         'stroke-opacity': 1, transform: 1, 'class': 1, id: 1, style: 1};

    function parseColor(text) {
        if (!text) { return null; }
        var t = String(text).trim();
        var m = /^rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)$/i.exec(t);
        if (m) { return [+m[1], +m[2], +m[3]]; }
        m = /^#([0-9a-f]{6})([0-9a-f]{2})?$/i.exec(t);
        if (m) {
            if (m[2] && parseInt(m[2], 16) === 0) { return 'transparent'; }
            return [parseInt(m[1].slice(0, 2), 16), parseInt(m[1].slice(2, 4), 16),
                    parseInt(m[1].slice(4, 6), 16)];
        }
        return null;
    }

    function luminance(rgb) {
        var c = rgb.map(function (v) {
            v /= 255;
            return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
        });
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
    }

    /* Black (bonds, carbon labels) becomes currentColor, so the drawing
       follows the theme's text colour. In dark mode the element colours a
       toolkit picks for a white page (blue N, dark red O) are lightened
       until they read on the dark card. */
    function themeColor(value, dark) {
        var rgb = parseColor(value);
        if (rgb === 'transparent') { return 'none'; }
        if (!rgb) { return value; }
        if (rgb[0] < 40 && rgb[1] < 40 && rgb[2] < 40) { return 'currentColor'; }
        if (rgb[0] > 245 && rgb[1] > 245 && rgb[2] > 245) { return 'none'; }   // white backgrounds
        var out = rgb.slice(), k;
        if (!dark) {
            // Bright greens and yellows (Cl, S, F) are unreadable on white.
            for (k = 0; k < 8 && luminance(out) > 0.3; k++) {
                out = out.map(function (v) { return Math.round(v * 0.8); });
            }
            return k ? 'rgb(' + out.join(',') + ')' : value;
        }
        for (k = 0; k < 8 && luminance(out) < 0.28; k++) {
            out = out.map(function (v) { return Math.round(v + (255 - v) * 0.25); });
        }
        return 'rgb(' + out.join(',') + ')';
    }

    function styleToAttrs(node) {
        var style = node.getAttribute('style');
        if (!style) { return; }
        style.split(';').forEach(function (decl) {
            var idx = decl.indexOf(':');
            if (idx < 0) { return; }
            var k = decl.slice(0, idx).trim(), v = decl.slice(idx + 1).trim();
            if (ALLOWED_ATTRS[k] && k !== 'style' && !/url\(|expression|javascript/i.test(v)) {
                node.setAttribute(k, v);
            }
        });
        node.removeAttribute('style');
    }

    function cleanNode(src, dark) {
        var tag = src.localName;
        if (!ALLOWED_TAGS[tag]) { return null; }
        var node = document.createElementNS(SVG_NS, tag);
        Array.prototype.forEach.call(src.attributes, function (a) {
            var name = a.localName;
            if (!ALLOWED_ATTRS[name] || /^on/i.test(name)) { return; }
            if (/url\(|javascript:/i.test(a.value)) { return; }
            node.setAttribute(name === 'class' ? 'data-src-class' : name, a.value);
        });
        styleToAttrs(node);
        ['fill', 'stroke'].forEach(function (k) {
            if (node.hasAttribute(k)) { node.setAttribute(k, themeColor(node.getAttribute(k), dark)); }
        });
        Array.prototype.forEach.call(src.childNodes, function (child) {
            if (child.nodeType === 3) { node.appendChild(document.createTextNode(child.nodeValue)); }
            else if (child.nodeType === 1) {
                var c = cleanNode(child, dark);
                if (c) { node.appendChild(c); }
            }
        });
        return node;
    }

    function sanitizeSvg(text, dark) {
        var doc = new DOMParser().parseFromString(String(text), 'image/svg+xml');
        var root = doc.documentElement;
        if (!root || root.localName !== 'svg' || doc.querySelector('parsererror')) {
            throw new Error('the drawing could not be read');
        }
        var svg = cleanNode(root, dark);
        svg.removeAttribute('id');
        return svg;
    }

    function isDark() {
        return document.documentElement.getAttribute('data-theme') === 'dark';
    }

    // ------------------------------------------------------------------
    // OpenChemLib
    // ------------------------------------------------------------------

    function oclMolecule(OCL, source, format) {
        var text = String(source || '');
        if (format === 'molfile' || (format !== 'smiles' && looksLikeMolfile(text))) {
            var r = OCL.Molecule.fromMolfileWithAtomMap(text);
            // r.map[sourceIndex] = OpenChemLib atom index
            var map = [];
            for (var i = 0; i < r.molecule.getAllAtoms() + 64 && r.map[i] !== undefined; i++) {
                map.push(r.map[i]);
            }
            return {mol: r.molecule, toSource: invert(map, r.molecule.getAllAtoms()), sourceCount: map.length};
        }
        var mol = OCL.Molecule.fromSmiles(text.trim());
        var written = smilesAtoms(text.trim());
        var toSource = [];
        var n = mol.getAllAtoms();
        var folded = written.some(function (a) { return a.hydrogen; });
        var same = !folded && written.length === n;
        for (var j = 0; same && j < n; j++) {
            if (labelOf(mol, j) !== written[j].element && written[j].element !== '*') { same = false; }
        }
        for (var k = 0; k < n; k++) { toSource.push(same ? k : null); }
        return {mol: mol, toSource: toSource, sourceCount: written.length,
                note: same ? '' : (folded ?
                    'This SMILES writes hydrogens as separate atoms ([H]). OpenChemLib draws them as part of their neighbour, so atoms cannot be selected here; give a molfile, or use engine: rdkit.' :
                    'OpenChemLib read this SMILES with a different atom order, so atoms cannot be selected here; give a molfile, or use engine: rdkit.')};
    }

    function invert(map, n) {
        var out = [];
        for (var i = 0; i < n; i++) { out.push(null); }
        map.forEach(function (oclIndex, sourceIndex) {
            if (oclIndex !== null && oclIndex >= 0 && oclIndex < n) { out[oclIndex] = sourceIndex; }
        });
        return out;
    }

    function labelOf(mol, i) {
        var label = mol.getAtomLabel(i);
        return label === '?' ? '*' : label;
    }

    var svgCounter = 0;

    function bondLength(size) {
        return Math.max(20, Math.min(48, Math.round(Math.min(size.width, size.height) / 6.5)));
    }

    function depictOCL(OCL, source, format, size) {
        var parsed = oclMolecule(OCL, source, format);
        var mol = parsed.mol;
        var id = 'pchem' + (++svgCounter);
        // OpenChemLib draws with a 24 px bond unless told otherwise, which
        // leaves a small molecule tiny in a large stage.
        var avbl = bondLength(size);
        var text = mol.toSVG(size.width, size.height, id, {
            autoCrop: false, suppressChiralText: true, maxAVBL: avbl, inflateToMaxAVBL: true,
            factorTextSize: 1.1, strokeWidth: 1.5});
        var svg = sanitizeSvg(text, isDark());
        var atoms = [];
        var circles = svg.querySelectorAll('circle[data-src-class="event"]');
        var hit = {};
        Array.prototype.forEach.call(circles, function (c) {
            var m = /:Atom:(\d+)$/.exec(c.getAttribute('id') || '');
            if (m) { hit[+m[1]] = {x: +c.getAttribute('cx'), y: +c.getAttribute('cy')}; }
        });
        // Event targets go; the adapter draws its own.
        Array.prototype.forEach.call(svg.querySelectorAll('[data-src-class="event"]'), function (n) {
            n.parentNode.removeChild(n);
        });
        for (var i = 0; i < mol.getAllAtoms(); i++) {
            var pos = hit[i];
            if (!pos) { continue; }
            var src = parsed.toSource[i];
            atoms.push({atom: src === null ? null : src, element: labelOf(mol, i), x: pos.x, y: pos.y,
                        selectable: src !== null});
        }
        atoms.sort(function (a, b) {
            if (a.atom === null) { return 1; }
            if (b.atom === null) { return -1; }
            return a.atom - b.atom;
        });
        return {svg: svg, atoms: atoms, note: parsed.note || '', atomCount: mol.getAllAtoms()};
    }

    // ------------------------------------------------------------------
    // RDKit
    // ------------------------------------------------------------------

    var ELEMENTS = ['*', 'H', 'He', 'Li', 'Be', 'B', 'C', 'N', 'O', 'F', 'Ne', 'Na', 'Mg', 'Al', 'Si',
        'P', 'S', 'Cl', 'Ar', 'K', 'Ca', 'Sc', 'Ti', 'V', 'Cr', 'Mn', 'Fe', 'Co', 'Ni', 'Cu', 'Zn',
        'Ga', 'Ge', 'As', 'Se', 'Br', 'Kr', 'Rb', 'Sr', 'Y', 'Zr', 'Nb', 'Mo', 'Tc', 'Ru', 'Rh', 'Pd',
        'Ag', 'Cd', 'In', 'Sn', 'Sb', 'Te', 'I', 'Xe', 'Cs', 'Ba', 'La', 'Ce', 'Pr', 'Nd', 'Pm', 'Sm',
        'Eu', 'Gd', 'Tb', 'Dy', 'Ho', 'Er', 'Tm', 'Yb', 'Lu', 'Hf', 'Ta', 'W', 'Re', 'Os', 'Ir', 'Pt',
        'Au', 'Hg', 'Tl', 'Pb', 'Bi', 'Po', 'At', 'Rn'];

    function rdkitMol(RDKit, source, format) {
        var text = String(source || '');
        var details = JSON.stringify({removeHs: false});
        var mol = RDKit.get_mol(format === 'smiles' ? text.trim() : text, details);
        if (!mol || !mol.is_valid()) {
            if (mol) { mol.delete(); }
            return null;
        }
        return mol;
    }

    function depictRDKit(RDKit, source, format, size) {
        var mol = rdkitMol(RDKit, source, format);
        if (!mol) { throw new Error('RDKit could not read this structure'); }
        try {
            var info = JSON.parse(mol.get_json());
            var list = (info.molecules && info.molecules[0] && info.molecules[0].atoms) || [];
            var n = list.length;
            var all = [], colours = {};
            for (var i = 0; i < n; i++) { all.push(i); colours[i] = [1, 1, 1, 0]; }
            // Every atom highlighted in a transparent colour: the drawing then
            // reports each atom's centre (an <ellipse class="atom-i">), and
            // the layout does not change when the selection does.
            var text = mol.get_svg_with_highlights(JSON.stringify({
                atoms: all, bonds: [], highlightAtomColors: colours, width: size.width,
                height: size.height, backgroundColour: [1, 1, 1, 0], addStereoAnnotation: false,
                // Same bond length as the OpenChemLib drawing: a small molecule
                // is not blown up to fill the stage.
                fixedBondLength: bondLength(size)}));
            var svg = sanitizeSvg(text, isDark());
            var centres = {};
            Array.prototype.forEach.call(svg.querySelectorAll('ellipse'), function (e) {
                var m = /\batom-(\d+)\b/.exec(e.getAttribute('data-src-class') || '');
                if (m) {
                    centres[+m[1]] = {x: +e.getAttribute('cx'), y: +e.getAttribute('cy')};
                    e.parentNode.removeChild(e);
                }
            });
            var atoms = [];
            for (var j = 0; j < n; j++) {
                var c = centres[j];
                if (!c) { continue; }
                var z = typeof list[j].z === 'number' ? list[j].z : 6;
                atoms.push({atom: j, element: ELEMENTS[z] || '?', x: c.x, y: c.y, selectable: true});
            }
            return {svg: svg, atoms: atoms, note: '', atomCount: n};
        } finally {
            mol.delete();
        }
    }

    function depict(engine, toolkit, source, format, size) {
        return engine === 'rdkit' ? depictRDKit(toolkit, source, format, size)
                                  : depictOCL(toolkit, source, format, size);
    }

    // ------------------------------------------------------------------
    // Identifiers
    // ------------------------------------------------------------------

    /* Valence problems OpenChemLib can see, as plain sentences. */
    function oclProblems(OCL, mol) {
        var problems = [];
        mol.ensureHelperArrays(OCL.Molecule.cHelperRings);
        for (var i = 0; i < mol.getAllAtoms(); i++) {
            var occupied = mol.getOccupiedValence(i), max = mol.getMaxValence(i);
            if (occupied > max) {
                problems.push(labelOf(mol, i) + ' (atom ' + (i + 1) + ') has ' + occupied +
                    ' bonds; it allows ' + max + '.');
            }
        }
        return problems;
    }

    function identifiersOCL(OCL, mol) {
        var empty = mol.getAllAtoms() === 0;
        if (empty) { return {empty: true}; }
        var formula = '';
        try { formula = mol.getMolecularFormula().formula; } catch (e) { formula = ''; }
        return {
            empty: false,
            molfile: mol.toMolfileV3(),
            smiles: mol.toIsomericSmiles(),
            idcode: mol.getIDCode(),
            formula: formula,
            problems: oclProblems(OCL, mol)
        };
    }

    function identifiersRDKit(RDKit, molfile) {
        var mol = null;
        try {
            mol = RDKit.get_mol(molfile);
            if (!mol || !mol.is_valid()) {
                return {valid: false};
            }
            var out = {valid: true, rdkit_smiles: mol.get_smiles()};
            try {
                var inchi = mol.get_inchi();
                if (inchi) {
                    out.inchi = inchi;
                    out.inchikey = RDKit.get_inchikey_for_inchi(inchi);
                }
            } catch (e) { /* a build without InChI */ }
            return out;
        } finally {
            if (mol) { mol.delete(); }
        }
    }

    window.PotatoChem = {
        loadOCL: loadOCL,
        loadRDKit: loadRDKit,
        loadRDKitScript: loadRDKitScript,
        smilesAtoms: smilesAtoms,
        looksLikeMolfile: looksLikeMolfile,
        sanitizeSvg: sanitizeSvg,
        themeColor: themeColor,
        isDark: isDark,
        depict: depict,
        oclMolecule: oclMolecule,
        identifiersOCL: identifiersOCL,
        identifiersRDKit: identifiersRDKit
    };
})();
