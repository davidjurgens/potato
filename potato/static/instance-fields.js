/**
 * The current item's own fields, for widgets configured with `source_field`.
 *
 * The server puts the item's record on every annotation page twice: as
 * `[data-instance-json]`, the full record that structured schemas already read,
 * and as `<script id="instance_data">`, a scalar-only copy. Both are emitted
 * whether or not the config declares an `instance_display` block.
 *
 * The media widgets never looked at either. Their lookup chains only consulted
 * `[data-field-key=...]` and `.instance-display-container[data-instance-fields]`,
 * both of which only `instance_display` emits. So `source_field` -- documented
 * as the way to point a widget at a field other than `text_key` -- did nothing
 * on its own, and the widget reported no media over an item that had media.
 *
 * `[data-instance-json]` is preferred because it is the richer record and the
 * one `pc-viewer.js` and the structured schemas already agree on; the scalar
 * copy is the fallback for any page that carries only that.
 *
 * Read fresh on every call rather than cached: navigating to the next instance
 * replaces both blocks, and a widget re-initialising against a stale copy would
 * load the previous item's media, which is worse than loading none.
 */
(function () {
    'use strict';

    function parse(raw, source) {
        if (!raw) {
            return null;
        }
        try {
            var parsed = JSON.parse(raw);
            return (parsed && typeof parsed === 'object') ? parsed : null;
        } catch (e) {
            console.warn('[InstanceFields] ' + source + ' is not valid JSON:', e);
            return null;
        }
    }

    /** The whole record, or {} when neither block is present or parseable. */
    function instanceFields() {
        var record = document.querySelector('[data-instance-json]');
        var fields = record
            ? parse(record.getAttribute('data-instance-json'), '[data-instance-json]')
            : null;
        if (fields && Object.keys(fields).length) {
            return fields;
        }
        var block = document.getElementById('instance_data');
        return (block && parse(block.textContent, '#instance_data')) || fields || {};
    }

    /**
     * The value of one field as a URL string, or null.
     *
     * Only non-empty strings come back. A number or a boolean under the
     * configured key is not a media URL, and returning one would send the
     * widget off to load "3" instead of falling through to the next step in
     * its chain.
     */
    function instanceField(key) {
        if (!key) {
            return null;
        }
        var value = instanceFields()[key];
        if (typeof value !== 'string') {
            return null;
        }
        value = value.trim();
        return value ? value : null;
    }

    window.potatoInstanceFields = instanceFields;
    window.potatoInstanceField = instanceField;
})();
