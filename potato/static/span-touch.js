/**
 * Span highlighting by touch.
 *
 * SpanManager creates a span on `mouseup` over the text (span-core.js
 * setupEventListeners). A phone selects text with a long press and a pair of
 * drag handles, and neither fires `mouseup` reliably -- so on a phone there
 * was no way to highlight a span at all.
 *
 * On a touch device this watches the selection instead. Once it has settled
 * inside a span-target text field, a "Highlight" button appears at the bottom
 * of the screen; tapping it hands the selection to the same
 * SpanManager.handleTextSelection the desktop path calls. A button, not
 * automatic creation on `selectionchange`: a phone selection passes through
 * several intermediate states while the handles are dragged, and creating a
 * span at each would litter the text.
 *
 * Desktop (fine pointer) is untouched: this script returns immediately.
 */
(function () {
    "use strict";

    function isTouch() {
        try {
            return window.matchMedia("(hover: none) and (pointer: coarse)").matches;
        } catch (e) {
            return false;
        }
    }

    if (!isTouch()) return;

    var TARGETS = '#instance-text, #text-content, [id^="text-content-"], ' +
        '.display-field[data-span-target="true"]';
    var SETTLE_MS = 350;

    var button = null;
    var savedRange = null;
    var timer = null;

    function spanTaskOnPage() {
        return !!document.querySelector(".annotation-form.span");
    }

    function selectionInTarget(selection) {
        if (!selection || !selection.rangeCount || selection.isCollapsed) return null;
        var range = selection.getRangeAt(0);
        var node = range.commonAncestorContainer;
        var el = node.nodeType === Node.TEXT_NODE ? node.parentElement : node;
        if (!el || !el.closest(TARGETS)) return null;
        if (!selection.toString().trim()) return null;
        return range;
    }

    function armedLabel(selection) {
        var mgr = window.spanManager;
        if (!mgr || typeof mgr.getSelectedLabel !== "function") return null;
        try {
            var field = typeof mgr.fieldOfSelection === "function"
                ? mgr.fieldOfSelection(selection) : "";
            return mgr.getSelectedLabel(field) || null;
        } catch (e) {
            return null;
        }
    }

    function ensureButton() {
        if (button) return button;
        button = document.createElement("button");
        button.type = "button";
        button.id = "span-touch-highlight";
        button.className = "span-touch-highlight";
        button.hidden = true;
        // Keep focus (and, where the browser allows, the selection) off the
        // button. Not touchstart: preventDefault there cancels the click the
        // tap would produce. The selection is restored from savedRange in
        // commit() in any case.
        button.addEventListener("pointerdown", function (e) { e.preventDefault(); });
        button.addEventListener("click", commit);
        document.body.appendChild(button);
        return button;
    }

    function hide() {
        if (button) button.hidden = true;
        savedRange = null;
    }

    function show(label) {
        var b = ensureButton();
        if (label) {
            b.textContent = "Highlight as “" + label + "”";
            b.disabled = false;
        } else {
            b.textContent = "Choose a label, then highlight";
            b.disabled = true;
        }
        b.hidden = false;
    }

    function update() {
        var selection = window.getSelection();
        var range = selectionInTarget(selection);
        if (!range) {
            hide();
            return;
        }
        savedRange = range.cloneRange();
        show(armedLabel(selection));
    }

    function commit() {
        var mgr = window.spanManager;
        if (!savedRange || !mgr || typeof mgr.handleTextSelection !== "function") {
            hide();
            return;
        }
        // Tapping may have collapsed the live selection; restore the one the
        // button was offered for.
        var selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(savedRange);
        try {
            mgr.handleTextSelection(null);
        } finally {
            try { selection.removeAllRanges(); } catch (e) { /* ignore */ }
            hide();
        }
    }

    function init() {
        if (!spanTaskOnPage()) return;
        document.addEventListener("selectionchange", function () {
            clearTimeout(timer);
            timer = setTimeout(update, SETTLE_MS);
        });
        // A label chosen after the selection was made re-arms the button.
        document.addEventListener("change", function (e) {
            if (e.target && e.target.closest && e.target.closest(".annotation-form.span")) {
                if (savedRange && button && !button.hidden) {
                    var selection = window.getSelection();
                    show(armedLabel(selection) || null);
                }
            }
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
