/**
 * Shared placement helper for Potato's floating annotation widgets
 * (Boundary Lab, Truth Serum, Think-Aloud).
 *
 * Each is a position:fixed card pinned to a bottom corner of the viewport —
 * which is also where the Previous/Next controls live. On a short viewport the
 * card lands on top of a control and silently eats clicks meant for it: the
 * click hits the card's body, nothing happens, and the annotator gets no
 * feedback. Measured on a 922x674 viewport: Boundary Lab (bottom-right) made
 * Next unclickable; Truth Serum (bottom-left) made Previous unclickable.
 *
 * Naively lifting the card above the nav row just moves the problem — it then
 * covers the label radios, which is worse. So instead of one hard-coded nudge,
 * place() scores a few candidate positions against everything the annotator
 * needs to click (nav buttons, annotation inputs, and any other open widget)
 * and picks the one that covers the fewest.
 *
 * Always measure the LAYOUT box (offsetWidth/offsetHeight, clientHeight) for
 * the placement maths: these cards slide in with a translateY animation, and a
 * getBoundingClientRect() read mid-animation is offset by it.
 */
(function () {
    'use strict';

    var GAP = 12;
    var STEP = 20;   // horizontal scan resolution, in px

    /**
     * Rendered and non-empty.
     *
     * Deliberately NOT an `offsetParent !== null` test: offsetParent is always
     * null for position:fixed elements, which is exactly what every one of
     * these widgets is — that check silently dropped the other open panels from
     * the protected set, and they all piled onto the same spot.
     */
    function visible(el) {
        if (!el) return false;
        var cs = getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden') return false;
        var r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
    }

    /** Everything the annotator must be able to click while a card is open. */
    function protectedRects(panel) {
        var els = [];
        ['prev-btn', 'next-btn'].forEach(function (id) {
            var b = document.getElementById(id);
            if (visible(b)) els.push(b);
        });
        [].push.apply(els, [].slice.call(
            document.querySelectorAll('input.annotation-input')).filter(visible));
        // Other open widgets must not be covered either (the combined showcase
        // example runs several of these at once).
        [].push.apply(els, [].slice.call(
            document.querySelectorAll('.ts-panel, .boundary-panel, .ta-pill'))
            .filter(function (p) { return p !== panel && visible(p); }));
        return els.map(function (el) { return el.getBoundingClientRect(); });
    }

    function overlaps(a, b) {
        return !(a.right <= b.left || a.left >= b.right ||
                 a.bottom <= b.top || a.top >= b.bottom);
    }

    /** How many protected rects a candidate box would cover. */
    function score(box, rects) {
        var n = 0;
        for (var i = 0; i < rects.length; i++) if (overlaps(box, rects[i])) n++;
        return n;
    }

    function boxFor(left, bottom, w, h, viewportH) {
        return { left: left, right: left + w, top: viewportH - bottom - h, bottom: viewportH - bottom };
    }

    /**
     * Position a bottom-anchored fixed card so it covers as little interactive
     * UI as possible. Falls back to the card's CSS anchor when nothing collides.
     *
     * @param {HTMLElement} panel a visible, position:fixed, bottom-anchored card
     */
    function place(panel) {
        if (!panel) return;
        // Reset to the CSS anchor so we measure the authored position.
        panel.style.left = '';
        panel.style.right = '';
        panel.style.bottom = '';

        var w = panel.offsetWidth;
        var h = panel.offsetHeight;
        if (!w || !h) return;   // hidden: nothing to place

        var viewportW = document.documentElement.clientWidth;
        var viewportH = document.documentElement.clientHeight;
        var cs = getComputedStyle(panel);
        var baseBottom = parseFloat(cs.bottom) || 0;
        var baseLeft = panel.getBoundingClientRect().left;

        var rects = protectedRects(panel);
        if (!rects.length) return;

        var navTop = Math.min.apply(null, ['prev-btn', 'next-btn']
            .map(function (id) { return document.getElementById(id); })
            .filter(visible)
            .map(function (b) { return b.getBoundingClientRect().top; })
            .concat([Infinity]));

        var lifted = (navTop === Infinity)
            ? baseBottom
            : Math.max(0, Math.min(viewportH - navTop + GAP, viewportH - h - GAP));

        // Candidate positions. A coarse set (authored / centred only) is not
        // enough: with several widgets open, a clean side-by-side arrangement
        // can exist and still be missed, so scan the bottom band properly.
        var bottoms = [baseBottom];
        if (Math.abs(lifted - baseBottom) > 1) bottoms.push(lifted);
        var lefts = [baseLeft];
        var maxLeft = viewportW - w - GAP;
        for (var x = GAP; x <= maxLeft; x += STEP) lefts.push(x);
        if (maxLeft > GAP) lefts.push(maxLeft);

        // Fewest covered rects wins; ties go to whichever sits closest to the
        // position the widget's own CSS asked for, so an uncrowded page keeps
        // the authored design.
        var best = null;
        for (var bi = 0; bi < bottoms.length; bi++) {
            for (var li = 0; li < lefts.length; li++) {
                var b = bottoms[bi], l = lefts[li];
                var s = score(boxFor(l, b, w, h, viewportH), rects);
                var drift = Math.abs(l - baseLeft) + Math.abs(b - baseBottom);
                if (best === null || s < best.score ||
                    (s === best.score && drift < best.drift)) {
                    best = { score: s, drift: drift, left: l, bottom: b };
                }
                if (s === 0 && drift === 0) { bi = bottoms.length; break; }  // authored spot is clear
            }
        }
        if (!best) return;

        panel.style.left = best.left + 'px';
        panel.style.right = 'auto';
        panel.style.bottom = best.bottom + 'px';
    }

    window.potatoFloatingPanel = {
        place: place,
        // Back-compat alias for the widgets' original call site.
        avoidNav: place
    };
})();
