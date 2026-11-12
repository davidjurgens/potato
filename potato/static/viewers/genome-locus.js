/*
 * genome_locus viewer adapter (igv.js).
 *
 * The selection is the current locus ({locus: "chr1:1450-1550"}) plus the
 * features the annotator clicks on a variant or annotation track, each
 * {chr, start, end, kind, name, track[, ref, alt]} with 1-based inclusive
 * positions. Selected features are shaded as igv regions of interest.
 *
 * igv.js draws with canvas 2D, so there is no WebGL requirement. Data files
 * are read from /media/ with HTTP range requests; nothing is fetched from the
 * internet unless the display sets allow_remote.
 */
(function () {
    'use strict';
    var FW = window.PotatoViewerFramework;
    if (!FW || FW.__genomeLocus) { return; }
    FW.__genomeLocus = true;

    var SELECTED = 'rgba(232, 89, 12, 0.28)';

    function toInt(v) {
        var n = typeof v === 'number' ? v : parseFloat(String(v || '').replace(/,/g, ''));
        return isFinite(n) ? Math.round(n) : null;
    }

    function normalizeItem(item) {
        if (!item || typeof item !== 'object' || !item.chr) { return null; }
        var start = toInt(item.start), end = toInt(item.end);
        if (start === null) { return null; }
        if (end === null || end < start) { end = start; }
        var out = {chr: String(item.chr), start: start, end: end};
        ['kind', 'name', 'track', 'ref', 'alt'].forEach(function (k) {
            if (item[k] !== undefined && item[k] !== null && item[k] !== '') { out[k] = String(item[k]); }
        });
        return out;
    }

    function key(item) {
        return [item.chr, item.start, item.end, item.ref || '', item.alt || ''].join('|');
    }

    function fmt(n) { return Number(n).toLocaleString('en-US'); }

    function describe(item) {
        if (!item || !item.chr) { return ''; }
        var where = item.chr + ':' + fmt(item.start) + (item.end !== item.start ? '-' + fmt(item.end) : '');
        var what = item.ref && item.alt ? item.ref + '>' + item.alt : '';
        var name = item.name && item.name !== '.' ? item.name : '';
        var bits = [where, name, what].filter(Boolean).join(' ');
        if (item.track) { bits += ' (' + item.track + ')'; }
        return item.label ? bits + ' [' + item.label + ']' : bits;
    }

    function describeContext(sel) {
        return sel && sel.locus ? 'view ' + sel.locus : '';
    }

    /* "chr1:1,450-1,550" -> "chr1:1450-1550" */
    function normalizeLocus(text) {
        // igv reports fractional ends ("chr1:1141-1253.8") while zoomed in.
        var m = /^\s*([^\s:]+)(?::\s*([\d,.]+)(?:\s*-\s*([\d,.]+))?)?\s*$/.exec(String(text || ''));
        if (!m) { return null; }
        if (!m[2]) { return m[1]; }
        var a = toInt(m[2]), b = m[3] ? toInt(m[3]) : a;
        return m[1] + ':' + a + '-' + b;
    }

    function popupValue(data, name) {
        for (var i = 0; i < (data || []).length; i++) {
            var row = data[i];
            if (row && row.name === name) { return String(row.value); }
        }
        return null;
    }

    /* The loaded variant under a genomic location, or null. A click on a
       genotype cell gets the sample's popup (Sample, Genotype, ...) with no
       Chr or Pos, though it is the larger target for the same call. */
    function variantAt(track, location) {
        if (typeof location !== 'number') { return null; }
        var views = (track.trackView && track.trackView.viewports) || [];
        for (var i = 0; i < views.length; i++) {
            var features = views[i].cachedFeatures;
            if (!Array.isArray(features)) { continue; }
            for (var j = 0; j < features.length; j++) {
                var f = features[j];
                if (f && f.chr && f.start <= location && location < Math.max(f.end, f.start + 1)) { return f; }
            }
        }
        return null;
    }

    /* The feature under a click, as a selection item, or null. */
    function featureFromClick(track, popupData, clicked, location) {
        var type = track && track.type;
        if (type === 'variant') {
            var chr = popupValue(popupData, 'Chr');
            var pos = popupValue(popupData, 'Pos');
            if ((!chr || !pos) && popupValue(popupData, 'Genotype') !== null) {
                var v = variantAt(track, location);
                if (v) {
                    var alts = Array.isArray(v.alternateBases) ? v.alternateBases.join(',') : (v.alternateBases || '');
                    var vref = v.referenceBases || '';
                    return normalizeItem({chr: v.chr, start: v.start + 1,
                                          end: v.start + Math.max(vref.length, 1),
                                          kind: 'variant', name: (v.names || v.id || '').toString(),
                                          ref: vref, alt: alts, track: track.name});
                }
            }
            if (!chr || !pos) { return null; }
            var start = toInt(pos.split('|')[0].split('-')[0]);
            var ref = popupValue(popupData, 'Ref') || '';
            var alt = (popupValue(popupData, 'Alt') || '').replace(/&lt;/g, '<');
            return normalizeItem({chr: chr, start: start, end: start + Math.max(ref.length, 1) - 1,
                                  kind: 'variant', name: popupValue(popupData, 'ID') || '',
                                  ref: ref, alt: alt, track: track.name});
        }
        if (type === 'annotation' && clicked && clicked.length) {
            var f = clicked[0];
            return normalizeItem({chr: f.chr, start: f.start + 1, end: f.end, kind: 'feature',
                                  name: f.name || f.id || '', track: track.name});
        }
        return null;
    }

    var EXT = {bam: 'bam', cram: 'cram', vcf: 'vcf', bed: 'bed', gff3: 'gff3', gff: 'gff',
               gtf: 'gtf', bb: 'bigbed', bigbed: 'bigbed', bw: 'bigwig', bigwig: 'bigwig',
               bedgraph: 'bedgraph', bdg: 'bedgraph', wig: 'wig'};
    var TYPE = {bam: 'alignment', cram: 'alignment', vcf: 'variant', bigwig: 'wig',
                bedgraph: 'wig', wig: 'wig'};

    function formatOf(url) {
        var base = String(url || '').split('?')[0].toLowerCase().replace(/\.b?gz$/, '');
        var m = /\.([a-z0-9]+)$/.exec(base);
        return m ? (EXT[m[1]] || null) : null;
    }

    /* Why an item's file reference cannot be used, or '' when it can. The
       server checks configured files (resolve_source); a field track's file
       comes from the item, so it is checked here, where it is read. */
    function refusal(ctx, value, what) {
        var text = String(value === undefined || value === null ? '' : value).trim();
        if (!text) { return 'this item has no ' + what; }
        if (/^(https?:)?\/\//i.test(text)) {
            return ctx.config.allowRemote ? '' : 'the ' + what + ' "' + text + '" is a remote URL, and ' +
                'remote files are turned off (allow_remote)';
        }
        if (/^[a-z][a-z0-9+.-]*:/i.test(text)) {
            return 'the ' + what + ' "' + text + '" is not a file path';
        }
        var path = text.replace(/\\/g, '/');
        if (path.charAt(0) === '/' && path.indexOf('/media/') !== 0) {
            return 'the ' + what + ' "' + text + '" is outside the media directory';
        }
        if (path.split('/').indexOf('..') !== -1) {
            return 'the ' + what + ' "' + text + '" points outside the media directory';
        }
        return '';
    }

    function trackConfig(ctx, t, data, problems) {
        var url = t.url, index = t.indexURL, format = t.format;
        if (t.field) {
            var why = refusal(ctx, data[t.field], 'file in field "' + t.field + '"');
            url = why ? null : ctx.resolveMedia(data[t.field]);
            if (!url) {
                problems.push('Track "' + t.name + '" is not shown: ' + (why || 'its file cannot be loaded') + '.');
                return null;
            }
            format = format || formatOf(url);
            if (!format) {
                problems.push('Track "' + t.name + '" is not shown: cannot tell the format of "' +
                              data[t.field] + '" (name it .bam, .cram, .vcf.gz, .bed ... or set format:).');
                return null;
            }
            if (t.indexField) {
                var whyIndex = refusal(ctx, data[t.indexField], 'index in field "' + t.indexField + '"');
                if (whyIndex) {
                    problems.push('Track "' + t.name + '" is not shown: ' + whyIndex + '.');
                    return null;
                }
                index = ctx.resolveMedia(data[t.indexField]);
            }
            else if (t.indexed !== false) { index = defaultIndex(url, format); }
        }
        var out = {name: t.name, type: t.type || TYPE[format] || 'annotation', format: format, url: url};
        if (index) { out.indexURL = index; } else { out.indexed = false; }
        if (t.height) { out.height = t.height; }
        if (t.color) { out.color = t.color; }
        if (t.displayMode) { out.displayMode = t.displayMode; }
        return out;
    }

    function defaultIndex(url, format) {
        if (format === 'bam') { return url + '.bai'; }
        if (format === 'cram') { return url + '.crai'; }
        if (/\.b?gz$/i.test(url.split('?')[0])) { return url + '.tbi'; }
        return null;
    }

    /* Kept on screen, unlike the status line, which the next selection
       message replaces. */
    function showTrackProblems(ctx, problems) {
        var note = ctx.element.querySelector('.pv-track-note');
        if (!note) {
            note = document.createElement('p');
            note.className = 'pv-track-note pv-error';
            note.setAttribute('role', 'alert');
            note.style.cssText = 'margin:0.25rem 0;padding:0.375rem 0.5rem;' +
                'border-radius:var(--radius-sm, 4px);font-size:var(--text-sm, 0.8125rem);';
            var status = ctx.element.querySelector('.pv-status');
            ctx.element.insertBefore(note, status || null);
        }
        note.textContent = problems.join(' ') + ' Tell the researcher.';
    }

    function start(ctx) {
        var cfg = ctx.config, viewer = ctx.viewer;
        if (!window.igv) { throw new Error('igv.js did not load'); }
        var needsData = (cfg.tracks || []).some(function (t) { return t.field; });
        var dataPromise = needsData ? ctx.instanceData() : Promise.resolve({});
        var initial = viewer.getSelection().locus || cfg.locus;
        return dataPromise.then(function (data) {
            var tracks = [], problems = [];
            (cfg.tracks || []).forEach(function (t) {
                var tc = trackConfig(ctx, t, data || {}, problems);
                if (tc) { tracks.push(tc); }
            });
            var options = {
                locus: initial,
                tracks: tracks,
                showSampleNames: true,
                // Do not ask igv.org for its genome list: everything this
                // page reads comes from this server unless allow_remote is on.
                loadDefaultGenomes: false
            };
            if (cfg.reference) { options.reference = cfg.reference; }
            else if (cfg.genome) { options.genome = cfg.genome; }
            if (problems.length) { showTrackProblems(ctx, problems); }
            return window.igv.createBrowser(ctx.stage, options);
        }).then(function (browser) {
            viewer.engine = browser;

            function currentLocus() {
                try {
                    var loci = browser.currentLoci();
                    return normalizeLocus(Array.isArray(loci) ? loci[0] : loci);
                } catch (e) { return null; }
            }

            // igv fires locuschange for its own layout passes too (the first
            // draw, a resize, the search a restore triggers). Only a change
            // that follows the annotator's own input -- a drag, the wheel,
            // the zoom buttons, the locus box -- is a change to the
            // selection, or merely opening an item would count as an answer.
            // A click on a track (selecting a feature) is not navigation;
            // a drag is, and so is anything in igv's navigation bar.
            var lastInput = 0, downAt = null;
            var mark = function () { lastInput = Date.now(); };
            var opts = {capture: true, passive: true};
            ctx.stage.addEventListener('wheel', mark, opts);
            ctx.stage.addEventListener('keydown', mark, opts);
            ctx.stage.addEventListener('pointerdown', function (e) {
                downAt = {x: e.clientX, y: e.clientY};
                if (e.target.closest && e.target.closest('.igv-navbar, .igv-ruler-sweeper, .igv-windowsize-panel-container')) { mark(); }
            }, opts);
            ctx.stage.addEventListener('pointermove', function (e) {
                if (downAt && Math.abs(e.clientX - downAt.x) > 3) { mark(); }
            }, opts);
            ctx.stage.addEventListener('pointerup', function () { downAt = null; }, opts);
            browser.on('locuschange', function () {
                if (Date.now() - lastInput > 2500) { return; }
                var locus = currentLocus();
                if (locus) { viewer.setContext('locus', locus); }
            });

            browser.on('trackclick', function (track, popupData, genomicLocation, clicked) {
                if (!cfg.selectFeatures) { return undefined; }
                var item = featureFromClick(track, popupData, clicked, genomicLocation);
                if (!item) { return undefined; }     // igv's own popup
                var adding = !viewer.hasItem(item);
                viewer.toggleItem(item);
                ctx.status((adding ? 'Selected ' : 'Deselected ') + describe(item));
                return false;
            });

            var lastLocus = initial;
            viewer.addPainter(function (sel) {
                paintRegions(browser, viewer, sel.items);
                if (sel.locus && sel.locus !== lastLocus) {
                    lastLocus = sel.locus;
                    if (sel.locus !== currentLocus()) { browser.search(sel.locus); }
                }
            });
            ctx.element.querySelector('.pv-stage').removeAttribute('role');
        });
    }

    /* Selected features as igv regions of interest, one group per colour. */
    function paintRegions(browser, viewer, items) {
        try { browser.clearROIs(); } catch (e) { /* none yet */ }
        if (!items.length) { return; }
        var groups = {};
        items.forEach(function (it) {
            var colour = viewer.colorFor(it) ? hexToRgba(viewer.colorFor(it), 0.3) : SELECTED;
            (groups[colour] = groups[colour] || []).push(
                {chr: it.chr, start: it.start - 1, end: it.end, name: describe(it)});
        });
        var configs = Object.keys(groups).map(function (colour) {
            return {name: 'Selected', color: colour, features: groups[colour]};
        });
        Promise.resolve().then(function () { return browser.loadROI(configs); })
            .catch(function (e) { console.warn('igv regions could not be drawn', e); });
    }

    function hexToRgba(hex, alpha) {
        var m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || '');
        if (!m) { return SELECTED; }
        return 'rgba(' + parseInt(m[1], 16) + ', ' + parseInt(m[2], 16) + ', ' +
            parseInt(m[3], 16) + ', ' + alpha + ')';
    }

    FW.register('genome_locus', {
        context: ['locus'],
        key: key,
        normalizeItem: normalizeItem,
        describe: describe,
        describeContext: describeContext,
        init: function (ctx) {
            ctx.viewer._selection.locus = normalizeLocus(ctx.config.locus);
        },
        start: start
    });
})();
