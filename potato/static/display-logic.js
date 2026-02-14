/**
 * Display Logic Manager
 *
 * Handles conditional schema visibility based on user responses.
 * Evaluates display_logic rules and shows/hides annotation schemas accordingly.
 *
 * Usage:
 *   // Initialize on page load
 *   const displayLogicManager = new DisplayLogicManager();
 *   displayLogicManager.initialize();
 *
 *   // Call after any annotation change
 *   displayLogicManager.evaluateAll();
 */

class DisplayLogicManager {
    constructor() {
        // Map of schema name -> display logic configuration
        this.displayLogicRules = new Map();

        // Map of schema name -> container element
        this.schemaContainers = new Map();

        // Map of watched schema -> list of dependent schemas
        this.dependencies = new Map();

        // Current visibility state for each schema with display_logic
        this.visibilityState = new Map();

        // Animation duration in ms
        this.animationDuration = 300;

        // Debug mode
        this.debug = false;
    }

    /**
     * Initialize the display logic manager.
     * Scans the DOM for display_logic configurations and sets up the initial state.
     */
    initialize() {
        this.scanForDisplayLogic();
        this.buildDependencyGraph();

        if (this.debug) {
            console.log('[DisplayLogic] Initialized with', this.displayLogicRules.size, 'rules');
            console.log('[DisplayLogic] Dependencies:', Object.fromEntries(this.dependencies));
        }

        // Evaluate all rules on initial load
        // Use setTimeout to ensure DOM is ready and initial annotations are loaded
        setTimeout(() => this.evaluateAll(), 100);
    }

    /**
     * Scan the DOM for elements with data-display-logic attributes.
     */
    scanForDisplayLogic() {
        const containers = document.querySelectorAll('[data-display-logic-target="true"]');

        containers.forEach(container => {
            const schemaName = container.getAttribute('data-schema-name');
            const displayLogicStr = container.getAttribute('data-display-logic');

            if (!schemaName || !displayLogicStr) {
                console.warn('[DisplayLogic] Container missing schema-name or display-logic:', container);
                return;
            }

            try {
                const displayLogic = JSON.parse(displayLogicStr);
                this.displayLogicRules.set(schemaName, displayLogic);
                this.schemaContainers.set(schemaName, container);
                this.visibilityState.set(schemaName, false); // Start hidden

                if (this.debug) {
                    console.log('[DisplayLogic] Found rule for schema:', schemaName, displayLogic);
                }
            } catch (e) {
                console.error('[DisplayLogic] Failed to parse display logic for', schemaName, ':', e);
            }
        });
    }

    /**
     * Build the dependency graph (which schemas depend on which others).
     */
    buildDependencyGraph() {
        this.displayLogicRules.forEach((rule, schemaName) => {
            const conditions = rule.show_when || [];

            conditions.forEach(condition => {
                const watchedSchema = condition.schema;

                if (!this.dependencies.has(watchedSchema)) {
                    this.dependencies.set(watchedSchema, new Set());
                }
                this.dependencies.get(watchedSchema).add(schemaName);
            });
        });
    }

    /**
     * Evaluate all display logic rules.
     * Called on page load and after annotation changes.
     */
    evaluateAll() {
        const annotations = this.getCurrentAnnotations();

        if (this.debug) {
            console.log('[DisplayLogic] Evaluating all rules with annotations:', annotations);
        }

        this.displayLogicRules.forEach((rule, schemaName) => {
            const shouldBeVisible = this.evaluateRule(rule, annotations);
            this.updateVisibility(schemaName, shouldBeVisible);
        });
    }

    /**
     * Evaluate rules only for schemas that depend on the changed schema.
     * More efficient than evaluateAll() for targeted updates.
     *
     * @param {string} changedSchema - The schema that changed
     */
    evaluateForSchema(changedSchema) {
        const dependents = this.dependencies.get(changedSchema);

        if (!dependents || dependents.size === 0) {
            return;
        }

        const annotations = this.getCurrentAnnotations();

        if (this.debug) {
            console.log('[DisplayLogic] Evaluating dependents of', changedSchema, ':', [...dependents]);
        }

        dependents.forEach(schemaName => {
            const rule = this.displayLogicRules.get(schemaName);
            if (rule) {
                const shouldBeVisible = this.evaluateRule(rule, annotations);
                this.updateVisibility(schemaName, shouldBeVisible);
            }
        });
    }

    /**
     * Get current annotations from the global state.
     * @returns {Object} Current annotations keyed by schema name
     */
    getCurrentAnnotations() {
        // Try to get from global currentAnnotations (set by annotation.js)
        if (typeof currentAnnotations !== 'undefined' && currentAnnotations) {
            // Transform from {schema: {label: value}} to {schema: value}
            const result = {};

            for (const [schema, labels] of Object.entries(currentAnnotations)) {
                // For radio/select: single value
                // For multiselect: array of selected values
                // For text/slider: direct value

                if (labels && typeof labels === 'object') {
                    // Check if it's a radio (single selection)
                    const selectedLabels = [];
                    let textValue = null;

                    for (const [label, value] of Object.entries(labels)) {
                        if (value === true || value === 'true' || value === 1) {
                            selectedLabels.push(label);
                        } else if (typeof value === 'string' || typeof value === 'number') {
                            // Text or numeric value
                            textValue = value;
                        }
                    }

                    if (selectedLabels.length === 1) {
                        // Single selection (radio)
                        result[schema] = selectedLabels[0];
                    } else if (selectedLabels.length > 1) {
                        // Multiple selections (multiselect)
                        result[schema] = selectedLabels;
                    } else if (textValue !== null) {
                        // Text/numeric input
                        result[schema] = textValue;
                    }
                } else if (labels !== null && labels !== undefined) {
                    result[schema] = labels;
                }
            }

            return result;
        }

        // Fallback: scan DOM for current values
        return this.getAnnotationsFromDOM();
    }

    /**
     * Fallback method to get annotations directly from DOM elements.
     * @returns {Object} Annotations keyed by schema name
     */
    getAnnotationsFromDOM() {
        const annotations = {};

        // Radio buttons
        document.querySelectorAll('input[type="radio"]:checked').forEach(input => {
            const schema = input.getAttribute('schema');
            if (schema) {
                annotations[schema] = input.value;
            }
        });

        // Checkboxes (multiselect)
        const checkboxSchemas = new Map();
        document.querySelectorAll('input[type="checkbox"]:checked').forEach(input => {
            const schema = input.getAttribute('schema');
            if (schema) {
                if (!checkboxSchemas.has(schema)) {
                    checkboxSchemas.set(schema, []);
                }
                checkboxSchemas.get(schema).push(input.value);
            }
        });
        checkboxSchemas.forEach((values, schema) => {
            annotations[schema] = values;
        });

        // Text inputs
        document.querySelectorAll('textarea.annotation-input, input[type="text"].annotation-input').forEach(input => {
            const schema = input.getAttribute('schema');
            if (schema) {
                annotations[schema] = input.value;
            }
        });

        // Sliders
        document.querySelectorAll('input[type="range"].annotation-input').forEach(input => {
            const schema = input.getAttribute('schema');
            if (schema) {
                annotations[schema] = parseFloat(input.value);
            }
        });

        // Number inputs
        document.querySelectorAll('input[type="number"].annotation-input').forEach(input => {
            const schema = input.getAttribute('schema');
            if (schema) {
                annotations[schema] = parseFloat(input.value);
            }
        });

        // Select dropdowns
        document.querySelectorAll('select.annotation-input').forEach(select => {
            const schema = select.getAttribute('schema');
            if (schema && select.value) {
                annotations[schema] = select.value;
            }
        });

        return annotations;
    }

    /**
     * Evaluate a display logic rule.
     *
     * @param {Object} rule - The display_logic rule configuration
     * @param {Object} annotations - Current annotations
     * @returns {boolean} Whether the schema should be visible
     */
    evaluateRule(rule, annotations) {
        const conditions = rule.show_when || [];
        const logic = rule.logic || 'all';

        if (conditions.length === 0) {
            return true; // No conditions = always visible
        }

        const results = conditions.map(condition => {
            return this.evaluateCondition(condition, annotations);
        });

        if (logic === 'all') {
            return results.every(r => r);
        } else {
            return results.some(r => r);
        }
    }

    /**
     * Evaluate a single condition.
     *
     * @param {Object} condition - The condition configuration
     * @param {Object} annotations - Current annotations
     * @returns {boolean} Whether the condition is satisfied
     */
    evaluateCondition(condition, annotations) {
        const { schema, operator, value, case_sensitive = false } = condition;
        const actualValue = annotations[schema];

        if (this.debug) {
            console.log('[DisplayLogic] Evaluating:', schema, operator, value, '| actual:', actualValue);
        }

        // Handle empty/not_empty first
        if (operator === 'empty') {
            return this.isEmpty(actualValue);
        }
        if (operator === 'not_empty') {
            return !this.isEmpty(actualValue);
        }

        // Equality operators
        if (operator === 'equals') {
            return this.checkEquals(actualValue, value, case_sensitive);
        }
        if (operator === 'not_equals') {
            return !this.checkEquals(actualValue, value, case_sensitive);
        }

        // Contains operators
        if (operator === 'contains') {
            return this.checkContains(actualValue, value, case_sensitive);
        }
        if (operator === 'not_contains') {
            return !this.checkContains(actualValue, value, case_sensitive);
        }

        // Regex matching
        if (operator === 'matches') {
            return this.checkMatches(actualValue, value, case_sensitive);
        }

        // Numeric comparisons
        if (['gt', 'gte', 'lt', 'lte'].includes(operator)) {
            return this.checkNumeric(operator, actualValue, value);
        }

        // Range operators
        if (operator === 'in_range') {
            return this.checkRange(actualValue, value);
        }
        if (operator === 'not_in_range') {
            return !this.checkRange(actualValue, value);
        }

        // Length operators
        if (['length_gt', 'length_lt'].includes(operator)) {
            return this.checkLength(operator, actualValue, value);
        }
        if (operator === 'length_in_range') {
            return this.checkLengthRange(actualValue, value);
        }

        console.warn('[DisplayLogic] Unknown operator:', operator);
        return false;
    }

    /**
     * Check if a value is empty.
     */
    isEmpty(value) {
        if (value === null || value === undefined) {
            return true;
        }
        if (typeof value === 'string') {
            return value.trim().length === 0;
        }
        if (Array.isArray(value)) {
            return value.length === 0;
        }
        return false;
    }

    /**
     * Check equality (handles single value or list of values).
     */
    checkEquals(actual, expected, caseSensitive) {
        if (Array.isArray(expected)) {
            // Check if actual matches ANY of the expected values
            return expected.some(exp => this.valuesEqual(actual, exp, caseSensitive));
        }
        return this.valuesEqual(actual, expected, caseSensitive);
    }

    /**
     * Compare two values for equality.
     */
    valuesEqual(actual, expected, caseSensitive) {
        if (actual === null || actual === undefined) {
            return expected === null || expected === undefined;
        }

        // String comparison with case sensitivity
        if (typeof expected === 'string') {
            const actualStr = String(actual);
            if (!caseSensitive) {
                return actualStr.toLowerCase() === expected.toLowerCase();
            }
            return actualStr === expected;
        }

        return actual === expected;
    }

    /**
     * Check if actual contains expected value(s).
     */
    checkContains(actual, expected, caseSensitive) {
        if (Array.isArray(expected)) {
            // Check if actual contains ANY of the expected values
            return expected.some(exp => this.valueContains(actual, exp, caseSensitive));
        }
        return this.valueContains(actual, expected, caseSensitive);
    }

    /**
     * Check if actual contains a single expected value.
     */
    valueContains(actual, expected, caseSensitive) {
        // If actual is a list (multiselect), check membership
        if (Array.isArray(actual)) {
            return actual.some(item => this.valuesEqual(item, expected, caseSensitive));
        }

        // If actual is a string, check substring
        if (typeof actual === 'string') {
            const expectedStr = String(expected);
            if (!caseSensitive) {
                return actual.toLowerCase().includes(expectedStr.toLowerCase());
            }
            return actual.includes(expectedStr);
        }

        // Fallback to equality
        return this.valuesEqual(actual, expected, caseSensitive);
    }

    /**
     * Check regex match.
     */
    checkMatches(actual, pattern, caseSensitive) {
        if (actual === null || actual === undefined) {
            return false;
        }

        try {
            const flags = caseSensitive ? '' : 'i';
            const regex = new RegExp(pattern, flags);
            return regex.test(String(actual));
        } catch (e) {
            console.warn('[DisplayLogic] Invalid regex pattern:', pattern, e);
            return false;
        }
    }

    /**
     * Check numeric comparison.
     */
    checkNumeric(operator, actual, expected) {
        const actualNum = parseFloat(actual);
        const expectedNum = parseFloat(expected);

        if (isNaN(actualNum) || isNaN(expectedNum)) {
            return false;
        }

        switch (operator) {
            case 'gt': return actualNum > expectedNum;
            case 'gte': return actualNum >= expectedNum;
            case 'lt': return actualNum < expectedNum;
            case 'lte': return actualNum <= expectedNum;
            default: return false;
        }
    }

    /**
     * Check if value is in range (inclusive).
     */
    checkRange(actual, range) {
        if (!Array.isArray(range) || range.length !== 2) {
            return false;
        }

        const actualNum = parseFloat(actual);
        const minVal = parseFloat(range[0]);
        const maxVal = parseFloat(range[1]);

        if (isNaN(actualNum) || isNaN(minVal) || isNaN(maxVal)) {
            return false;
        }

        return actualNum >= minVal && actualNum <= maxVal;
    }

    /**
     * Check text length comparison.
     */
    checkLength(operator, actual, expected) {
        const length = actual ? String(actual).length : 0;
        const expectedLen = parseInt(expected);

        if (isNaN(expectedLen)) {
            return false;
        }

        if (operator === 'length_gt') {
            return length > expectedLen;
        }
        if (operator === 'length_lt') {
            return length < expectedLen;
        }

        return false;
    }

    /**
     * Check if text length is in range.
     */
    checkLengthRange(actual, range) {
        if (!Array.isArray(range) || range.length !== 2) {
            return false;
        }

        const length = actual ? String(actual).length : 0;
        const minLen = parseInt(range[0]);
        const maxLen = parseInt(range[1]);

        if (isNaN(minLen) || isNaN(maxLen)) {
            return false;
        }

        return length >= minLen && length <= maxLen;
    }

    /**
     * Update the visibility of a schema container.
     *
     * @param {string} schemaName - The schema to update
     * @param {boolean} shouldBeVisible - Whether it should be visible
     */
    updateVisibility(schemaName, shouldBeVisible) {
        const container = this.schemaContainers.get(schemaName);
        if (!container) {
            return;
        }

        const wasVisible = this.visibilityState.get(schemaName);

        if (shouldBeVisible === wasVisible) {
            return; // No change needed
        }

        this.visibilityState.set(schemaName, shouldBeVisible);

        if (this.debug) {
            console.log('[DisplayLogic] Visibility change:', schemaName, wasVisible, '->', shouldBeVisible);
        }

        // Track display logic change in behavioral tracker
        const reason = this.getVisibilityReason(schemaName, shouldBeVisible);
        if (window.interactionTracker) {
            window.interactionTracker.trackDisplayLogicChange(schemaName, shouldBeVisible, reason);

            // If hiding a schema that has a value, track it as stale
            if (!shouldBeVisible && wasVisible) {
                const schemaValue = this.getSchemaValue(schemaName);
                if (schemaValue !== null && schemaValue !== undefined) {
                    window.interactionTracker.trackStaleAnnotation(schemaName, schemaValue, reason);
                }
            }
        }

        if (shouldBeVisible) {
            this.showContainer(container);
        } else {
            this.hideContainer(container);
        }
    }

    /**
     * Get the current value of a schema from annotations.
     * @param {string} schemaName - The schema to get value for
     * @returns {*} The schema value or null
     */
    getSchemaValue(schemaName) {
        const annotations = this.getCurrentAnnotations();
        return annotations[schemaName] || null;
    }

    /**
     * Get the reason for a visibility state.
     * @param {string} schemaName - The schema
     * @param {boolean} visible - The visibility state
     * @returns {string} Human-readable reason
     */
    getVisibilityReason(schemaName, visible) {
        if (visible) {
            return 'Conditions met';
        }

        const rule = this.displayLogicRules.get(schemaName);
        if (!rule) {
            return 'No rule defined';
        }

        const annotations = this.getCurrentAnnotations();
        const conditions = rule.show_when || [];
        const reasons = conditions.map(cond => {
            const actual = annotations[cond.schema];
            return `${cond.schema} ${cond.operator} ${JSON.stringify(cond.value)} (actual: ${JSON.stringify(actual)})`;
        });

        return `Conditions not met (${rule.logic || 'all'}): ${reasons.join(', ')}`;
    }

    /**
     * Show a container with animation.
     */
    showContainer(container) {
        container.classList.remove('display-logic-hidden');
        container.classList.add('display-logic-visible');

        // Trigger reflow for animation
        container.offsetHeight;

        // Optional: scroll into view if newly visible
        if (this.shouldScrollIntoView(container)) {
            setTimeout(() => {
                container.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }, this.animationDuration);
        }
    }

    /**
     * Hide a container with animation.
     */
    hideContainer(container) {
        container.classList.remove('display-logic-visible');
        container.classList.add('display-logic-hidden');
    }

    /**
     * Check if we should scroll the container into view.
     * Only scroll if it's mostly off-screen.
     */
    shouldScrollIntoView(container) {
        const rect = container.getBoundingClientRect();
        const viewHeight = window.innerHeight || document.documentElement.clientHeight;

        // Check if the container is mostly visible
        const visibleHeight = Math.min(rect.bottom, viewHeight) - Math.max(rect.top, 0);
        const containerHeight = rect.height;

        // Scroll if less than 50% is visible
        return visibleHeight < containerHeight * 0.5;
    }

    /**
     * Check if a schema is currently visible according to display logic.
     *
     * @param {string} schemaName - The schema to check
     * @returns {boolean} True if visible (or if no display logic)
     */
    isSchemaVisible(schemaName) {
        // If no display_logic rule, it's always visible
        if (!this.displayLogicRules.has(schemaName)) {
            return true;
        }
        return this.visibilityState.get(schemaName) || false;
    }

    /**
     * Get the visibility state for all schemas.
     * Used for saving with annotations.
     *
     * @returns {Object} Map of schema name -> {visible: boolean, reason?: string}
     */
    getVisibilityState() {
        const state = {};

        this.displayLogicRules.forEach((rule, schemaName) => {
            const visible = this.visibilityState.get(schemaName) || false;
            state[schemaName] = { visible };

            if (!visible) {
                // Build reason string
                const conditions = rule.show_when || [];
                const annotations = this.getCurrentAnnotations();
                const reasons = conditions.map(cond => {
                    const actual = annotations[cond.schema];
                    return `${cond.schema} ${cond.operator} ${JSON.stringify(cond.value)} (actual: ${JSON.stringify(actual)})`;
                });
                state[schemaName].reason = `Conditions not met (${rule.logic || 'all'}): ${reasons.join(', ')}`;
            }
        });

        return state;
    }

    /**
     * Enable debug logging.
     */
    enableDebug() {
        this.debug = true;
        console.log('[DisplayLogic] Debug mode enabled');
    }

    /**
     * Disable debug logging.
     */
    disableDebug() {
        this.debug = false;
    }
}

// Global instance
let displayLogicManager = null;

/**
 * Initialize the display logic manager.
 * Called automatically when the page loads.
 */
function initDisplayLogic() {
    if (displayLogicManager) {
        console.warn('[DisplayLogic] Already initialized');
        return displayLogicManager;
    }

    displayLogicManager = new DisplayLogicManager();
    displayLogicManager.initialize();

    return displayLogicManager;
}

/**
 * Get the global display logic manager instance.
 */
function getDisplayLogicManager() {
    return displayLogicManager;
}
