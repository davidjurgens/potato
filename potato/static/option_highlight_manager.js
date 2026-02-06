/**
 * Option Highlight Manager
 *
 * Manages LLM-based option highlighting for discrete annotation tasks.
 * Dims less-likely options while keeping top-k most likely options at full opacity.
 */

class OptionHighlightManager {
    constructor() {
        this.config = null;
        this.cache = new Map();  // Client-side cache: annotationId -> highlights
        this.loadingStates = new Set();  // Track loading states per annotation
        this.initialized = false;
    }

    /**
     * Initialize the manager with configuration from the server.
     */
    async initialize() {
        if (this.initialized) {
            return;
        }

        try {
            const response = await fetch('/api/option_highlights/config');
            if (!response.ok) {
                console.warn('[OptionHighlight] Failed to load config:', response.status);
                return;
            }

            this.config = await response.json();
            console.log('[OptionHighlight] Config loaded:', this.config);

            if (!this.config.enabled) {
                console.log('[OptionHighlight] Feature disabled');
                return;
            }

            this.initialized = true;

            // Apply highlights on page load if auto_apply is enabled
            if (this.config.auto_apply) {
                // Wait for DOM to be ready
                if (document.readyState === 'loading') {
                    document.addEventListener('DOMContentLoaded', () => this.applyAllHighlights());
                } else {
                    // Small delay to ensure annotation forms are rendered
                    setTimeout(() => this.applyAllHighlights(), 100);
                }
            }

            // Trigger prefetch for upcoming items
            this.triggerPrefetch();

        } catch (error) {
            console.error('[OptionHighlight] Error initializing:', error);
        }
    }

    /**
     * Check if a schema should have option highlighting applied.
     * @param {string} schemaName - The annotation schema name
     * @returns {boolean}
     */
    shouldApplyToSchema(schemaName) {
        if (!this.config || !this.config.enabled) {
            return false;
        }

        // If schemas filter is not set, apply to all discrete schemas
        if (this.config.schemas === null || this.config.schemas === undefined) {
            return true;
        }

        return this.config.schemas.includes(schemaName);
    }

    /**
     * Apply highlights to all annotation forms on the page.
     */
    async applyAllHighlights() {
        if (!this.config || !this.config.enabled) {
            return;
        }

        const forms = document.querySelectorAll('.annotation-form');
        console.log('[OptionHighlight] Applying to', forms.length, 'forms');

        for (const form of forms) {
            const annotationId = form.getAttribute('data-annotation-id');
            const schemaName = form.id || form.dataset.schemaName || '';
            const annotationType = form.dataset.annotationType || '';

            // Only apply to discrete option types
            const discreteTypes = ['radio', 'multiselect', 'likert', 'select'];
            if (!discreteTypes.includes(annotationType)) {
                continue;
            }

            if (this.shouldApplyToSchema(schemaName)) {
                await this.applyHighlightsToForm(form, annotationId);
            }
        }
    }

    /**
     * Apply highlights to a specific annotation form.
     * @param {HTMLElement} form - The annotation form element
     * @param {string|number} annotationId - The annotation ID
     */
    async applyHighlightsToForm(form, annotationId) {
        // Skip if already loading
        if (this.loadingStates.has(annotationId)) {
            return;
        }

        this.loadingStates.add(annotationId);

        try {
            // Check cache first
            let highlights = this.cache.get(annotationId);

            if (!highlights) {
                // Fetch from server
                highlights = await this.fetchHighlights(annotationId);
                if (highlights && !highlights.error) {
                    this.cache.set(annotationId, highlights);
                }
            }

            if (!highlights || highlights.error) {
                console.warn('[OptionHighlight] No highlights for annotation', annotationId, highlights?.error);
                return;
            }

            // Apply visual highlighting
            this.applyVisualHighlights(form, highlights);

        } catch (error) {
            console.error('[OptionHighlight] Error applying highlights:', error);
        } finally {
            this.loadingStates.delete(annotationId);
        }
    }

    /**
     * Fetch highlights from the server API.
     * @param {string|number} annotationId - The annotation ID
     * @returns {Promise<Object>} Highlight data
     */
    async fetchHighlights(annotationId) {
        try {
            const response = await fetch(`/api/option_highlights/${annotationId}`);
            if (!response.ok) {
                return { error: `HTTP ${response.status}` };
            }
            return await response.json();
        } catch (error) {
            return { error: error.message };
        }
    }

    /**
     * Apply visual highlighting to form options.
     * @param {HTMLElement} form - The annotation form element
     * @param {Object} highlights - The highlight data from the server
     */
    applyVisualHighlights(form, highlights) {
        const highlightedOptions = highlights.highlighted || [];
        const dimOpacity = this.config?.dim_opacity || 0.4;

        console.log('[OptionHighlight] Applying visual highlights:', highlightedOptions);

        // Find all option elements in the form
        const optionContainers = form.querySelectorAll(
            '.shadcn-radio-option, .shadcn-checkbox-option, .shadcn-span-option, ' +
            '.option-item, .likert-option, .form-check'
        );

        // Add AI highlighting active indicator to the form
        form.classList.add('ai-highlighting-active');

        optionContainers.forEach(container => {
            // Get the input element
            const input = container.querySelector('input[type="radio"], input[type="checkbox"]');
            if (!input) return;

            const value = input.value;
            const labelElement = container.querySelector('label') || container;
            const labelText = labelElement.textContent?.trim() || '';

            // Check if this option should be highlighted
            const isHighlighted = highlightedOptions.some(opt => {
                const optLower = String(opt).toLowerCase();
                const valueLower = String(value).toLowerCase();
                const labelLower = labelText.toLowerCase();
                return optLower === valueLower ||
                       labelLower.includes(optLower) ||
                       optLower.includes(valueLower);
            });

            // Apply appropriate classes
            if (isHighlighted) {
                container.classList.add('option-highlighted');
                container.classList.remove('option-dimmed');
            } else {
                container.classList.add('option-dimmed');
                container.classList.remove('option-highlighted');
                container.style.setProperty('--dim-opacity', dimOpacity);
            }
        });
    }

    /**
     * Clear all highlights from the page.
     */
    clearAllHighlights() {
        // Remove classes from all option containers
        document.querySelectorAll('.option-highlighted, .option-dimmed').forEach(el => {
            el.classList.remove('option-highlighted', 'option-dimmed');
            el.style.removeProperty('--dim-opacity');
        });

        // Remove active indicator from forms
        document.querySelectorAll('.ai-highlighting-active').forEach(el => {
            el.classList.remove('ai-highlighting-active');
        });

        // Clear cache
        this.cache.clear();
    }

    /**
     * Clear highlights for a specific annotation.
     * @param {string|number} annotationId - The annotation ID
     */
    clearHighlights(annotationId) {
        const form = document.querySelector(`.annotation-form[data-annotation-id="${annotationId}"]`);
        if (!form) return;

        form.querySelectorAll('.option-highlighted, .option-dimmed').forEach(el => {
            el.classList.remove('option-highlighted', 'option-dimmed');
            el.style.removeProperty('--dim-opacity');
        });

        form.querySelectorAll('.option-highlight-indicator').forEach(el => {
            el.remove();
        });

        form.classList.remove('ai-highlighting-active');
        this.cache.delete(annotationId);
    }

    /**
     * Trigger server-side prefetching of upcoming items.
     */
    async triggerPrefetch() {
        if (!this.config || !this.config.enabled) {
            return;
        }

        try {
            await fetch('/api/option_highlights/prefetch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ count: this.config.prefetch_count })
            });
            console.log('[OptionHighlight] Prefetch triggered');
        } catch (error) {
            console.warn('[OptionHighlight] Prefetch trigger failed:', error);
        }
    }

    /**
     * Refresh highlights (e.g., after navigation).
     */
    async refresh() {
        if (!this.config || !this.config.enabled) {
            return;
        }

        // Clear existing highlights
        this.clearAllHighlights();

        // Re-apply if auto_apply is enabled
        if (this.config.auto_apply) {
            await this.applyAllHighlights();
        }

        // Trigger prefetch for next items
        this.triggerPrefetch();
    }

    /**
     * Toggle highlighting on/off for the current page.
     */
    toggle() {
        if (!this.config) {
            return;
        }

        const hasHighlights = document.querySelector('.option-highlighted, .option-dimmed');

        if (hasHighlights) {
            this.clearAllHighlights();
        } else {
            this.applyAllHighlights();
        }
    }
}

// Create global instance
window.optionHighlightManager = new OptionHighlightManager();

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        window.optionHighlightManager.initialize();
    });
} else {
    window.optionHighlightManager.initialize();
}
