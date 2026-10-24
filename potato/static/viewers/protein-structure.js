/*
 * protein_structure viewer adapter (3Dmol.js by default, Mol* on request).
 *
 * Selection items are residues: {chain, resi, resn[, icode]}. The annotator
 * toggles one by clicking it in the 3D view or in the residue table; the
 * table is rendered by the server and works without WebGL. Selected residues
 * are drawn as sticks (3Dmol) or with Mol*'s selection marking.
 */
(function () {
    'use strict';
    var FW = window.PotatoViewerFramework;
    if (!FW || FW.__proteinStructure) { return; }
    FW.__proteinStructure = true;

    var WATER = {HOH: 1, WAT: 1, DOD: 1, H2O: 1, SOL: 1, TIP: 1, TIP3: 1, SPC: 1};
    var ONE = {ALA: 'A', ARG: 'R', ASN: 'N', ASP: 'D', CYS: 'C', GLN: 'Q', GLU: 'E', GLY: 'G',
               HIS: 'H', ILE: 'I', LEU: 'L', LYS: 'K', MET: 'M', PHE: 'F', PRO: 'P', SER: 'S',
               THR: 'T', TRP: 'W', TYR: 'Y', VAL: 'V', SEC: 'U', PYL: 'O', MSE: 'M'};
    var SELECTED = '#c2255c';   // matches viewer_selection's first label colour

    function normalizeItem(item) {
        if (!item || typeof item !== 'object') { return null; }
        var resi = typeof item.resi === 'number' ? item.resi : parseInt(item.resi, 10);
        if (!isFinite(resi) || typeof item.chain !== 'string') { return null; }
        var out = {chain: item.chain, resi: resi, resn: String(item.resn || '').toUpperCase()};
        if (item.icode && String(item.icode).trim()) { out.icode = String(item.icode).trim(); }
        return out;
    }

    function key(item) { return item.chain + '|' + item.resi + '|' + (item.icode || ''); }

    function describe(item) {
        if (!item) { return ''; }
        var text = (item.resn || '?') + ' ' + item.resi + (item.icode || '') +
            (item.chain ? ', chain ' + item.chain : '');
        return item.label ? text + ' (' + item.label + ')' : text;
    }

    function cssVar(el, name, fallback) {
        var v = getComputedStyle(el).getPropertyValue(name);
        return (v && v.trim()) || fallback;
    }

    // ------------------------------------------------------------------
    // Fetching the file
    // ------------------------------------------------------------------

    function fetchStructure(cfg) {
        return fetch(cfg.url, {credentials: 'same-origin'}).then(function (r) {
            if (!r.ok) { throw new Error('the structure file returned HTTP ' + r.status); }
            return r.arrayBuffer();
        }).then(function (buf) {
            var bytes = new Uint8Array(buf);
            var gz = bytes.length > 2 && bytes[0] === 0x1f && bytes[1] === 0x8b;
            if (!gz) { return bytes; }
            if (typeof DecompressionStream === 'undefined') {
                throw new Error('this browser cannot read gzipped structures');
            }
            var stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
            return new Response(stream).arrayBuffer().then(function (b) { return new Uint8Array(b); });
        }).then(function (bytes) {
            if (cfg.format === 'bcif') { return bytes; }
            return new TextDecoder('utf-8').decode(bytes);
        });
    }

    function plddtColor(cfg, b) {
        if (b === null || b === undefined || isNaN(b)) { return '#9aa0a6'; }
        var v = b * (cfg.plddtScale || 1);
        var bands = cfg.plddtBands || [];
        for (var i = 0; i < bands.length; i++) {
            if (bands[i].min === null || v > bands[i].min) { return bands[i].color; }
        }
        return '#9aa0a6';
    }

    // ------------------------------------------------------------------
    // The residue table
    // ------------------------------------------------------------------

    function cellOf(button) {
        return {chain: button.getAttribute('data-chain') || '',
                resi: parseInt(button.getAttribute('data-resi'), 10),
                resn: button.getAttribute('data-resn') || '',
                icode: button.getAttribute('data-icode') || ''};
    }

    function wireTable(ctx) {
        var root = ctx.element.querySelector('.pv-residues');
        if (!root || root.__pvWired) { return; }
        root.__pvWired = true;
        var viewer = ctx.viewer;
        root.addEventListener('click', function (e) {
            var btn = e.target.closest && e.target.closest('.pv-res');
            if (!btn || !root.contains(btn)) { return; }
            focusCell(btn);
            viewer.toggleItem(cellOf(btn));
        });
        root.addEventListener('keydown', function (e) {
            var btn = e.target.closest && e.target.closest('.pv-res');
            if (!btn) { return; }
            var strip = btn.parentElement;
            var cells = Array.prototype.slice.call(strip.querySelectorAll('.pv-res'));
            var i = cells.indexOf(btn), next = null;
            if (e.key === 'ArrowRight') { next = cells[i + 1]; }
            else if (e.key === 'ArrowLeft') { next = cells[i - 1]; }
            else if (e.key === 'Home') { next = cells[0]; }
            else if (e.key === 'End') { next = cells[cells.length - 1]; }
            else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { next = verticalNeighbour(cells, btn, e.key === 'ArrowDown'); }
            else { return; }
            // The page binds the arrow keys to previous/next item; inside the
            // table they move between residues instead.
            e.preventDefault();
            e.stopPropagation();
            if (next) { focusCell(next); next.focus(); }
        });
        viewer.addPainter(function (sel) { paintTable(root, viewer, sel); });
    }

    function focusCell(btn) {
        var strip = btn.parentElement;
        strip.querySelectorAll('.pv-res[tabindex="0"]').forEach(function (b) { b.setAttribute('tabindex', '-1'); });
        btn.setAttribute('tabindex', '0');
    }

    function verticalNeighbour(cells, btn, down) {
        var top = btn.offsetTop, left = btn.offsetLeft, best = null, bestDx = Infinity;
        var targetTop = null;
        cells.forEach(function (c) {
            if (down ? c.offsetTop > top : c.offsetTop < top) {
                if (targetTop === null || (down ? c.offsetTop < targetTop : c.offsetTop > targetTop)) {
                    targetTop = c.offsetTop;
                }
            }
        });
        if (targetTop === null) { return null; }
        cells.forEach(function (c) {
            if (c.offsetTop !== targetTop) { return; }
            var dx = Math.abs(c.offsetLeft - left);
            if (dx < bestDx) { bestDx = dx; best = c; }
        });
        return best;
    }

    function paintTable(root, viewer, sel) {
        var picked = {};
        sel.items.forEach(function (it) { picked[key(it)] = it; });
        root.querySelectorAll('.pv-res').forEach(function (btn) {
            var item = picked[key(normalizeItem(cellOf(btn)))];
            btn.setAttribute('aria-pressed', item ? 'true' : 'false');
            var colour = item ? viewer.colorFor(item) : null;
            if (colour) { btn.style.setProperty('--pv-sel', colour); }
            else { btn.style.removeProperty('--pv-sel'); }
        });
    }

    function scrollToCell(ctx, item) {
        var root = ctx.element.querySelector('.pv-residues');
        if (!root) { return; }
        var sel = '.pv-res[data-chain="' + CSS.escape(item.chain) + '"][data-resi="' + item.resi + '"]';
        var btn = root.querySelector(sel);
        if (btn && btn.scrollIntoView) { btn.scrollIntoView({block: 'nearest', inline: 'nearest'}); }
    }

    /* For a structure the server could not read (a remote URL), build the
       table from the loaded model, with the same markup the server writes. */
    function buildTable(ctx, residues) {
        var root = ctx.element.querySelector('.pv-residues');
        if (!root) { return; }
        var holder = root.querySelector('.pv-chains');
        var note = root.querySelector('.pv-residues-note');
        if (!holder) { return; }
        var limit = ctx.config.tableLimit || 3000;
        if (residues.length > limit) {
            if (note) { note.textContent = 'This structure has ' + residues.length +
                ' residues, more than the table shows (' + limit + '). Select residues in the 3D view.'; }
            return;
        }
        if (note) { note.remove(); }
        holder.innerHTML = '';
        var byChain = {}, order = [];
        residues.forEach(function (r) {
            if (!byChain[r.chain]) { byChain[r.chain] = []; order.push(r.chain); }
            byChain[r.chain].push(r);
        });
        order.forEach(function (chain) {
            var wrap = document.createElement('div');
            wrap.className = 'pv-chain';
            wrap.setAttribute('data-chain', chain);
            var name = document.createElement('div');
            name.className = 'pv-chain-name';
            name.id = ctx.element.id + '-chain-' + chain.replace(/[^A-Za-z0-9]/g, '_');
            name.textContent = chain ? 'Chain ' + chain + ' ' : 'No chain ID ';
            var count = document.createElement('span');
            count.className = 'pv-count';
            count.textContent = byChain[chain].length + ' residues';
            name.appendChild(count);
            var strip = document.createElement('div');
            strip.className = 'pv-res-strip';
            strip.setAttribute('role', 'group');
            strip.setAttribute('aria-labelledby', name.id);
            byChain[chain].forEach(function (r, n) {
                var b = document.createElement('button');
                var number = r.resi + (r.icode || '');
                b.type = 'button';
                b.className = 'pv-res' + (r.het ? ' pv-het' : '') + ((n === 0 || r.resi % 10 === 0) ? ' pv-tick' : '');
                b.setAttribute('data-chain', r.chain);
                b.setAttribute('data-resi', String(r.resi));
                b.setAttribute('data-resn', r.resn);
                if (r.icode) { b.setAttribute('data-icode', r.icode); }
                b.setAttribute('aria-pressed', 'false');
                b.setAttribute('tabindex', n === 0 ? '0' : '-1');
                b.setAttribute('aria-label', r.resn + ' ' + number + ', chain ' + (chain || 'none'));
                b.title = r.resn + ' ' + number;
                var code = document.createElement('span');
                code.className = 'pv-res-code';
                code.setAttribute('aria-hidden', 'true');
                code.textContent = r.het ? r.resn : (ONE[r.resn] || r.resn);
                var num = document.createElement('span');
                num.className = 'pv-res-num';
                num.setAttribute('aria-hidden', 'true');
                num.textContent = number;
                b.appendChild(code);
                b.appendChild(num);
                strip.appendChild(b);
            });
            wrap.appendChild(name);
            wrap.appendChild(strip);
            holder.appendChild(wrap);
        });
        paintTable(root, ctx.viewer, ctx.viewer.getSelection());
    }

    // ------------------------------------------------------------------
    // PAE image beside the structure
    // ------------------------------------------------------------------

    function loadPae(ctx) {
        var cfg = ctx.config;
        var fig = ctx.element.querySelector('.pv-pae');
        if (!cfg.paeField || !fig) { return; }
        ctx.instanceData().then(function (data) {
            var url = ctx.resolveMedia(data && data[cfg.paeField]);
            if (!url) { return; }
            var img = fig.querySelector('img');
            img.onload = function () { fig.hidden = false; };
            img.onerror = function () { fig.hidden = true; };
            img.src = url;
        }).catch(function () { /* no PAE for this item */ });
    }

    // ------------------------------------------------------------------
    // 3Dmol.js
    // ------------------------------------------------------------------

    function start3Dmol(ctx, data) {
        var cfg = ctx.config, el = ctx.element, viewer = ctx.viewer;
        var $3D = window.$3Dmol;
        if (!$3D) { throw new Error('3Dmol.js did not load'); }
        var gl = $3D.createViewer(ctx.stage, {
            backgroundColor: cssVar(el, '--card', '#ffffff'),
            antialias: true
        });
        var format = cfg.format === 'bcif' ? 'bcif' : (cfg.format === 'pdb' ? 'pdb' : 'cif');
        var model = gl.addModel(data, format);
        if (!model || !model.selectedAtoms({}).length) {
            throw new Error('no atoms could be read from the structure file');
        }
        var colorBy = cfg.colorBy || 'chain';
        var base = {cartoon: {}};
        if (cfg.plddt) {
            base.cartoon.colorfunc = function (atom) { return plddtColor(cfg, atom.b); };
        } else if (colorBy === 'spectrum') {
            base.cartoon.color = 'spectrum';
        } else if (colorBy === 'secondary') {
            base.cartoon.colorscheme = 'ssJmol';
        } else {
            base.cartoon.colorscheme = 'chain';
        }
        var water = {resn: Object.keys(WATER)};

        function paint(sel) {
            gl.setStyle({}, base);
            gl.setStyle(water, {});
            if (cfg.showLigands) {
                gl.addStyle({hetflag: true, not: water}, {stick: {radius: 0.2}});
                // A lone ion has no bonds, so a stick draws nothing.
                gl.addStyle({hetflag: true, bonds: 0, not: water}, {sphere: {scale: 0.45}});
            }
            sel.items.forEach(function (it) {
                var spec = {chain: it.chain, resi: it.resi};
                if (it.icode) { spec.icode = it.icode; }
                var colour = viewer.colorFor(it) || SELECTED;
                gl.addStyle(spec, {stick: {radius: 0.28, color: colour}});
            });
            gl.render();
        }

        function itemOf(atom) {
            return normalizeItem({chain: atom.chain || '', resi: atom.resi, resn: atom.resn,
                                  icode: atom.icode});
        }

        gl.setClickable({}, true, function (atom) {
            if (!atom || WATER[atom.resn]) { return; }
            var item = itemOf(atom);
            if (!item) { return; }
            var adding = !viewer.hasItem(item);
            viewer.toggleItem(item);
            ctx.status((adding ? 'Selected ' : 'Deselected ') + describe(item));
            if (adding) { scrollToCell(ctx, item); }
        });
        gl.setHoverable({}, true, function (atom) {
            if (!atom || WATER[atom.resn]) { return; }
            var text = describe(itemOf(atom));
            if (cfg.plddt && atom.b !== undefined) {
                text += ' · pLDDT ' + (atom.b * (cfg.plddtScale || 1)).toFixed(1);
            }
            ctx.status(text);
        }, function () {});

        viewer.addPainter(paint);
        gl.zoomTo();
        gl.render();
        viewer.engine = gl;

        if (cfg.tableFromModel) {
            var seen = {}, residues = [];
            model.selectedAtoms({}).forEach(function (a) {
                if (WATER[a.resn]) { return; }
                var k = (a.chain || '') + '|' + a.resi + '|' + (a.icode || '');
                if (seen[k]) { return; }
                seen[k] = true;
                residues.push({chain: a.chain || '', resi: a.resi, resn: a.resn,
                               icode: a.icode || '', het: !!a.hetflag});
            });
            buildTable(ctx, residues);
        }

        if (window.ResizeObserver) {
            new ResizeObserver(function () { gl.resize(); gl.render(); }).observe(ctx.stage);
        }
    }

    // ------------------------------------------------------------------
    // Mol*
    // ------------------------------------------------------------------

    /* Mol*'s confidence theme reads ma_qa_metric_local (as in AlphaFold DB
       mmCIF files). The hierarchy is filled a little after the load promise
       resolves, so wait for it rather than theming nothing. */
    function applyMolstarPlddt(plugin, attempt) {
        var structures = plugin.managers.structure.hierarchy.current.structures;
        if (!structures.length && attempt < 20) {
            setTimeout(function () { applyMolstarPlddt(plugin, attempt + 1); }, 100);
            return;
        }
        structures.forEach(function (s) {
            Promise.resolve(plugin.managers.structure.component.updateRepresentationsTheme(
                s.components, {color: 'plddt-confidence'})).catch(function (e) {
                console.warn('pLDDT colouring needs ma_qa_metric_local in the mmCIF', e);
            });
        });
    }

    function startMolstar(ctx, data) {
        var cfg = ctx.config, viewer = ctx.viewer;
        var ms = window.molstar;
        if (!ms || !ms.Viewer) { throw new Error('Mol* did not load'); }
        return ms.Viewer.create(ctx.stage, {
            layoutIsExpanded: false,
            layoutShowControls: false,
            layoutShowRemoteState: false,
            layoutShowSequence: false,
            layoutShowLog: false,
            layoutShowLeftPanel: false,
            viewportShowExpand: false,
            viewportShowSelectionMode: false,
            viewportShowAnimation: false,
            collapseLeftPanel: true
        }).then(function (mv) {
            viewer.engine = mv;
            var binary = cfg.format === 'bcif';
            var fmt = cfg.format === 'pdb' ? 'pdb' : 'mmcif';
            return mv.loadStructureFromData(binary ? data : String(data), fmt, {dataLabel: cfg.field})
                .then(function () { return mv; });
        }).then(function (mv) {
            var plugin = mv.plugin;
            if (cfg.plddt) { applyMolstarPlddt(plugin, 0); }
            var lib = ms.lib && ms.lib.structure;
            plugin.behaviors.interaction.click.subscribe(function (ev) {
                var loci = ev && ev.current && ev.current.loci;
                if (!lib || !loci || !lib.StructureElement.Loci.is(loci)) { return; }
                var loc = lib.StructureElement.Loci.getFirstLocation(loci);
                if (!loc) { return; }
                var P = lib.StructureProperties;
                var item = normalizeItem({
                    chain: P.chain.auth_asym_id(loc),
                    resi: P.residue.auth_seq_id(loc),
                    resn: P.atom.auth_comp_id(loc),
                    icode: P.residue.pdbx_PDB_ins_code(loc)
                });
                if (!item || WATER[item.resn]) { return; }
                var adding = !viewer.hasItem(item);
                viewer.toggleItem(item);
                ctx.status((adding ? 'Selected ' : 'Deselected ') + describe(item));
                if (adding) { scrollToCell(ctx, item); }
            });
            viewer.addPainter(function (sel) {
                if (!sel.items.length) {
                    mv.structureInteractivity({action: 'select'});
                    return;
                }
                mv.structureInteractivity({
                    action: 'select',
                    elements: sel.items.map(function (it) {
                        var e = {auth_asym_id: it.chain, auth_seq_id: it.resi};
                        if (it.icode) { e.pdbx_PDB_ins_code = it.icode; }
                        return e;
                    })
                });
            });
            if (cfg.tableFromModel) {
                var note = ctx.element.querySelector('.pv-residues-note');
                if (note) { note.textContent = 'The residue table is not available for a remote structure shown in Mol*; select residues in the 3D view.'; }
            }
        });
    }

    FW.register('protein_structure', {
        context: [],
        key: key,
        normalizeItem: normalizeItem,
        describe: describe,
        fallbackHint: 'Select residues in the residue table below instead.',
        init: function (ctx) {
            wireTable(ctx);
            loadPae(ctx);
        },
        start: function (ctx) {
            ctx.status('');
            return fetchStructure(ctx.config).then(function (data) {
                if (ctx.config.engine === 'molstar') { return startMolstar(ctx, data); }
                return start3Dmol(ctx, data);
            });
        }
    });
})();
