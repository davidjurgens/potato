/*
 * Triad designs for triad_test, the browser half of
 * potato/cultural_domain/triads.py. Keep the two in step:
 * tests/unit/test_triad_design.py runs this file in Node and compares.
 *
 *   complete  every C(n,3) triad (auto: while there are at most 20)
 *   steiner   every pair exactly once (n = 1 or 3 mod 6; Bose / Skolem)
 *   sample    greedy, pair counts as even as possible, seeded
 *
 * The design depends on the domain only; the triad order and the item
 * positions are shuffled per participant, item and scheme.
 */
(function (root, factory) {
    var api = factory();
    if (typeof module === 'object' && module.exports) { module.exports = api; }
    else { root.PotatoTriadDesign = api; }
})(typeof self !== 'undefined' ? self : this, function () {
    'use strict';

    var COMPLETE_MAX = 20;

    function utf8(text) {
        if (typeof TextEncoder !== 'undefined') { return new TextEncoder().encode(text); }
        var s = unescape(encodeURIComponent(text)), out = [];
        for (var i = 0; i < s.length; i++) { out.push(s.charCodeAt(i)); }
        return out;
    }

    function fnv1a(text) {
        var bytes = utf8(String(text)), h = 0x811c9dc5;
        for (var i = 0; i < bytes.length; i++) {
            h ^= bytes[i];
            h = Math.imul(h, 0x01000193) >>> 0;
        }
        return h >>> 0;
    }

    function mulberry32(seed) {
        var a = seed >>> 0;
        return function () {
            a = (a + 0x6D2B79F5) >>> 0;
            var t = a;
            t = Math.imul(t ^ (t >>> 15), t | 1);
            t = ((t + Math.imul(t ^ (t >>> 7), t | 61)) >>> 0) ^ t;
            return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
        };
    }

    function shuffle(values, rng) {
        for (var i = values.length - 1; i > 0; i--) {
            var j = Math.floor(rng() * (i + 1));
            var tmp = values[i]; values[i] = values[j]; values[j] = tmp;
        }
        return values;
    }

    function choose3(n) {
        return n < 3 ? 0 : n * (n - 1) * (n - 2) / 6;
    }

    function complete(n) {
        var out = [];
        for (var a = 0; a < n; a++) {
            for (var b = a + 1; b < n; b++) {
                for (var c = b + 1; c < n; c++) { out.push([a, b, c]); }
            }
        }
        return out;
    }

    function steinerExists(n) {
        return n >= 3 && (n % 6 === 1 || n % 6 === 3);
    }

    function steiner(n) {
        var blocks = [], x, y, i;
        if (n % 6 === 3) {
            var v = n / 3, half = (v + 1) / 2;
            var p = function (x, i) { return x + v * (i % 3); };
            for (x = 0; x < v; x++) { blocks.push([p(x, 0), p(x, 1), p(x, 2)]); }
            for (x = 0; x < v; x++) {
                for (y = x + 1; y < v; y++) {
                    var z = ((x + y) * half) % v;
                    for (i = 0; i < 3; i++) { blocks.push([p(x, i), p(y, i), p(z, i + 1)]); }
                }
            }
        } else {
            var t = (n - 1) / 6, m = 2 * t, inf = n - 1;
            var q = function (x, i) { return x + m * (i % 3); };
            var op = function (x, y) {
                var s = (x + y) % m;
                return s % 2 === 0 ? s / 2 : t + (s - 1) / 2;
            };
            for (x = 0; x < t; x++) { blocks.push([q(x, 0), q(x, 1), q(x, 2)]); }
            for (x = 0; x < t; x++) {
                for (i = 0; i < 3; i++) { blocks.push([inf, q(x + t, i), q(x, i + 1)]); }
            }
            for (x = 0; x < m; x++) {
                for (y = x + 1; y < m; y++) {
                    for (i = 0; i < 3; i++) { blocks.push([q(x, i), q(y, i), q(op(x, y), i + 1)]); }
                }
            }
        }
        blocks = blocks.map(function (b) { return b.slice().sort(function (u, w) { return u - w; }); });
        blocks.sort(function (u, w) { return (u[0] - w[0]) || (u[1] - w[1]) || (u[2] - w[2]); });
        return blocks;
    }

    function sample(n, size, seed) {
        var candidates = shuffle(complete(n), mulberry32(seed));
        var limit = size == null ? candidates.length : Math.min(size, candidates.length);
        var pair = [], item = [], used = [], chosen = [], i;
        for (i = 0; i < n; i++) { pair.push(new Array(n).fill(0)); item.push(0); }
        var uncovered = n * (n - 1) / 2;
        while (chosen.length < limit && (size != null || uncovered > 0)) {
            var best = -1, bestScore = Infinity;
            for (var idx = 0; idx < candidates.length; idx++) {
                if (used[idx]) { continue; }
                var c = candidates[idx], a = c[0], b = c[1], d = c[2];
                var ab = pair[a][b], ad = pair[a][d], bd = pair[b][d];
                var score = Math.max(ab, ad, bd) * 1000000 + (ab + ad + bd) * 1000 +
                    item[a] + item[b] + item[d];
                if (score < bestScore) { best = idx; bestScore = score; }
            }
            used[best] = true;
            var tr = candidates[best];
            [[tr[0], tr[1]], [tr[0], tr[2]], [tr[1], tr[2]]].forEach(function (pq) {
                if (pair[pq[0]][pq[1]] === 0) { uncovered--; }
                pair[pq[0]][pq[1]]++;
                pair[pq[1]][pq[0]]++;
            });
            item[tr[0]]++; item[tr[1]]++; item[tr[2]]++;
            chosen.push(tr.slice());
        }
        return chosen;
    }

    function resolve(n, design, maxTriads) {
        design = design || 'auto';
        if (design === 'steiner' && !steinerExists(n)) { return 'sample'; }
        if (design !== 'auto') { return design; }
        var total = choose3(n);
        if (total <= COMPLETE_MAX && (maxTriads == null || total <= maxTriads)) { return 'complete'; }
        if (steinerExists(n) && (maxTriads == null || n * (n - 1) / 6 <= maxTriads)) { return 'steiner'; }
        return 'sample';
    }

    function designSeed(schema, domain) {
        return fnv1a('triad-design\x1f' + schema + '\x1f' + domain.join('\x1f'));
    }

    function build(domain, schema, design, maxTriads) {
        var n = domain.length;
        if (n < 3) { throw new Error('a triad test needs at least three items'); }
        var kind = resolve(n, design, maxTriads);
        var triads = kind === 'complete' ? complete(n)
            : kind === 'steiner' ? steiner(n)
            : sample(n, maxTriads == null ? null : maxTriads, designSeed(schema, domain));
        return {design: kind, triads: triads};
    }

    /* The triads one participant sees, in order, each in shown position order. */
    function plan(domain, schema, userId, instanceId, design, maxTriads) {
        var built = build(domain, schema, design, maxTriads);
        var rng = mulberry32(fnv1a(userId + '\x1f' + instanceId + '\x1f' + schema));
        var order = [];
        for (var i = 0; i < built.triads.length; i++) { order.push(i); }
        shuffle(order, rng);
        var shown = order.map(function (idx) {
            var positions = shuffle([0, 1, 2], rng), tr = built.triads[idx];
            return positions.map(function (p) { return domain[tr[p]]; });
        });
        return {design: built.design, triads: shown};
    }

    function domainItems(raw) {
        var out = [];
        (raw || []).forEach(function (entry) {
            if (entry && typeof entry === 'object') { entry = entry.name != null ? entry.name : entry.text; }
            if (entry == null) { return; }
            var text = String(entry).trim();
            if (text && out.indexOf(text) < 0) { out.push(text); }
        });
        return out;
    }

    return {fnv1a: fnv1a, mulberry32: mulberry32, shuffle: shuffle, complete: complete,
            steinerExists: steinerExists, steiner: steiner, sample: sample, resolve: resolve,
            build: build, plan: plan, domainItems: domainItems};
});
