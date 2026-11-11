"""
Live-session applier for widgets that rebuild themselves from a hidden input.

Several trace-review schemes (tool_call_review, handoff_review, gui_trajectory
and the rest) keep their answer in one hidden ``annotation-input`` and draw
everything from it in a ``build()`` function inside their inline script. In a
live collaborative session ``collab.js`` writes a teammate's answer into that
input and then asks ``window.potatoCollabWidgets[<annotation_type>].apply(ctx)``
to put it on screen. Each such scheme registers its own rebuild function here,
keyed by scheme name, and one shared ``apply`` calls it.

The rebuild function must be idempotent: read the hidden input, replace the
widget's state with it (empty input = empty answer), redraw, bind listeners only
on elements it just created, and never save.
"""

import json


def collab_rebuild_js(annotation_type: str, rebuild_fn: str = "build") -> str:
    """JS, for inside a scheme's IIFE, registering ``rebuild_fn`` for ``SCHEMA``.

    The surrounding script must define ``SCHEMA`` (the scheme name) and the
    function named by ``rebuild_fn``. Braces are single: callers insert the
    result into an f-string as a value, so it is not re-formatted.
    """
    type_js = json.dumps(annotation_type)
    return """
        // Live sessions: collab.js writes a teammate's answer into the hidden
        // input, then calls this to redraw the scheme from it (no save).
        (function (w) {
            w.potatoCollabRebuild = w.potatoCollabRebuild || {};
            w.potatoCollabRebuild[SCHEMA] = %(fn)s;
            w.potatoCollabWidgets = w.potatoCollabWidgets || {};
            if (!w.potatoCollabRebuildApply) {
                w.potatoCollabRebuildApply = function (ctx) {
                    var rebuild = (w.potatoCollabRebuild || {})[ctx && ctx.schema];
                    if (typeof rebuild !== 'function') return false;
                    var form = (ctx && ctx.form) || document.getElementById(ctx.schema);
                    // Keep keyboard focus (and the caret) on the same control.
                    var a = document.activeElement, spot = null;
                    if (a && form && a !== form && form.contains(a)) {
                        spot = {tag: a.tagName, cls: a.className, id: a.id, data: {},
                                s: a.selectionStart, e: a.selectionEnd};
                        Array.prototype.forEach.call(a.attributes, function (at) {
                            if (at.name.indexOf('data-') === 0) spot.data[at.name] = at.value;
                        });
                    }
                    rebuild();
                    if (spot && form) {
                        var match = Array.prototype.filter.call(
                            form.getElementsByTagName(spot.tag), function (el) {
                                if (el.className !== spot.cls || el.id !== spot.id) return false;
                                return Object.keys(spot.data).every(function (k) {
                                    return el.getAttribute(k) === spot.data[k];
                                });
                            })[0];
                        if (match && match !== document.activeElement) {
                            try {
                                match.focus();
                                if (typeof spot.s === 'number' && match.setSelectionRange) {
                                    match.setSelectionRange(spot.s, spot.e);
                                }
                            } catch (err) { /* not focusable or no caret */ }
                        }
                    }
                    return true;
                };
            }
            w.potatoCollabWidgets[%(type)s] = {
                apply: function (ctx) { return w.potatoCollabRebuildApply(ctx); }
            };
        })(window);
""" % {"fn": rebuild_fn, "type": type_js}
