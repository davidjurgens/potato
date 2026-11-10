"""
Which keys a viewer takes from the whole page, measured in the browser.

keybinding_allocator reserves the keys each viewer module lists in
``page_keys`` (and ``label_keys``) so that sequential label shortcuts elsewhere
on the page avoid them. The lists are Python; the handlers are JS. This presses
each printable key with nothing focused and reports the ones some handler
called preventDefault on, so a test can check that every one is listed.
"""

from __future__ import annotations

import importlib

# Space, letters, digits and the punctuation a label key could plausibly use.
# No Enter, Tab or arrows: those move focus or change the item.
PRINTABLE = " abcdefghijklmnopqrstuvwxyz0123456789,.<>[]-=+_;'`"


def keys_taken_page_wide(page, keys: str = PRINTABLE) -> set:
    # Hold each keydown from window capture, where it starts, and read
    # defaultPrevented once it is over: a viewer that also stops propagation
    # (interval_label does) never lets the event reach a later listener.
    page.evaluate("""() => {
        window.__keyDowns = [];
        window.addEventListener('keydown', (e) => window.__keyDowns.push(e), true);
    }""")
    for key in keys:
        # Some keys open or focus something; start every press from the body.
        page.evaluate("() => document.activeElement && document.activeElement.blur()")
        page.keyboard.type(key)
    return set(page.evaluate(
        "() => window.__keyDowns.filter(e => e.defaultPrevented).map(e => e.key.toLowerCase())"))


def keys_reserved_for(scheme: dict) -> set:
    """What the allocator reserves for ``scheme``, as the viewer module lists it."""
    from potato.server_utils.schemas.keybinding_allocator import PAGE_KEY_MODULES
    module = importlib.import_module(
        f"potato.server_utils.schemas.{PAGE_KEY_MODULES[scheme['annotation_type']]}")
    reserved = {k.lower() for k in module.page_keys(scheme)}
    if hasattr(module, "label_keys"):
        reserved |= {k.lower() for k, _ in module.label_keys(scheme)}
    reserved |= {str(lab["key_value"]).lower() for lab in scheme.get("labels") or []
                 if isinstance(lab, dict) and lab.get("key_value") is not None}
    return reserved
