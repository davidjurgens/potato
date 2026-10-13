/**
 * Instance Display Manager
 *
 * Handles client-side functionality for the instance display system.
 * This includes image zoom, collapsible sections, and coordination
 * with annotation schemas that reference display fields.
 */

(function() {
    'use strict';

    /**
     * InstanceDisplayManager handles all display field interactions
     */
    class InstanceDisplayManager {
        constructor() {
            this.displayContainer = document.querySelector('.instance-display-container');
            this.displayFields = {};
            this.spanTargets = [];

            if (this.displayContainer) {
                this.init();
            }
        }

        /**
         * Initialize the display manager
         */
        init() {
            this.collectDisplayFields();
            this.initImageZoom();
            this.initCollapsibleSections();
            this.initSpanTargets();
            this.initPerTurnRatings();
            this.initResizableExpand();
            this.initMediaFailures();

            console.log('[InstanceDisplay] Initialized with', Object.keys(this.displayFields).length, 'fields');
        }

        /**
         * Say so when a video display cannot load its file.
         *
         * A missing or unplayable file left an empty black player with no
         * message (the video example's clip answered 404 and the item read
         * as blank). The failure is reported on the <source>, which does not
         * bubble, and can happen before this runs, so check the state too.
         */
        initMediaFailures() {
            this.displayContainer.querySelectorAll('video.display-video').forEach(video => {
                const report = () => this.reportMediaFailure(video);
                const sources = video.querySelectorAll('source');
                if (sources.length) {
                    sources[sources.length - 1].addEventListener('error', report);
                }
                video.addEventListener('error', report);
                if (video.error || video.networkState === HTMLMediaElement.NETWORK_NO_SOURCE) {
                    report();
                }
            });
        }

        async reportMediaFailure(video) {
            if (video.dataset.loadFailed) return;
            video.dataset.loadFailed = 'true';
            const url = video.getAttribute('data-source-url') || '';
            let outcome = 'unknown';
            if (url && typeof fetch === 'function') {
                try {
                    const response = await fetch(url, {headers: {Range: 'bytes=0-0'}});
                    outcome = response.ok
                        ? 'ok'
                        : `HTTP ${response.status}${response.statusText ? ' ' + response.statusText : ''}`;
                    try { if (response.body) response.body.cancel(); } catch (e) { /* ignore */ }
                } catch (e) {
                    outcome = 'unreachable';
                }
            }
            let message = 'The video file could not be loaded.';
            if (outcome.startsWith('HTTP')) {
                message = `The video file could not be loaded: the server answered ${outcome}.`;
            } else if (outcome === 'ok') {
                message = 'The video file was downloaded, but this browser cannot play its format.';
            } else if (outcome === 'unreachable') {
                message = 'The video file could not be reached from this browser.';
            }
            const note = document.createElement('div');
            note.className = 'video-error';
            note.setAttribute('role', 'alert');
            note.textContent = message;
            video.hidden = true;
            video.insertAdjacentElement('afterend', note);
        }

        /**
         * Collect all display fields from the DOM
         */
        collectDisplayFields() {
            const fields = this.displayContainer.querySelectorAll('.display-field');
            fields.forEach(field => {
                const key = field.dataset.fieldKey;
                const type = field.dataset.fieldType;
                if (key) {
                    this.displayFields[key] = {
                        element: field,
                        type: type,
                        isSpanTarget: field.dataset.spanTarget === 'true'
                    };

                    if (field.dataset.spanTarget === 'true') {
                        this.spanTargets.push(key);
                    }
                }
            });
        }

        /**
         * Initialize image zoom functionality
         */
        initImageZoom() {
            const zoomContainers = document.querySelectorAll('.image-zoom-container');
            zoomContainers.forEach(container => {
                const img = container.querySelector('img');
                const zoomIn = container.querySelector('.zoom-in');
                const zoomOut = container.querySelector('.zoom-out');
                const zoomReset = container.querySelector('.zoom-reset');

                if (!img) return;

                let scale = 1;
                const minScale = 0.5;
                const maxScale = 5;
                const scaleStep = 1.25;

                const updateScale = (newScale) => {
                    scale = Math.max(minScale, Math.min(maxScale, newScale));
                    img.style.transform = `scale(${scale})`;
                    img.style.transformOrigin = 'center center';
                };

                if (zoomIn) {
                    zoomIn.addEventListener('click', (e) => {
                        e.preventDefault();
                        updateScale(scale * scaleStep);
                    });
                }

                if (zoomOut) {
                    zoomOut.addEventListener('click', (e) => {
                        e.preventDefault();
                        updateScale(scale / scaleStep);
                    });
                }

                if (zoomReset) {
                    zoomReset.addEventListener('click', (e) => {
                        e.preventDefault();
                        updateScale(1);
                    });
                }

                // Also support scroll wheel zoom when hovering
                container.addEventListener('wheel', (e) => {
                    if (e.ctrlKey || e.metaKey) {
                        e.preventDefault();
                        const delta = e.deltaY > 0 ? 1 / scaleStep : scaleStep;
                        updateScale(scale * delta);
                    }
                });
            });
        }

        /**
         * Initialize collapsible sections with persistent state
         */
        initCollapsibleSections() {
            const collapsibles = document.querySelectorAll('.collapsible-text-container');
            collapsibles.forEach(container => {
                const toggle = container.querySelector('.collapsible-toggle');
                const content = container.querySelector('.collapse');

                if (!toggle || !content) return;

                // Get the field key from the parent display-field or collapse ID
                const displayField = container.closest('.display-field');
                const fieldKey = displayField ? displayField.dataset.fieldKey : content.id;
                const storageKey = `potato_collapse_${fieldKey}`;

                // Restore state from localStorage
                const savedState = localStorage.getItem(storageKey);
                if (savedState !== null) {
                    const shouldBeExpanded = savedState === 'expanded';
                    const isCurrentlyExpanded = content.classList.contains('show');

                    if (shouldBeExpanded !== isCurrentlyExpanded) {
                        // Need to toggle the state
                        if (shouldBeExpanded) {
                            content.classList.add('show');
                            toggle.setAttribute('aria-expanded', 'true');
                        } else {
                            content.classList.remove('show');
                            toggle.setAttribute('aria-expanded', 'false');
                        }
                    }
                }

                // Save state when toggled
                content.addEventListener('shown.bs.collapse', () => {
                    toggle.setAttribute('aria-expanded', 'true');
                    localStorage.setItem(storageKey, 'expanded');
                });

                content.addEventListener('hidden.bs.collapse', () => {
                    toggle.setAttribute('aria-expanded', 'false');
                    localStorage.setItem(storageKey, 'collapsed');
                });
            });
        }

        /**
         * Initialize span target fields
         */
        initSpanTargets() {
            // Span targets need special handling for the span annotation system
            // This sets up the necessary attributes and event listeners

            this.spanTargets.forEach(key => {
                const field = this.displayFields[key];
                if (!field) return;

                const textContent = field.element.querySelector('.text-content');
                if (textContent) {
                    // Ensure the text content has the necessary attributes
                    // for the span annotation system to work
                    if (!textContent.id) {
                        textContent.id = `text-content-${key}`;
                    }
                }
            });
        }

        /**
         * Give each height-capped display field a "Show all" control.
         *
         * A field wrapper (.display-field-resizable) is capped at 80vh, or at
         * the config's max_height, and scrolls inside that. A long agent trace
         * then reads as cut off, and resize: vertical cannot drag past the cap.
         * The control appears only while the content actually overflows, and
         * lifts the cap until it is pressed again.
         */
        initResizableExpand() {
            const wrappers = this.displayContainer.querySelectorAll('.display-field-resizable');
            wrappers.forEach((wrapper, i) => {
                if (!wrapper.id) wrapper.id = `display-field-resizable-${i}`;
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'display-field-expand';
                button.setAttribute('aria-controls', wrapper.id);
                button.setAttribute('aria-expanded', 'false');
                button.textContent = 'Show all';
                button.hidden = true;
                wrapper.insertAdjacentElement('afterend', button);

                const update = () => {
                    const expanded = wrapper.classList.contains('is-expanded');
                    const overflowing = wrapper.scrollHeight > wrapper.clientHeight + 4;
                    button.hidden = !expanded && !overflowing;
                };

                button.addEventListener('click', () => {
                    const expanded = wrapper.classList.toggle('is-expanded');
                    if (expanded) {
                        // A height dragged with the resize handle would
                        // otherwise keep the pane short.
                        wrapper.style.height = '';
                    }
                    button.setAttribute('aria-expanded', String(expanded));
                    button.textContent = expanded ? 'Show less' : 'Show all';
                    update();
                });

                update();
                if (typeof ResizeObserver === 'function') {
                    const observer = new ResizeObserver(update);
                    observer.observe(wrapper);
                    if (wrapper.firstElementChild) observer.observe(wrapper.firstElementChild);
                }
                window.addEventListener('load', update, { once: true });
            });
        }

        /**
         * Initialize per-turn rating widgets in dialogue displays.
         * Supports both single-schema and multi-schema (multi-dimension) per-turn ratings.
         * Each schema stores its values in its own hidden input.
         */
        initPerTurnRatings() {
            const containers = document.querySelectorAll('.has-per-turn-ratings');
            containers.forEach(container => {
                const fieldKey = container.dataset.fieldKey;

                // Collect all hidden inputs keyed by schema name
                const hiddenInputs = {};
                container.querySelectorAll('.per-turn-hidden').forEach(input => {
                    const schemaName = input.dataset.schemaName;
                    if (schemaName) {
                        hiddenInputs[schemaName] = input;
                    }
                });

                // Fall back to single hidden input (legacy format)
                const singleHiddenInput = container.querySelector('.annotation-data-input:not(.per-turn-hidden)');

                // Rating values keyed by schema: {schemaName: {turnIndex: value}}
                const ratingValuesBySchema = {};

                // Seed from server-restored hidden values BEFORE wiring events
                // (persistence contract: the server sets value + data-server-set
                // via BeautifulSoup; without this seed, navigate-away-and-back
                // loses the visual selection state).
                const seedFromInput = (schemaName, input) => {
                    if (!input || input.getAttribute('data-server-set') !== 'true') return;
                    const raw = input.getAttribute('value') || input.value;
                    if (!raw) return;
                    try {
                        const parsed = JSON.parse(raw);
                        if (parsed && typeof parsed === 'object') {
                            ratingValuesBySchema[schemaName] = parsed;
                        }
                    } catch (e) {
                        console.warn('[InstanceDisplay] Could not parse per-turn ratings for', schemaName, e);
                    }
                };
                Object.entries(hiddenInputs).forEach(([schemaName, input]) => seedFromInput(schemaName, input));
                if (singleHiddenInput) seedFromInput('', singleHiddenInput);

                // Paint one turn + schema: fill up to the chosen value, mark
                // the chosen value as the checked radio, and keep exactly one
                // value in the tab order (the checked one, else the first) so
                // Tab enters each rating once and arrows move within it.
                const paintTurn = (schema, turn) => {
                    const chosen = (ratingValuesBySchema[schema] || {})[turn];
                    const selector = `.ptr-value[data-turn="${turn}"][data-schema="${schema}"]`;
                    const values = [...container.querySelectorAll(selector)];
                    values.forEach((v, i) => {
                        const vVal = parseInt(v.dataset.value, 10);
                        v.classList.toggle('ptr-selected', !!chosen && vVal <= chosen);
                        v.setAttribute('aria-checked', String(!!chosen && vVal === chosen));
                        const tabStop = chosen ? vVal === chosen : i === 0;
                        v.setAttribute('tabindex', tabStop ? '0' : '-1');
                    });
                };

                // Paint restored visual state
                Object.entries(ratingValuesBySchema).forEach(([schema, schemaValues]) => {
                    Object.keys(schemaValues).forEach((turn) => paintTurn(schema, turn));
                });

                // Choose a value. `toggle` is the mouse/Space behaviour --
                // choosing the current value again clears it; arrow keys always
                // set, as radio groups do.
                const choose = (el, toggle) => {
                    const turn = el.dataset.turn;
                    const value = parseInt(el.dataset.value, 10);
                    const schema = el.dataset.schema || '';

                    if (!ratingValuesBySchema[schema]) {
                        ratingValuesBySchema[schema] = {};
                    }
                    const schemaValues = ratingValuesBySchema[schema];

                    if (toggle && schemaValues[turn] === value) {
                        delete schemaValues[turn];
                    } else {
                        schemaValues[turn] = value;
                    }

                    paintTurn(schema, turn);

                    // Update the corresponding hidden input
                    if (schema && hiddenInputs[schema]) {
                        hiddenInputs[schema].value = JSON.stringify(schemaValues);
                    } else if (singleHiddenInput) {
                        singleHiddenInput.value = JSON.stringify(schemaValues);
                    }
                };

                container.querySelectorAll('.ptr-value').forEach(el => {
                    el.addEventListener('click', (e) => {
                        e.preventDefault();
                        choose(el, true);
                    });

                    el.addEventListener('keydown', (e) => {
                        const group = [...el.parentElement.querySelectorAll('.ptr-value')];
                        const i = group.indexOf(el);
                        let target = null;
                        if (e.key === 'ArrowRight' || e.key === 'ArrowUp') {
                            target = group[(i + 1) % group.length];
                        } else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') {
                            target = group[(i - 1 + group.length) % group.length];
                        } else if (e.key === 'Home') {
                            target = group[0];
                        } else if (e.key === 'End') {
                            target = group[group.length - 1];
                        } else if (e.key === ' ' || e.key === 'Enter') {
                            // Stop the page-level hotkeys (Enter = Next) from
                            // also acting on this key.
                            e.preventDefault();
                            e.stopPropagation();
                            choose(el, true);
                            return;
                        } else {
                            return;
                        }
                        e.preventDefault();
                        e.stopPropagation();
                        choose(target, false);
                        target.focus();
                    });
                });
            });
        }

        /**
         * Get a display field by key
         * @param {string} key - The field key
         * @returns {Object|null} The field info or null
         */
        getField(key) {
            return this.displayFields[key] || null;
        }

        /**
         * Get the source URL for a field (for images/videos/audio)
         * @param {string} key - The field key
         * @returns {string|null} The source URL or null
         */
        getSourceUrl(key) {
            const field = this.getField(key);
            if (!field) return null;

            const sourceElement = field.element.querySelector('[data-source-url]');
            return sourceElement ? sourceElement.dataset.sourceUrl : null;
        }

        /**
         * Get all span target field keys
         * @returns {string[]} Array of field keys that are span targets
         */
        getSpanTargets() {
            return [...this.spanTargets];
        }

        /**
         * Check if multiple span targets exist (multi-span mode)
         * @returns {boolean}
         */
        isMultiSpanMode() {
            return this.spanTargets.length > 1;
        }

        /**
         * Get the primary text content element for span annotation
         * Falls back to legacy #text-content if instance_display not configured
         * @returns {HTMLElement|null}
         */
        getPrimaryTextElement() {
            // First check for instance_display span targets
            if (this.spanTargets.length > 0) {
                const key = this.spanTargets[0];
                const field = this.displayFields[key];
                if (field) {
                    return field.element.querySelector('.text-content');
                }
            }

            // Fall back to legacy element
            return document.getElementById('text-content');
        }
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            window.instanceDisplayManager = new InstanceDisplayManager();
        });
    } else {
        window.instanceDisplayManager = new InstanceDisplayManager();
    }

    // Export for module systems
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = InstanceDisplayManager;
    }

})();
