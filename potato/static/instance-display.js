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

            console.log('[InstanceDisplay] Initialized with', Object.keys(this.displayFields).length, 'fields');
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

                // Handle click on rating values
                container.querySelectorAll('.ptr-value').forEach(el => {
                    el.addEventListener('click', (e) => {
                        e.preventDefault();
                        const turn = el.dataset.turn;
                        const value = parseInt(el.dataset.value, 10);
                        const schema = el.dataset.schema || '';

                        // Initialize schema bucket
                        if (!ratingValuesBySchema[schema]) {
                            ratingValuesBySchema[schema] = {};
                        }
                        const schemaValues = ratingValuesBySchema[schema];

                        // Toggle: clicking same value deselects
                        if (schemaValues[turn] === value) {
                            delete schemaValues[turn];
                        } else {
                            schemaValues[turn] = value;
                        }

                        // Update visual state for this turn + schema combination
                        const selector = `.ptr-value[data-turn="${turn}"][data-schema="${schema}"]`;
                        container.querySelectorAll(selector).forEach(v => {
                            const vVal = parseInt(v.dataset.value, 10);
                            if (schemaValues[turn] && vVal <= schemaValues[turn]) {
                                v.classList.add('ptr-selected');
                            } else {
                                v.classList.remove('ptr-selected');
                            }
                        });

                        // Update the corresponding hidden input
                        if (schema && hiddenInputs[schema]) {
                            hiddenInputs[schema].value = JSON.stringify(schemaValues);
                        } else if (singleHiddenInput) {
                            singleHiddenInput.value = JSON.stringify(schemaValues);
                        }

                        console.log('[InstanceDisplay] Per-turn rating:', fieldKey,
                            schema ? `schema=${schema}` : '', 'turn', turn, '=',
                            schemaValues[turn] || 'cleared');
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
