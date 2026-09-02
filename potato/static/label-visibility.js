/**
 * Label visibility — shared across image, video, and text-span annotation.
 *
 * Dense annotation gets unreadable fast: twenty overlapping boxes, a timeline of
 * stacked segments, a paragraph highlighted in eight colours. Every modality
 * needs the same affordance — "show me only the class I am working on" — so this
 * owns the state and the control, and each modality supplies only the one
 * function that knows how to hide its own artifacts.
 *
 * Splitting it this way matters because the state is the part worth sharing:
 * it persists per project + schema, so hiding a class stays hidden as the
 * annotator moves through items. (V7's equivalent is documented as a per-file
 * control; making it stick across the project is the point.)
 *
 * Usage:
 *     const vis = new LabelVisibilityManager({
 *         schemaName: 'objects',
 *         projectKey: window.POTATO_CONFIG.annotation_task_name,
 *         container: containerEl,
 *         onChange: (hidden) => manager.applyLabelVisibility(hidden),
 *     });
 *
 * The container is expected to hold `.label-btn[data-label]` elements, which
 * image and video already render identically; span supplies its own list.
 */

class LabelVisibilityManager {
    /**
     * @param {Object} opts
     * @param {string} opts.schemaName - Schema this applies to
     * @param {string} opts.projectKey - Stable project identifier
     * @param {HTMLElement} opts.container - Element holding the label buttons
     * @param {Function} opts.onChange - Called with a Set of hidden label names
     * @param {string} [opts.buttonSelector] - Defaults to '.label-btn'
     */
    constructor(opts) {
        this.schemaName = opts.schemaName;
        this.projectKey = opts.projectKey || 'default';
        this.container = opts.container;
        this.onChange = opts.onChange || function () {};
        this.buttonSelector = opts.buttonSelector || '.label-btn';

        this.hidden = this._load();

        this._decorateButtons();
        this._apply();
    }

    get storageKey() {
        return `potato.labelVisibility.${this.projectKey}.${this.schemaName}`;
    }

    /** Label names currently hidden. */
    hiddenLabels() {
        return new Set(this.hidden);
    }

    isVisible(label) {
        return !this.hidden.has(label);
    }

    setVisible(label, visible) {
        if (visible) this.hidden.delete(label);
        else this.hidden.add(label);
        this._persist();
        this._apply();
    }

    toggle(label) {
        this.setVisible(label, !this.isVisible(label));
    }

    showAll() {
        if (!this.hidden.size) return;
        this.hidden.clear();
        this._persist();
        this._apply();
    }

    /**
     * Show only `label`, hiding every other class.
     *
     * Pressing it again on the same label restores everything, so one key both
     * isolates and un-isolates and the annotator never has to remember which
     * state they are in.
     */
    solo(label) {
        const others = this._allLabels().filter(l => l !== label);
        const alreadySolo = this.hidden.size === others.length &&
            others.every(l => this.hidden.has(l));

        if (alreadySolo) {
            // Restore what was hidden BEFORE soloing rather than showing
            // everything. Un-soloing should undo the solo, not also discard
            // classes the annotator had deliberately hidden earlier.
            this.hidden = new Set(this._preSolo || []);
            this._preSolo = null;
        } else {
            this._preSolo = new Set(this.hidden);
            this.hidden = new Set(others);
        }
        this._persist();
        this._apply();
    }

    _allLabels() {
        if (!this.container) return [];
        return [...this.container.querySelectorAll(this.buttonSelector)]
            .map(b => b.dataset.label)
            .filter(Boolean);
    }

    _load() {
        try {
            const raw = localStorage.getItem(this.storageKey);
            if (raw) return new Set(JSON.parse(raw));
        } catch (e) {
            // Private browsing, or a corrupt value. Start visible; a broken
            // preference must never make annotations look absent.
        }
        return new Set();
    }

    _persist() {
        try {
            localStorage.setItem(this.storageKey, JSON.stringify([...this.hidden]));
        } catch (e) {
            // Best effort: the feature still works for this session.
        }
    }

    /**
     * Add an eye toggle to each label button.
     *
     * The toggle is a separate button rather than a click-target on the label
     * itself, because selecting a label to draw with and hiding that label are
     * different intentions and conflating them would make the common action
     * (select) risky.
     */
    _decorateButtons() {
        if (!this.container) return;

        this.container.querySelectorAll(this.buttonSelector).forEach(btn => {
            const label = btn.dataset.label;
            if (!label || btn.querySelector('.label-visibility-toggle')) return;

            const eye = document.createElement('span');
            eye.className = 'label-visibility-toggle';
            eye.setAttribute('role', 'button');
            eye.setAttribute('tabindex', '0');
            eye.dataset.label = label;

            const activate = (e) => {
                // Do not also arm the label for drawing.
                e.stopPropagation();
                e.preventDefault();
                this.toggle(label);
            };
            eye.addEventListener('click', activate);
            eye.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') activate(e);
            });

            btn.appendChild(eye);
        });
    }

    /** Push state to the DOM and to the modality's renderer. */
    _apply() {
        if (this.container) {
            this.container.querySelectorAll(this.buttonSelector).forEach(btn => {
                const label = btn.dataset.label;
                const visible = this.isVisible(label);
                btn.classList.toggle('label-hidden', !visible);

                const eye = btn.querySelector('.label-visibility-toggle');
                if (eye) {
                    // aria-pressed on the toggle, not the label button, whose
                    // pressed state already means "armed for drawing".
                    eye.setAttribute('aria-pressed', visible ? 'false' : 'true');
                    eye.setAttribute('aria-label',
                        `${visible ? 'Hide' : 'Show'} ${label} annotations`);
                    eye.title = eye.getAttribute('aria-label');
                    eye.textContent = visible ? '\u{1F441}' : '\u{1F6AB}';
                }
            });
        }

        this.onChange(this.hiddenLabels());
    }
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = LabelVisibilityManager;
}
if (typeof window !== 'undefined') {
    window.LabelVisibilityManager = LabelVisibilityManager;
}
