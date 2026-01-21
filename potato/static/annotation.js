// Debug logging utility - respects the debug setting from server config
function debugLog(...args) {
    if (window.config && window.config.debug) {
        console.log(...args);
    }
}

function debugWarn(...args) {
    if (window.config && window.config.debug) {
        console.warn(...args);
    }
}

// Global state
let currentInstance = null;
let currentAnnotations = {};
let userState = null;
let isLoading = false;
let textSaveTimer = null;
let currentSpanAnnotations = [];
let debugLastInstanceId = null;
let debugOverlayCount = 0;

// Stored event handler references for proper cleanup (prevents memory leaks)
const boundEventHandlers = {
    spanManagerMouseUp: null,
    spanManagerKeyUp: null,
    robustTextSelectionMouseUp: null,
    robustTextSelectionKeyUp: null
};

let aiAssistantManger = new AIAssistantManager();

// DEEP DEBUG: Enhanced tracking
let deepDebugState = {
    navigationCalls: 0,
    instanceIdChanges: [],
    overlayStates: [],
    spanManagerCalls: [],
    lastAction: null,
    timestamp: new Date().toISOString()
};

/**
 * Deep debug logging for navigation events - only logs when debug mode is enabled
 */
function logDeepDebug(action, extraData = {}) {
    // Skip all debug logging when not in debug mode
    if (!window.config || !window.config.debug) {
        return;
    }

    const state = {
        timestamp: new Date().toISOString(),
        action: action,
        currentInstanceId: currentInstance?.id,
        debugLastInstanceId: debugLastInstanceId,
        isLoading: isLoading,
        overlayCount: getCurrentOverlayCount(),
        spanManagerExists: !!window.spanManager,
        spanManagerInitialized: window.spanManager?.isInitialized,
        ...extraData
    };

    debugLog(`[DEEP DEBUG NAV] ${action}:`, state);
    deepDebugState.lastAction = action;
    deepDebugState.timestamp = new Date().toISOString();

    // Track instance ID changes
    if (extraData.newInstanceId || extraData.currentInstanceId) {
        deepDebugState.instanceIdChanges.push({
            timestamp: new Date().toISOString(),
            from: debugLastInstanceId,
            to: extraData.newInstanceId || extraData.currentInstanceId,
            action: action
        });
    }

    // Track overlay states
    deepDebugState.overlayStates.push({
        timestamp: new Date().toISOString(),
        action: action,
        overlayCount: getCurrentOverlayCount(),
        instanceId: currentInstance?.id
    });

    // Keep only last 20 entries to avoid memory bloat
    if (deepDebugState.instanceIdChanges.length > 20) {
        deepDebugState.instanceIdChanges = deepDebugState.instanceIdChanges.slice(-20);
    }
    if (deepDebugState.overlayStates.length > 20) {
        deepDebugState.overlayStates = deepDebugState.overlayStates.slice(-20);
    }
}

/**
 * Get current overlay count for debugging
 */
function getCurrentOverlayCount() {
    const spanOverlays = document.getElementById('span-overlays');
    return spanOverlays ? spanOverlays.children.length : 0;
}

// Initialize the application
document.addEventListener('DOMContentLoaded', function () {
    loadCurrentInstance();
    setupEventListeners();
    // Initial validation check
    validateRequiredFields();
    // Initialize span manager integration
    initializeSpanManagerIntegration();
});

/**
 * Global overlay tracking for debugging - only logs when debug mode is enabled
 */
function trackOverlayCreation(overlay, context = 'unknown') {
    if (!window.config || !window.config.debug) return;

    debugLog(`[DEBUG] OVERLAY CREATED in ${context}:`, {
        className: overlay.className,
        id: overlay.id,
        parentId: overlay.parentElement?.id,
        timestamp: new Date().toISOString()
    });

    // Track total overlays
    const totalOverlays = document.querySelectorAll('.span-overlay').length;
    debugLog(`[DEBUG] TOTAL OVERLAYS after creation: ${totalOverlays}`);
}

function trackOverlayRemoval(overlay, context = 'unknown') {
    if (!window.config || !window.config.debug) return;

    debugLog(`[DEBUG] OVERLAY REMOVED in ${context}:`, {
        className: overlay.className,
        id: overlay.id,
        timestamp: new Date().toISOString()
    });

    // Track total overlays
    const totalOverlays = document.querySelectorAll('.span-overlay').length;
    debugLog(`[DEBUG] TOTAL OVERLAYS after removal: ${totalOverlays}`);
}

function debugTrackOverlays(action, instanceId = null) {
    if (!window.config || !window.config.debug) return;

    const spanOverlays = document.getElementById('span-overlays');
    const overlayCount = spanOverlays ? spanOverlays.children.length : 0;
    const instanceText = document.getElementById('instance-text');
    const textContent = document.getElementById('text-content');

    debugLog(`[DEBUG OVERLAY TRACKING] ${action}:`, {
        instanceId: instanceId || currentInstance?.id,
        lastInstanceId: debugLastInstanceId,
        overlayCount: overlayCount,
        spanOverlaysExists: !!spanOverlays,
        instanceTextExists: !!instanceText,
        textContentExists: !!textContent,
        spanOverlaysHTML: spanOverlays ? spanOverlays.innerHTML.substring(0, 200) + '...' : 'null',
        timestamp: new Date().toISOString()
    });

    debugOverlayCount = overlayCount;
    if (instanceId) debugLastInstanceId = instanceId;
}

// DEBUG: Add overlay cleanup verification - only logs when debug mode is enabled
function debugVerifyOverlayCleanup() {
    if (!window.config || !window.config.debug) return;

    const spanOverlays = document.getElementById('span-overlays');
    if (!spanOverlays) {
        debugWarn('[DEBUG] span-overlays container not found during cleanup verification');
        return;
    }

    const overlayCount = spanOverlays.children.length;
    debugLog(`[DEBUG] Overlay cleanup verification:`, {
        overlayCount: overlayCount,
        containerEmpty: overlayCount === 0,
        containerInnerHTML: spanOverlays.innerHTML,
        containerChildren: Array.from(spanOverlays.children).map(child => ({
            tagName: child.tagName,
            className: child.className,
            dataset: child.dataset
        }))
    });

    if (overlayCount > 0) {
        debugWarn('[DEBUG] WARNING: Overlays still present after expected cleanup!');
    }
}

function setupEventListeners() {
    // Go to button
    document.getElementById('go-to-btn').addEventListener('click', function () {
        const goToValue = document.getElementById('go_to').value;
        if (goToValue && goToValue > 0) {
            navigateToInstance(parseInt(goToValue));
        }
    });

    // Enter key on go to input
    document.getElementById('go_to').addEventListener('keypress', function (e) {
        if (e.key === 'Enter') {
            document.getElementById('go-to-btn').click();
        }
    });

    // Keyboard navigation and shortcuts
    document.addEventListener('keydown', function (e) {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
            return; // Don't handle navigation when typing
        }

        switch (e.key) {
            case 'ArrowLeft':
                e.preventDefault();
                navigateToPrevious();
                break;
            case 'ArrowRight':
                e.preventDefault();
                navigateToNext();
                break;
        }
    });

    // Keyboard shortcuts for checkboxes and radio buttons (matches base_template.html behavior)
    document.addEventListener('keyup', function (e) {
        // Don't handle when in input fields
        const activeElement = document.activeElement;
        const activeId = activeElement.id;
        const activeType = activeElement.getAttribute('type');
        if (activeId === 'go_to' || activeType === 'text' ||
            activeElement.tagName === 'INPUT' || activeElement.tagName === 'TEXTAREA') {
            return;
        }

        const key = e.key.toLowerCase();

        // Check checkboxes first
        const checkboxes = document.querySelectorAll('input[type="checkbox"]');
        for (const checkbox of checkboxes) {
            if (key === checkbox.value.toLowerCase()) {
                checkbox.checked = !checkbox.checked;
                // Trigger change event so annotation state gets updated
                checkbox.dispatchEvent(new Event('change', { bubbles: true }));
                if (checkbox.onclick) {
                    checkbox.onclick.apply(checkbox);
                }
                return;
            }
        }

        // Check radio buttons
        const radios = document.querySelectorAll('input[type="radio"]');
        for (const radio of radios) {
            if (key === radio.value.toLowerCase()) {
                radio.checked = true;
                // Trigger change event so annotation state gets updated
                radio.dispatchEvent(new Event('change', { bubbles: true }));
                if (radio.onclick) {
                    radio.onclick.apply(radio);
                }
                return;
            }
        }
    });
}

/**
 * Initialize integration with the frontend span manager
 */
function initializeSpanManagerIntegration() {
    // Wait for span manager to be available
    const checkSpanManager = () => {
        if (window.spanManager && window.spanManager.isInitialized) {
            debugLog('Annotation.js: Span manager integration initialized');
            setupSpanLabelSelector();
        } else {
            setTimeout(checkSpanManager, 100);
        }
    };
    checkSpanManager();
}

/**
 * Setup span label selector interface
 * This function sets up the span label selection checkboxes and their event handlers
 */
function setupSpanLabelSelector() {
    debugLog('🔍 [DEBUG] setupSpanLabelSelector() - ENTRY POINT');

    // Find all span label checkboxes
    const spanLabelCheckboxes = document.querySelectorAll('input[name*="span_label"]');
    debugLog('🔍 [DEBUG] setupSpanLabelSelector() - Found span label checkboxes:', spanLabelCheckboxes.length);

    if (spanLabelCheckboxes.length === 0) {
        debugLog('🔍 [DEBUG] setupSpanLabelSelector() - No span label checkboxes found');
        debugLog('🔍 [DEBUG] setupSpanLabelSelector() - EXIT POINT (no checkboxes)');
        return;
    }

    // Set up event listeners for each checkbox
    spanLabelCheckboxes.forEach((checkbox, index) => {
        debugLog(`🔍 [DEBUG] setupSpanLabelSelector() - Setting up checkbox ${index}:`, {
            name: checkbox.name,
            id: checkbox.id,
            value: checkbox.value
        });

        // Add MutationObserver to track checkbox state changes
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                if (mutation.type === 'attributes' && mutation.attributeName === 'checked') {
                    debugLog('🔍 [DEBUG] setupSpanLabelSelector() - Checkbox checked attribute changed:', {
                        id: checkbox.id,
                        oldValue: mutation.oldValue,
                        newValue: checkbox.checked,
                        stack: new Error().stack
                    });
                }
            });
        });

        observer.observe(checkbox, {
            attributes: true,
            attributeOldValue: true,
            attributeFilter: ['checked']
        });

        // Override the checked property to track when it's set programmatically
        const originalChecked = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'checked');
        Object.defineProperty(checkbox, 'checked', {
            get: function() {
                return originalChecked.get.call(this);
            },
            set: function(value) {
                debugLog('🔍 [DEBUG] setupSpanLabelSelector() - Checkbox checked property being set:', {
                    id: this.id,
                    oldValue: originalChecked.get.call(this),
                    newValue: value,
                    stack: new Error().stack
                });
                originalChecked.set.call(this, value);
            }
        });

        // Add click event listener if not already present
        if (!checkbox.hasAttribute('data-span-label-setup')) {
            checkbox.addEventListener('change', function () {
                debugLog('🔍 [DEBUG] setupSpanLabelSelector() - Checkbox changed:', {
                    name: this.name,
                    checked: this.checked,
                    value: this.value
                });

                // Add stack trace to see what's calling this
                debugLog('🔍 [DEBUG] setupSpanLabelSelector() - Change event stack trace:', new Error().stack);

                // Check if this change event was triggered by programmatic setting
                // If the checkbox was just set to checked by onlyOne, don't interfere
                if (this.checked && this.hasAttribute('data-just-checked')) {
                    debugLog('🔍 [DEBUG] setupSpanLabelSelector() - Ignoring change event for just-checked checkbox');
                    this.removeAttribute('data-just-checked');
                    return;
                }

                // Note: We don't manage checkbox state here anymore because the onclick
                // handler (onlyOne function) already handles this correctly.
                // This change event is just for logging and any additional functionality
                // that might be needed in the future.
            });

            // Mark as set up
            checkbox.setAttribute('data-span-label-setup', 'true');
        }
    });

    debugLog('🔍 [DEBUG] setupSpanLabelSelector() - EXIT POINT (setup complete)');
}



/**
 * Check if current instance has span annotations
 */
function checkForSpanAnnotations() {
    if (!currentInstance || !currentInstance.annotation_scheme) {
        return false;
    }

    // Check if any annotation type is 'span'
    for (const schema of Object.values(currentInstance.annotation_scheme)) {
        if (schema.type === 'span') {
            return true;
        }
    }
    return false;
}

/**
 * Get span labels from annotation scheme
 */
function getSpanLabelsFromScheme() {
    const labels = [];

    if (!currentInstance || !currentInstance.annotation_scheme) {
        return labels;
    }

    for (const [schemaName, schema] of Object.entries(currentInstance.annotation_scheme)) {
        if (schema.type === 'span' && schema.labels) {
            labels.push(...schema.labels);
        }
    }

    return labels;
}

/**
 * Load span annotations for current instance
 */
async function loadSpanAnnotations() {
    debugLog('🔍 [DEBUG] loadSpanAnnotations() - ENTRY POINT');
    debugLog('🔍 [DEBUG] loadSpanAnnotations() - currentInstance:', currentInstance);
    debugLog('🔍 [DEBUG] loadSpanAnnotations() - currentInstance.id:', currentInstance?.id);

    if (!currentInstance || !currentInstance.id) {
        debugLog('🔍 [DEBUG] loadSpanAnnotations() - EXIT POINT (no currentInstance or id)');
        return;
    }

    try {
        // Initialize span manager if not already done
        if (!window.spanManager) {
            debugLog('🔍 [DEBUG] loadSpanAnnotations() - Initializing span manager');
            initializeSpanManagerIntegration();
        }

        // Wait for span manager to be ready
        await new Promise(resolve => {
            const checkSpanManager = () => {
                if (window.spanManager) {
                    debugLog('🔍 [DEBUG] loadSpanAnnotations() - Span manager ready');
                    resolve();
                } else {
                    debugLog('🔍 [DEBUG] loadSpanAnnotations() - Span manager not ready, retrying...');
                    setTimeout(checkSpanManager, 100);
                }
            };
            checkSpanManager();
        });

        debugLog('🔍 [DEBUG] loadSpanAnnotations() - About to call spanManager.loadAnnotations()');
        debugLog('🔍 [DEBUG] loadSpanAnnotations() - Instance ID for API call:', currentInstance.id);

        // Load annotations for the current instance
        await window.spanManager.loadAnnotations(currentInstance.id);

        debugLog('🔍 [DEBUG] loadSpanAnnotations() - spanManager.loadAnnotations() completed');
        debugLog('🔍 [DEBUG] loadSpanAnnotations() - EXIT POINT (success)');
    } catch (error) {
        console.error('🔍 [DEBUG] loadSpanAnnotations() - Error loading span annotations:', error);
        debugLog('🔍 [DEBUG] loadSpanAnnotations() - EXIT POINT (error)');
    }
}

async function loadCurrentInstance() {
    try {
        setLoading(true);
        showError(false);

        // DEBUG: Track overlays at start of instance loading
        debugTrackOverlays('START_LOAD_CURRENT_INSTANCE');

        // Get current instance from server-rendered HTML
        const instanceTextElement = document.getElementById('instance-text');
        const instanceIdElement = document.getElementById('instance_id');

        if (!instanceTextElement) {
            throw new Error('Instance text element not found');
        }

        // Get instance text from the rendered HTML (server-rendered)
        const instanceText = instanceTextElement.innerHTML;

        // Get instance ID from hidden input
        const instanceId = instanceIdElement ? instanceIdElement.value : null;
        debugLog(`🔍 [DEBUG] loadCurrentInstance: Read instance_id from DOM: '${instanceId}'`);

        if (!instanceText || instanceText.trim() === '') {
            showError(true, 'No instance text available');
            return;
        }

        // Create current instance object from server-rendered data
        currentInstance = {
            id: instanceId,
            text: instanceTextElement.textContent || instanceTextElement.innerText,
            displayed_text: instanceText
        };

        // Set global variable for span manager
        window.currentInstance = currentInstance;

        // Get progress from the progress counter element
        const progressCounter = document.getElementById('progress-counter');
        if (progressCounter) {
            const progressText = progressCounter.textContent;
            const match = progressText.match(/(\d+)\/(\d+)/);
            if (match) {
                const annotated = parseInt(match[1]);
                const total = parseInt(match[2]);
                userState = {
                    assignments: {
                        annotated: annotated,
                        total: total
                    },
                    annotations: {
                        by_instance: {}
                    }
                };
            }
        }

        updateProgressDisplay();
        updateInstanceDisplay();
        restoreSpanAnnotationsFromHTML();
        loadAnnotations();
        generateAnnotationForms();
        aiAssistantManger.getAiAssistantName();

        // Load span annotations
        debugLog('🔍 [DEBUG] loadCurrentInstance() - About to call loadSpanAnnotations()');
        debugLog('🔍 [DEBUG] loadCurrentInstance() - currentInstance.id:', currentInstance?.id);
        await loadSpanAnnotations();
        debugLog('🔍 [DEBUG] loadCurrentInstance() - loadSpanAnnotations() completed');

        // Populate input values with existing annotations AFTER forms are generated
        setTimeout(() => {
            populateInputValues();
        }, 0);

    } catch (error) {
        console.error('Error loading current instance:', error);
        showError(true, error.message);
    } finally {
        setLoading(false);
    }
}

function updateProgressDisplay() {
    // Progress is already displayed in the HTML template
    // No need to update it since it's server-rendered
    debugLog('Progress display updated from server-rendered HTML');
}

function updateInstanceDisplay() {
    // Instance text is already displayed in the HTML template
    // Just ensure the instance_id is set correctly
    const instanceIdInput = document.getElementById('instance_id');
    if (instanceIdInput && currentInstance && currentInstance.id) {
        const oldValue = instanceIdInput.value;
        instanceIdInput.value = currentInstance.id;
        debugLog(`🔍 [DEBUG] updateInstanceDisplay: Updated instance_id from '${oldValue}' to '${currentInstance.id}'`);

        // FIREFOX FIX: Force the input element to be updated in Firefox
        const isFirefox = navigator.userAgent.toLowerCase().includes('firefox');
        if (isFirefox) {
            debugLog('🔍 [DEBUG] updateInstanceDisplay: Firefox detected - forcing input update');

            // Method 1: Force a DOM update by temporarily changing and restoring the value
            const tempValue = instanceIdInput.value;
            instanceIdInput.value = '';
            instanceIdInput.value = tempValue;

            // Method 2: Trigger input events to ensure Firefox recognizes the change
            instanceIdInput.dispatchEvent(new Event('input', { bubbles: true }));
            instanceIdInput.dispatchEvent(new Event('change', { bubbles: true }));

            // Method 3: Force a reflow
            instanceIdInput.offsetHeight;

            debugLog(`🔍 [DEBUG] updateInstanceDisplay: Firefox input update completed`);
        }
    } else {
        debugLog(`🔍 [DEBUG] updateInstanceDisplay: Could not update instance_id - input: ${!!instanceIdInput}, currentInstance: ${!!currentInstance}, currentInstance.id: ${currentInstance?.id}`);
    }
    debugLog('[DEBUG] updateInstanceDisplay: Instance display updated from server');
}

// Add this function to clear all form inputs
function clearAllFormInputs() {
    debugLog('🔍 Clearing all form inputs');

    // Clear text inputs and textareas
    const textInputs = document.querySelectorAll('input[type="text"], textarea.annotation-input');
    textInputs.forEach(input => {
        input.value = '';
    });

    // Clear radio buttons
    const radioInputs = document.querySelectorAll('input[type="radio"]');
    radioInputs.forEach(input => {
        input.checked = false;
    });

    // Clear checkboxes
    const checkboxInputs = document.querySelectorAll('input[type="checkbox"]');
    checkboxInputs.forEach(input => {
        input.checked = false;
    });

    // Clear sliders
    const sliderInputs = document.querySelectorAll('input[type="range"]');
    sliderInputs.forEach(input => {
        input.value = input.getAttribute('min') || input.getAttribute('starting_value') || '0';
        const valueDisplay = document.getElementById(`${input.name}-value`);
        if (valueDisplay) {
            valueDisplay.textContent = input.value;
        }
    });

    // Clear select dropdowns
    const selectInputs = document.querySelectorAll('select.annotation-input');
    selectInputs.forEach(input => {
        input.selectedIndex = 0;
    });

    // Clear number inputs
    const numberInputs = document.querySelectorAll('input[type="number"].annotation-input');
    numberInputs.forEach(input => {
        input.value = '';
    });

    debugLog('✅ All form inputs cleared');
}

async function loadAnnotations() {
    try {
        debugLog('🔍 Loading annotations for instance:', currentInstance.id);

        // IMPORTANT: Read from server-rendered HTML attributes, NOT browser form state.
        // Firefox (and some other browsers) preserve form state across page navigations,
        // which can cause checkboxes from the previous instance to appear checked
        // even though the server didn't render them that way.

        currentAnnotations = {};

        // Read checkbox state from HTML 'checked' ATTRIBUTE (not .checked property)
        // The server sets the 'checked' attribute on checkboxes that should be checked
        const checkboxInputs = document.querySelectorAll('input[type="checkbox"]');
        checkboxInputs.forEach(input => {
            const schema = input.getAttribute('schema');
            const labelName = input.getAttribute('label_name');
            // Use hasAttribute('checked') to read server-rendered state
            const serverChecked = input.hasAttribute('checked');
            // Sync the browser state to match server state (fixes Firefox form restoration)
            input.checked = serverChecked;
            if (schema && labelName && serverChecked) {
                if (!currentAnnotations[schema]) {
                    currentAnnotations[schema] = {};
                }
                currentAnnotations[schema][labelName] = input.value;
            }
        });

        // Read radio button state from HTML 'checked' ATTRIBUTE
        const radioInputs = document.querySelectorAll('input[type="radio"]');
        radioInputs.forEach(input => {
            const schema = input.getAttribute('schema');
            const labelName = input.getAttribute('label_name');
            // Use hasAttribute('checked') to read server-rendered state
            const serverChecked = input.hasAttribute('checked');
            // Sync the browser state to match server state
            input.checked = serverChecked;
            if (schema && labelName && serverChecked) {
                if (!currentAnnotations[schema]) {
                    currentAnnotations[schema] = {};
                }
                currentAnnotations[schema][labelName] = input.value;
            }
        });

        // Read text input state from HTML 'value' ATTRIBUTE
        // For text inputs, the server sets the value attribute
        const textInputs = document.querySelectorAll('input[type="text"], textarea.annotation-input');
        textInputs.forEach(input => {
            const schema = input.getAttribute('schema');
            const labelName = input.getAttribute('label_name');
            // Read from the HTML attribute, not the current input value
            const serverValue = input.getAttribute('value') || '';
            // Sync browser state to server state
            input.value = serverValue;
            if (schema && labelName && serverValue) {
                if (!currentAnnotations[schema]) {
                    currentAnnotations[schema] = {};
                }
                currentAnnotations[schema][labelName] = serverValue;
            }
        });

        // Read slider state from HTML 'value' ATTRIBUTE
        const sliderInputs = document.querySelectorAll('input[type="range"]');
        sliderInputs.forEach(input => {
            const schema = input.getAttribute('schema');
            const labelName = input.getAttribute('label_name');
            // Read from HTML attribute - server sets this for saved slider values
            const serverValue = input.getAttribute('value');
            if (serverValue) {
                input.value = serverValue;
            }
            if (schema && labelName) {
                if (!currentAnnotations[schema]) {
                    currentAnnotations[schema] = {};
                }
                currentAnnotations[schema][labelName] = input.value;
            }
        });

        debugLog('🔍 Annotations loaded from DOM:', currentAnnotations);
    } catch (error) {
        console.error('❌ Error loading annotations:', error);
        currentAnnotations = {};
    }
}

function generateAnnotationForms() {
    const formsContainer = document.getElementById('annotation-forms');

    // The server generates the forms, so we just need to set up event listeners
    // The forms are already in the HTML from server-side generation
    setupInputEventListeners();
    validateRequiredFields();
}

async function saveAnnotations() {
    if (!currentInstance) return;

    try {
        const headers = {
            'Content-Type': 'application/json',
        };

        // Add API key if available
        if (window.config.api_key) {
            headers['X-API-Key'] = window.config.api_key;
        }

        // Save both label and span annotations via /updateinstance
        const spanAnnotations = extractSpanAnnotationsFromDOM();
        debugLog('[DEBUG] saveAnnotations: spanAnnotations to send:', spanAnnotations);

        // Transform currentAnnotations to the format expected by /updateinstance
        const labelAnnotations = {};
        for (const [schema, labels] of Object.entries(currentAnnotations)) {
            for (const [label, value] of Object.entries(labels)) {
                const key = `${schema}:${label}`;
                labelAnnotations[key] = value;
            }
        }

        const response = await fetch('/updateinstance', {
            method: 'POST',
            headers: headers,
            body: JSON.stringify({
                instance_id: currentInstance.id,
                annotations: labelAnnotations,
                span_annotations: spanAnnotations
            })
        });

        if (response.ok) {
            const result = await response.json();
            debugLog('[DEBUG] saveAnnotations: annotations saved:', result);
        } else {
            console.warn('[DEBUG] saveAnnotations: failed to save annotations:', await response.text());
        }

        return true;

    } catch (error) {
        console.error('Error saving annotations:', error);
        showError(true, 'Failed to save annotations: ' + error.message);
        return false;
    }
}

async function navigateToPrevious() {
    debugLog('[DEEP DEBUG NAV] navigateToPrevious - ENTRY POINT');
    deepDebugState.navigationCalls++;

    logDeepDebug('navigateToPrevious_start', {
        currentInstanceId: currentInstance?.id,
        overlayCount: getCurrentOverlayCount()
    });

    if (isLoading) {
        debugLog('[DEEP DEBUG NAV] navigateToPrevious - Navigation blocked, still loading');
        return;
    }

    setLoading(true);
    debugLog('[DEEP DEBUG NAV] navigateToPrevious - Loading set to true');

    try {
        // Save annotations before navigating away
        debugLog('[DEEP DEBUG NAV] navigateToPrevious - Saving annotations before navigation');
        await saveAnnotations();

        // FIREFOX FIX: Force overlay cleanup before navigation
        const isFirefox = navigator.userAgent.toLowerCase().includes('firefox');
        debugLog('[DEEP DEBUG NAV] navigateToPrevious - Is Firefox:', isFirefox);

        if (isFirefox) {
            debugLog('[DEEP DEBUG NAV] Firefox detected - forcing overlay cleanup before navigation');
            const spanOverlays = document.getElementById('span-overlays');
            if (spanOverlays) {
                const beforeCount = spanOverlays.children.length;
                debugLog('[DEEP DEBUG NAV] navigateToPrevious - Before Firefox cleanup:', beforeCount, 'overlays');

                // Remove all overlays individually
                while (spanOverlays.firstChild) {
                    const child = spanOverlays.firstChild;
                    debugLog('[DEEP DEBUG NAV] navigateToPrevious - Removing overlay child:', child.className, child.id);

                    // Track overlay removal for debugging
                    if (typeof trackOverlayRemoval === 'function') {
                        trackOverlayRemoval(child, 'navigateToPrevious Firefox cleanup');
                    }

                    spanOverlays.removeChild(child);
                }

                // Force reflow
                spanOverlays.offsetHeight;
                const afterCount = spanOverlays.children.length;
                debugLog('[DEEP DEBUG NAV] navigateToPrevious - After Firefox cleanup:', afterCount, 'overlays');

                // Double-check cleanup
                const remainingOverlays = document.querySelectorAll('.span-overlay');
                debugLog('[DEEP DEBUG NAV] navigateToPrevious - Remaining overlays via querySelectorAll:', remainingOverlays.length);

                if (remainingOverlays.length > 0) {
                    debugLog('[DEEP DEBUG NAV] navigateToPrevious - WARNING: Overlays still exist after cleanup!');
                    remainingOverlays.forEach((overlay, index) => {
                        debugLog(`[DEEP DEBUG NAV] navigateToPrevious - Remaining overlay ${index}:`, overlay.className, overlay.id);
                    });
                }
            } else {
                debugLog('[DEEP DEBUG NAV] navigateToPrevious - No span-overlays container found');
            }
        }

        // Use the correct endpoint and payload for navigation
        const response = await fetch('/annotate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                action: 'prev_instance',
                instance_id: currentInstance?.id
            })
        });

        if (response.ok) {
            debugLog('[DEEP DEBUG NAV] navigateToPrevious - Navigation successful, reloading page');

            if (window.spanManager && typeof window.spanManager.onInstanceChange === 'function') {
                window.spanManager.onInstanceChange(currentInstance?.id);
            }

            logDeepDebug('navigateToPrevious_success', {
                currentInstanceId: currentInstance?.id,
                overlayCount: getCurrentOverlayCount()
            });

            // Add a small delay to ensure span manager operations complete before reload
            setTimeout(() => {
                window.location.reload();
            }, 100);
        } else {
            console.error('[DEEP DEBUG NAV] navigateToPrevious - Navigation failed:', response.status);
            setLoading(false);
        }
    } catch (error) {
        console.error('[DEEP DEBUG NAV] navigateToPrevious - Navigation error:', error);
        setLoading(false);
    }
}

async function navigateToNext() {
    debugLog('[DEEP DEBUG NAV] navigateToNext - ENTRY POINT');
    deepDebugState.navigationCalls++;

    logDeepDebug('navigateToNext_start', {
        currentInstanceId: currentInstance?.id,
        overlayCount: getCurrentOverlayCount()
    });

    if (isLoading) {
        debugLog('[DEEP DEBUG NAV] navigateToNext - Navigation blocked, still loading');
        return;
    }

    setLoading(true);
    debugLog('[DEEP DEBUG NAV] navigateToNext - Loading set to true');

    try {
        // Save annotations before navigating away
        debugLog('[DEEP DEBUG NAV] navigateToNext - Saving annotations before navigation');
        await saveAnnotations();

        // FIREFOX FIX: Force overlay cleanup before navigation
        const isFirefox = navigator.userAgent.toLowerCase().includes('firefox');
        debugLog('[DEEP DEBUG NAV] navigateToNext - Is Firefox:', isFirefox);

        if (isFirefox) {
            debugLog('[DEEP DEBUG NAV] Firefox detected - forcing overlay cleanup before navigation');
            const spanOverlays = document.getElementById('span-overlays');
            if (spanOverlays) {
                const beforeCount = spanOverlays.children.length;
                debugLog('[DEEP DEBUG NAV] navigateToNext - Before Firefox cleanup:', beforeCount, 'overlays');

                // Remove all overlays individually
                while (spanOverlays.firstChild) {
                    const child = spanOverlays.firstChild;
                    debugLog('[DEEP DEBUG NAV] navigateToNext - Removing overlay child:', child.className, child.id);

                    // Track overlay removal for debugging
                    if (typeof trackOverlayRemoval === 'function') {
                        trackOverlayRemoval(child, 'navigateToNext Firefox cleanup');
                    }

                    spanOverlays.removeChild(child);
                }

                // Force reflow
                spanOverlays.offsetHeight;
                const afterCount = spanOverlays.children.length;
                debugLog('[DEEP DEBUG NAV] navigateToNext - After Firefox cleanup:', afterCount, 'overlays');

                // Double-check cleanup
                const remainingOverlays = document.querySelectorAll('.span-overlay');
                debugLog('[DEEP DEBUG NAV] navigateToNext - Remaining overlays via querySelectorAll:', remainingOverlays.length);

                if (remainingOverlays.length > 0) {
                    debugLog('[DEEP DEBUG NAV] navigateToNext - WARNING: Overlays still exist after cleanup!');
                    remainingOverlays.forEach((overlay, index) => {
                        debugLog(`[DEEP DEBUG NAV] navigateToNext - Remaining overlay ${index}:`, overlay.className, overlay.id);
                    });
                }
            } else {
                debugLog('[DEEP DEBUG NAV] navigateToNext - No span-overlays container found');
            }
        }

        // Use the correct endpoint and payload for navigation
        const response = await fetch('/annotate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                action: 'next_instance',
                instance_id: currentInstance?.id
            })
        });

        if (response.ok) {
            debugLog('[DEEP DEBUG NAV] navigateToNext - Navigation successful, reloading page');

            if (window.spanManager && typeof window.spanManager.onInstanceChange === 'function') {
                window.spanManager.onInstanceChange(currentInstance?.id);
            }

            logDeepDebug('navigateToNext_success', {
                currentInstanceId: currentInstance?.id,
                overlayCount: getCurrentOverlayCount()
            });

            // Add a small delay to ensure span manager operations complete before reload
            setTimeout(() => {
                window.location.reload();
            }, 100);
        } else {
            console.error('[DEEP DEBUG NAV] navigateToNext - Navigation failed:', response.status);
            setLoading(false);
        }
    } catch (error) {
        console.error('[DEEP DEBUG NAV] navigateToNext - Navigation error:', error);
        setLoading(false);
    }
}

async function navigateToInstance(instanceIndex) {
    if (isLoading) return;

    try {
        setLoading(true);

        // DEBUG: Track overlays before navigation
        debugTrackOverlays('BEFORE_GO_TO_NAVIGATION', currentInstance?.id);

        // FIREFOX FIX: Force overlay cleanup before navigation
        const isFirefox = navigator.userAgent.toLowerCase().includes('firefox');
        debugLog('🔍 [DEBUG] navigateToInstance() - Is Firefox:', isFirefox);

        if (isFirefox) {
            debugLog('🔍 [DEBUG] Firefox detected - forcing overlay cleanup before navigation');
            const spanOverlays = document.getElementById('span-overlays');
            if (spanOverlays) {
                debugLog('🔍 [DEBUG] navigateToInstance() - Before Firefox cleanup:', spanOverlays.children.length, 'overlays');

                // Remove all overlays individually
                while (spanOverlays.firstChild) {
                    const child = spanOverlays.firstChild;
                    debugLog('🔍 [DEBUG] navigateToInstance() - Removing overlay child:', child.className, child.id);

                    // Track overlay removal for debugging
                    if (typeof trackOverlayRemoval === 'function') {
                        trackOverlayRemoval(child, 'navigateToInstance Firefox cleanup');
                    }

                    spanOverlays.removeChild(child);
                }

                // Force reflow
                spanOverlays.offsetHeight;
                debugLog('🔍 [DEBUG] navigateToInstance() - After Firefox cleanup:', spanOverlays.children.length, 'overlays');
            } else {
                debugLog('🔍 [DEBUG] navigateToInstance() - No span-overlays container found');
            }
        }

        const headers = {
            'Content-Type': 'application/json',
        };
        if (window.config.api_key) {
            headers['X-API-Key'] = window.config.api_key;
        }
        const response = await fetch('/annotate', {
            method: 'POST',
            headers: headers,
            body: JSON.stringify({
                action: 'go_to',
                go_to: instanceIndex
            })
        });

        if (response.ok) {
            debugLog('🔍 [DEBUG] navigateToInstance() - Navigation successful, about to reload page');
            // DEBUG: Clear overlays before reload
            const spanOverlays = document.getElementById('span-overlays');
            if (spanOverlays) {
                debugLog('🔍 [DEBUG] navigateToInstance() - Before clearing overlays:', spanOverlays.children.length, 'overlays');
                debugLog('🔍 [DEBUG] navigateToInstance() - Clearing span overlays before page reload');
                spanOverlays.innerHTML = '';
                debugLog('🔍 [DEBUG] navigateToInstance() - After clearing overlays:', spanOverlays.children.length, 'overlays');
                debugVerifyOverlayCleanup();
            } else {
                debugLog('🔍 [DEBUG] navigateToInstance() - No span-overlays container found');
            }
            // Reload the page to get the new instance data from the server
            window.location.reload();
        } else {
            throw new Error('Failed to navigate to instance');
        }
    } catch (error) {
        console.error('Error navigating to instance:', error);
        showError(true, error.message);
    } finally {
        setLoading(false);
    }
}

function validateRequiredFields() {
    // Check all inputs with validation="required"
    const requiredInputs = document.querySelectorAll('input[validation="required"]');
    let allRequiredFilled = true;

    // Group inputs by their name (for radio buttons) or individual inputs
    const inputGroups = {};
    requiredInputs.forEach(input => {
        if (input.type === 'radio') {
            // For radio buttons, check if any in the group is selected
            const name = input.name;
            if (!inputGroups[name]) {
                inputGroups[name] = [];
            }
            inputGroups[name].push(input);
        } else {
            // For other inputs, check individually
            if (!input.value || input.value.trim() === '') {
                allRequiredFilled = false;
            }
        }
    });

    // Check radio button groups
    for (const [name, inputs] of Object.entries(inputGroups)) {
        const anySelected = inputs.some(input => input.checked);
        if (!anySelected) {
            allRequiredFilled = false;
            break;
        }
    }

    // Update Next button state
    const nextBtn = document.getElementById('next-btn');
    if (nextBtn) {
        nextBtn.disabled = !allRequiredFilled;
    }

    return allRequiredFilled;
}

function setLoading(loading) {
    isLoading = loading;
    const loadingState = document.getElementById('loading-state');
    const mainContent = document.getElementById('main-content');
    const prevBtn = document.getElementById('prev-btn');
    const nextBtn = document.getElementById('next-btn');

    if (loading) {
        loadingState.style.display = 'block';
        mainContent.style.display = 'none';
        prevBtn.disabled = true;
        nextBtn.disabled = true;
    } else {
        loadingState.style.display = 'none';
        mainContent.style.display = 'block';
        prevBtn.disabled = false;
        // Don't enable next button here - let validateRequiredFields handle it
        validateRequiredFields();
    }
}

function showError(show, message = '') {
    const errorState = document.getElementById('error-state');
    const errorMessage = document.getElementById('error-message-text');
    const mainContent = document.getElementById('main-content');

    if (show) {
        errorState.style.display = 'block';
        mainContent.style.display = 'none';
        errorMessage.textContent = message;
    } else {
        errorState.style.display = 'none';
        mainContent.style.display = 'block';
    }
}

// Utility functions for annotation handling
function updateAnnotation(schema, label, value) {
    if (!currentAnnotations[schema]) {
        currentAnnotations[schema] = {};
    }
    currentAnnotations[schema][label] = value;
}

// Function to handle "None" option in multiselect annotations
function whetherNone(checkbox) {
    // This function is used to uncheck all the other labels when "None" is checked
    // and vice versa
    var x = document.getElementsByClassName(checkbox.className);
    var i;
    for (i = 0; i < x.length; i++) {
        if (checkbox.value == "None" && x[i].value != "None") x[i].checked = false;
        if (checkbox.value != "None" && x[i].value == "None") x[i].checked = false;
    }
    // Also trigger the input change handler for the current checkbox
    handleInputChange(checkbox);
}

// Input event handling functions
function setupInputEventListeners() {
    // Set up event listeners for all annotation inputs
    const inputs = document.querySelectorAll('.annotation-input');

    inputs.forEach(input => {
        const inputType = input.type;
        const tagName = input.tagName.toLowerCase();

        if (inputType === 'text' || tagName === 'textarea') {
            // Text inputs and textareas - debounced saving
            let timer;
            input.addEventListener('input', function (event) {
                clearTimeout(timer);
                timer = setTimeout(() => {
                    handleInputChange(event.target);
                }, 1000);
            });
            debugLog(`Set up event listener for ${tagName} element:`, input.id);
        } else if (inputType === 'radio' || inputType === 'checkbox') {
            // Radio/checkbox inputs - immediate saving
            input.addEventListener('change', function (event) {
                handleInputChange(event.target);
            });
        } else if (inputType === 'range') {
            // Slider inputs - immediate saving with value display
            input.addEventListener('input', function (event) {
                const valueDisplay = document.getElementById(`${input.name}-value`);
                if (valueDisplay) {
                    valueDisplay.textContent = event.target.value;
                }
                handleInputChange(event.target);
            });
        } else if (tagName === 'select') {
            // Select inputs - immediate saving
            input.addEventListener('change', function (event) {
                handleInputChange(event.target);
            });
        } else if (inputType === 'number') {
            // Number inputs - debounced saving
            let timer;
            input.addEventListener('input', function (event) {
                clearTimeout(timer);
                timer = setTimeout(() => {
                    handleInputChange(event.target);
                }, 1000);
            });
        }
    });
}

function handleInputChange(element) {
    const schema = element.getAttribute('schema');
    const labelName = element.getAttribute('label_name');
    const inputType = element.type;
    const tagName = element.tagName.toLowerCase();

    debugLog(`handleInputChange called for ${tagName} element:`, element.id, 'schema:', schema, 'label:', labelName);

    if (!schema || !labelName) {
        console.warn('Missing schema or label_name for input:', element);
        return;
    }

    // Validate required fields after input change
    validateRequiredFields();

    let value;

    if (inputType === 'radio') {
        // For radio buttons, only save if checked
        if (element.checked) {
            value = element.value;
        } else {
            return; // Don't save unchecked radio buttons
        }
    } else if (inputType === 'checkbox') {
        // For checkboxes, save the checked state
        if (element.checked) {
            value = element.value;
        } else {
            // For unchecked checkboxes, remove the annotation or set to false
            if (currentAnnotations[schema] && currentAnnotations[schema][labelName]) {
                delete currentAnnotations[schema][labelName];
                // If the schema is empty, remove it too
                if (Object.keys(currentAnnotations[schema]).length === 0) {
                    delete currentAnnotations[schema];
                }
            }
            debugLog(`Removed annotation: ${schema}.${labelName}`);

            // Auto-save the removal
            clearTimeout(textSaveTimer);
            textSaveTimer = setTimeout(() => {
                saveAnnotations();
            }, 500);
            return;
        }
    } else {
        // For text inputs, save the value
        value = element.value;
    }

    // Update the current annotations
    updateAnnotation(schema, labelName, value);
    debugLog(`Updated annotation: ${schema}.${labelName} = ${value}`);

    // Auto-save
    clearTimeout(textSaveTimer);
    textSaveTimer = setTimeout(() => {
        saveAnnotations();
    }, 500);
}

function populateInputValues() {
    if (!currentAnnotations || !userState) return;

    debugLog('🔍 Populating input values with annotations:', currentAnnotations);

    // Populate text inputs and textareas
    const textInputs = document.querySelectorAll('input[type="text"], textarea.annotation-input');
    debugLog('🔍 Found text inputs and textareas:', textInputs.length);

    textInputs.forEach(input => {
        const schema = input.getAttribute('schema');
        const labelName = input.getAttribute('label_name');
        debugLog('🔍 Checking input:', input.id, 'schema:', schema, 'label:', labelName);

        if (schema && labelName && currentAnnotations[schema] && currentAnnotations[schema][labelName]) {
            input.value = currentAnnotations[schema][labelName];
            debugLog(`✅ Populated ${input.tagName} ${input.id} with value:`, currentAnnotations[schema][labelName]);
        } else {
            debugLog(`❌ Could not populate ${input.tagName} ${input.id}:`, {
                hasSchema: !!schema,
                hasLabelName: !!labelName,
                hasSchemaInAnnotations: !!(currentAnnotations[schema]),
                hasLabelInSchema: !!(currentAnnotations[schema] && currentAnnotations[schema][labelName])
            });
        }
    });

    // Populate radio buttons
    const radioInputs = document.querySelectorAll('input[type="radio"]');
    radioInputs.forEach(input => {
        const schema = input.getAttribute('schema');
        const labelName = input.getAttribute('label_name');

        if (schema && labelName && currentAnnotations[schema] && currentAnnotations[schema][labelName]) {
            input.checked = (currentAnnotations[schema][labelName] === input.value);
            debugLog(`Populated radio ${input.id}: ${input.checked ? 'checked' : 'unchecked'}`);
        }
    });

    // Populate checkboxes
    const checkboxInputs = document.querySelectorAll('input[type="checkbox"]');
    checkboxInputs.forEach(input => {
        const schema = input.getAttribute('schema');
        const labelName = input.getAttribute('label_name');

        if (schema && labelName && currentAnnotations[schema]) {
            // For checkboxes, check if the value exists in the annotations
            const hasAnnotation = currentAnnotations[schema][labelName] === input.value;
            input.checked = hasAnnotation;
            debugLog(`Populated checkbox ${input.id}: ${hasAnnotation ? 'checked' : 'unchecked'}`);
        }
    });

    // Populate sliders
    const sliderInputs = document.querySelectorAll('input[type="range"]');
    sliderInputs.forEach(input => {
        const schema = input.getAttribute('schema');
        const labelName = input.getAttribute('label_name');

        if (schema && labelName && currentAnnotations[schema] && currentAnnotations[schema][labelName]) {
            input.value = currentAnnotations[schema][labelName];
            const valueDisplay = document.getElementById(`${input.name}-value`);
            if (valueDisplay) {
                valueDisplay.textContent = currentAnnotations[schema][labelName];
            }
            debugLog(`Populated slider ${input.id} with value:`, currentAnnotations[schema][labelName]);
        }
    });

    // Populate select dropdowns
    const selectInputs = document.querySelectorAll('select.annotation-input');
    selectInputs.forEach(input => {
        const schema = input.getAttribute('schema');
        const labelName = input.getAttribute('label_name');

        if (schema && labelName && currentAnnotations[schema] && currentAnnotations[schema][labelName]) {
            input.value = currentAnnotations[schema][labelName];
            debugLog(`Populated select ${input.id} with value:`, currentAnnotations[schema][labelName]);
        }
    });

    // Populate number inputs
    const numberInputs = document.querySelectorAll('input[type="number"].annotation-input');
    numberInputs.forEach(input => {
        const schema = input.getAttribute('schema');
        const labelName = input.getAttribute('label_name');

        if (schema && labelName && currentAnnotations[schema] && currentAnnotations[schema][labelName]) {
            input.value = currentAnnotations[schema][labelName];
            debugLog(`Populated number ${input.id} with value:`, currentAnnotations[schema][labelName]);
        }
    });

    validateRequiredFields();
}

// Span annotation functions
function onlyOne(checkbox) {
    debugLog('🔍 [DEBUG] onlyOne() called with checkbox:', {
        id: checkbox.id,
        name: checkbox.name,
        value: checkbox.value,
        checked: checkbox.checked,
        className: checkbox.className
    });

    var x = document.getElementsByClassName(checkbox.className);
    debugLog('🔍 [DEBUG] onlyOne() - Found elements with same class:', x.length);

    var i;
    for (i = 0; i < x.length; i++) {
        debugLog('🔍 [DEBUG] onlyOne() - Processing element:', {
            id: x[i].id,
            value: x[i].value,
            checked: x[i].checked,
            willUncheck: x[i].value != checkbox.value
        });

        if (x[i].value != checkbox.value) {
            debugLog('🔍 [DEBUG] onlyOne() - Unchecking element:', x[i].id);
            x[i].checked = false;
        }
    }
    // Ensure the clicked checkbox is checked
    debugLog('🔍 [DEBUG] onlyOne() - Setting clicked checkbox to checked:', checkbox.id);
    checkbox.setAttribute('data-just-checked', 'true'); // Flag to prevent change event interference
    checkbox.checked = true;

    // Remove the flag after a short delay in case the change event doesn't fire
    setTimeout(() => {
        if (checkbox.hasAttribute('data-just-checked')) {
            debugLog('🔍 [DEBUG] onlyOne() - Removing data-just-checked flag after timeout');
            checkbox.removeAttribute('data-just-checked');
        }
    }, 100);
}

function extractSpanAnnotationsFromDOM() {
    /*
     * Extract span annotations from the DOM using the overlay system.
     *
     * Returns:
     *     Array of span annotation objects with schema, name, start, end, title, value
     */
    debugLog('[DEBUG] extractSpanAnnotationsFromDOM called');

    const overlays = document.querySelectorAll('.span-overlay');
    const spanAnnotations = [];

    for (const overlay of overlays) {
        const schema = overlay.getAttribute('data-schema');
        const label = overlay.getAttribute('data-label');
        const start = parseInt(overlay.getAttribute('data-start'));
        const end = parseInt(overlay.getAttribute('data-end'));
        const title = overlay.querySelector('.span-label')?.textContent?.trim() || label;

        // Get the text value by finding the covered segments
        const segments = document.querySelectorAll('.text-segment');
        let coveredText = '';
        for (const segment of segments) {
            const segStart = parseInt(segment.getAttribute('data-start'));
            const segEnd = parseInt(segment.getAttribute('data-end'));
            const spanIds = segment.getAttribute('data-span-ids')?.split(',') || [];

            // Check if this segment is covered by this overlay
            if (overlay.getAttribute('data-annotation-id') &&
                spanIds.includes(overlay.getAttribute('data-annotation-id'))) {
                coveredText += segment.textContent;
            }
        }

        spanAnnotations.push({
            schema: schema,
            name: label,
            start: start,
            end: end,
            title: title,
            value: coveredText
        });
    }

    debugLog('[DEBUG] extractSpanAnnotationsFromDOM: found', spanAnnotations.length, 'spans:', spanAnnotations);
    return spanAnnotations;
}

function alignSpanOverlays() {
    /*
     * Align each .span-overlay to the union of its covered .text-segment spans.
     * This function positions overlays to match the actual text segments in the DOM.
     */
    debugLog('[DEBUG] alignSpanOverlays called');

    const overlays = document.querySelectorAll('.span-overlay');
    const segments = Array.from(document.querySelectorAll('.text-segment'));
    const container = document.querySelector('.span-annotation-container');

    if (!container) {
        console.warn('[DEBUG] alignSpanOverlays: No .span-annotation-container found');
        return;
    }

    for (const overlay of overlays) {
        const annotationId = overlay.getAttribute('data-annotation-id');
        if (!annotationId) {
            console.warn('[DEBUG] alignSpanOverlays: Overlay missing data-annotation-id');
            continue;
        }

        // Find all segments covered by this overlay
        const coveredSegments = segments.filter(segment => {
            const spanIds = segment.getAttribute('data-span-ids')?.split(',') || [];
            return spanIds.includes(annotationId);
        });

        if (coveredSegments.length === 0) {
            console.warn('[DEBUG] alignSpanOverlays: No segments found for overlay', annotationId);
            continue;
        }

        // Calculate the bounding rectangle of all covered segments
        let minLeft = Infinity;
        let maxRight = -Infinity;
        let minTop = Infinity;
        let maxBottom = -Infinity;

        for (const segment of coveredSegments) {
            const rect = segment.getBoundingClientRect();
            const containerRect = container.getBoundingClientRect();

            const relativeLeft = rect.left - containerRect.left;
            const relativeRight = rect.right - containerRect.left;
            const relativeTop = rect.top - containerRect.top;
            const relativeBottom = rect.bottom - containerRect.top;

            minLeft = Math.min(minLeft, relativeLeft);
            maxRight = Math.max(maxRight, relativeRight);
            minTop = Math.min(minTop, relativeTop);
            maxBottom = Math.max(maxBottom, relativeBottom);
        }

        // Position the overlay to cover all segments
        overlay.style.left = minLeft + 'px';
        overlay.style.top = minTop + 'px';
        overlay.style.width = (maxRight - minLeft) + 'px';
        overlay.style.height = (maxBottom - minTop) + 'px';
        overlay.style.backgroundColor = 'rgba(255, 230, 230, 0.3)';
        overlay.style.border = '1px solid rgba(255, 230, 230, 0.8)';

        debugLog('[DEBUG] alignSpanOverlays: Positioned overlay', annotationId, 'at',
            minLeft, minTop, maxRight - minLeft, maxBottom - minTop);
    }
}

// Robust selection mapping for overlay system
function getSelectionIndicesOverlay() {
    /*
     * Get the start and end indices of the current text selection using the overlay approach.
     *
     * This function uses the unified text positioning approach to ensure
     * consistent offsets between frontend and backend.
     *
     * Returns:
     *     Object with start and end indices in the original text
     */
    debugLog('[DEBUG] getSelectionIndicesOverlay called');

    var selection = window.getSelection();
    if (!selection.rangeCount) {
        debugLog('[DEBUG] getSelectionIndicesOverlay: No selection range');
        return { start: 0, end: 0 };
    }

    var range = selection.getRangeAt(0);
    var container = document.getElementById('text-content');

    if (!container) {
        debugLog('[DEBUG] getSelectionIndicesOverlay: No text-content container found');
        return { start: 0, end: 0 };
    }

    // Use the unified text positioning approach
    if (typeof calculateTextOffsetsFromSelection === 'function') {
        const offsets = calculateTextOffsetsFromSelection(container, range);
        debugLog('[DEBUG] getSelectionIndicesOverlay: Using unified approach, offsets:', offsets);
        return offsets;
    }

    // Fallback to the original approach if unified function is not available
    debugLog('[DEBUG] getSelectionIndicesOverlay: Using fallback approach');
    return getOriginalTextOffsetsOverlay(container, range);
}

// Use overlay system for all span operations
function changeSpanLabel(checkbox, schema, spanLabel, spanTitle, spanColor) {
    /*
     * Set up span annotation mode using the new span manager.
     *
     * Args:
     *     checkbox: The checkbox element that was clicked
     *     schema: The annotation schema
     *     spanLabel: The span label
     *     spanTitle: The span title
     *     spanColor: The span color
     */
    debugLog('[DEBUG] changeSpanLabel called:', { schema, spanLabel, spanTitle, spanColor, checked: checkbox.checked });

    // Use the new span manager if available
    if (window.spanManager && window.spanManager.isInitialized) {
        debugLog('[DEBUG] changeSpanLabel: Using new span manager');

        // Select the label and schema in the span manager
        window.spanManager.selectLabel(spanLabel, schema);

        // Set up text selection handler
        const textContainer = document.getElementById('instance-text');
        if (textContainer) {
            // Create bound handlers once and store them for proper cleanup
            if (!boundEventHandlers.spanManagerMouseUp) {
                boundEventHandlers.spanManagerMouseUp = window.spanManager.handleTextSelection.bind(window.spanManager);
                boundEventHandlers.spanManagerKeyUp = window.spanManager.handleTextSelection.bind(window.spanManager);
            }

            // Remove existing handlers using stored references
            textContainer.removeEventListener('mouseup', boundEventHandlers.spanManagerMouseUp);
            textContainer.removeEventListener('keyup', boundEventHandlers.spanManagerKeyUp);

            // Add new handlers only when checkbox is checked
            if (checkbox.checked) {
                textContainer.addEventListener('mouseup', boundEventHandlers.spanManagerMouseUp);
                textContainer.addEventListener('keyup', boundEventHandlers.spanManagerKeyUp);
                debugLog('[DEBUG] changeSpanLabel: Text selection handlers added for span manager');
            }
        }
    } else {
        // Defer to new manager once ready; avoid legacy overlay system to prevent conflicts
        debugLog('[DEBUG] changeSpanLabel: Span manager not ready; deferring selection to manager');
        const waitAndSelect = () => {
            if (window.spanManager && window.spanManager.isInitialized) {
                window.spanManager.selectLabel(spanLabel, schema);
                return true;
            }
            return false;
        };
        if (!waitAndSelect()) {
            let retries = 0;
            const timer = setInterval(() => {
                if (waitAndSelect() || ++retries > 20) clearInterval(timer);
            }, 100);
        }
    }

    // Add debugging to track checkbox state after function execution
    setTimeout(() => {
        debugLog('[DEBUG] changeSpanLabel: Checkbox state after execution:', {
            id: checkbox.id,
            checked: checkbox.checked,
            name: checkbox.name,
            value: checkbox.value
        });
    }, 0);
}

function surroundSelection(schema, labelName, title, selectionColor) {
    // Only use overlay system
    surroundSelectionOverlay(schema, labelName, title, selectionColor);
}

function restoreSpanAnnotationsFromHTML() {
    // Only use overlay system
    restoreSpanAnnotationsFromHTMLOverlay();
}

// LEGACY OVERLAY FUNCTIONS - DEPRECATED
// These functions are kept for backward compatibility but are no longer used
// The new boundary-based rendering system handles everything server-side

// function getSelectionIndicesOverlay() {
//     /*
//      * Get selection indices for the overlay-based approach.
//      *
//      * This function works with the original text element and maps
//      * DOM selection to original text offsets.
//      *
//      * Returns:
//      *     Object with start and end indices in the original text
//      */
//     debugLog('[DEBUG] getSelectionIndicesOverlay called');

//     // Get the user selection
//     var selection = window.getSelection();

//     if (selection.rangeCount === 0) {
//         debugLog('[DEBUG] getSelectionIndicesOverlay: No selection');
//         return { start: -1, end: -1 }; // No selection
//     }

//     // Get the range object representing the selected portion
//     var range = selection.getRangeAt(0);

//     debugLog('[DEBUG] getSelectionIndicesOverlay: Selection details:', {
//         selectionText: selection.toString(),
//         selectionLength: selection.toString().length,
//         rangeStartContainer: range.startContainer,
//         rangeStartOffset: range.startOffset,
//         rangeEndContainer: range.endContainer,
//         rangeEndOffset: range.endOffset,
//         commonAncestor: range.commonAncestorContainer
//     });

//     // Find the original text element within the span annotation container
//     var originalTextElement = $(range.commonAncestorContainer).closest('.original-text')[0];

//     if (!originalTextElement) {
//         debugLog('[DEBUG] getSelectionIndicesOverlay: Not within .original-text');
//         return { start: -2, end: -2 }; // Not within the original text
//     }

//     // Get the original text from the data attribute for comparison
//     var originalTextFromData = originalTextElement.getAttribute('data-original-text');
//     debugLog('[DEBUG] getSelectionIndicesOverlay: Original text from data attribute:', originalTextFromData);
//     debugLog('[DEBUG] getSelectionIndicesOverlay: Original text length from data:', originalTextFromData ? originalTextFromData.length : 0);

//     // For the overlay approach, we can use a simpler offset calculation
//     // since the original text is unchanged and we can directly map DOM positions
//     var result = getOriginalTextOffsetsOverlay(originalTextElement, range);

//     debugLog('[DEBUG] getSelectionIndicesOverlay: Final result:', result);

//     return result;
// }

function getOriginalTextOffsetsOverlay(container, range) {
    /*
     * Get original text offsets for the overlay approach.
     *
     * This function uses the unified text positioning approach to ensure
     * consistent offsets between frontend and backend.
     *
     * Args:
     *     container: The original text container element
     *     range: The DOM range object
     *
     * Returns:
     *     Object with start and end offsets in the original text
     */
    debugLog('[DEBUG] getOriginalTextOffsetsOverlay called');

    // Use the unified text positioning approach
    if (typeof calculateTextOffsetsFromSelection === 'function') {
        const offsets = calculateTextOffsetsFromSelection(container, range);
        debugLog('[DEBUG] getOriginalTextOffsetsOverlay: Using unified approach, offsets:', offsets);
        return offsets;
    }

    // Fallback to the original approach if unified function is not available
    debugLog('[DEBUG] getOriginalTextOffsetsOverlay: Using fallback approach');

    // Get the original text from the data attribute (this is the clean text without HTML markup)
    var originalText = container.getAttribute('data-original-text');
    if (!originalText) {
        debugLog('[DEBUG] getOriginalTextOffsetsOverlay: WARNING - no data-original-text attribute found, falling back to DOM text');
        originalText = container.textContent || container.innerText;
    }
    debugLog('[DEBUG] getOriginalTextOffsetsOverlay: originalText from data attribute:', originalText);
    debugLog('[DEBUG] getOriginalTextOffsetsOverlay: originalText length:', originalText.length);

    // Get the selected text
    var selectedText = window.getSelection().toString();
    debugLog('[DEBUG] getOriginalTextOffsetsOverlay: selectedText:', selectedText);
    debugLog('[DEBUG] getOriginalTextOffsetsOverlay: selectedText length:', selectedText.length);

    // Find the selection in the original text
    var startIndex = originalText.indexOf(selectedText);
    var endIndex = startIndex + selectedText.length;

    debugLog('[DEBUG] getOriginalTextOffsetsOverlay: mapped indices:', { startIndex, endIndex });

    // Verify the indices by extracting text
    if (startIndex !== -1) {
        var extractedText = originalText.substring(startIndex, endIndex);
        debugLog('[DEBUG] getOriginalTextOffsetsOverlay: extracted text using indices:', extractedText);
        debugLog('[DEBUG] getOriginalTextOffsetsOverlay: extracted text matches selected text:', extractedText === selectedText);
    } else {
        debugLog('[DEBUG] getOriginalTextOffsetsOverlay: WARNING - selected text not found in original text!');
    }

    return { start: startIndex, end: endIndex };
}

// Update the existing surroundSelection function to work with overlays
function surroundSelectionOverlay(schema, labelName, title, selectionColor) {
    /*
     * Create a span annotation using the overlay approach.
     *
     * Args:
     *     schema: The annotation schema
     *     labelName: The label name
     *     title: The annotation title
     *     selectionColor: The color for the annotation
     */
    debugLog('[DEBUG] surroundSelectionOverlay called:', { schema, labelName, title, selectionColor });

    // Check that this wasn't a spurious click or the click for the delete button which
    // also seems to trigger this selection event
    if (window.getSelection().rangeCount == 0) {
        debugLog('[DEBUG] surroundSelectionOverlay: No selection range found');
        return;
    }
    var range = window.getSelection().getRangeAt(0);

    if (range.startOffset == range.endOffset) {
        debugLog('[DEBUG] surroundSelectionOverlay: Selection start and end offsets are the same');
        return;
    }

    // Get the instance id
    var instance_id = document.getElementById("instance_id").value;
    debugLog('[DEBUG] surroundSelectionOverlay: Instance ID:', instance_id);

    if (window.getSelection) {
        var sel = window.getSelection();

        // Check that we're labeling something in the original text that
        // we want to annotate
        if (!sel.anchorNode.parentElement) {
            debugLog('[DEBUG] surroundSelectionOverlay: No anchor node parent element');
            return;
        }

        // Otherwise, we're going to be adding a new span annotation, if
        // the user has selected some non-empty part of the text
        if (sel.rangeCount && sel.toString().trim().length > 0) {
            debugLog('[DEBUG] surroundSelectionOverlay: Valid selection found, creating span');

            // Get the selection text as a string
            var selText = window.getSelection().toString().trim();
            debugLog('[DEBUG] surroundSelectionOverlay: Selected text:', selText);

            // Get the offsets for the server using the overlay approach
            var startEnd = getSelectionIndicesOverlay();
            debugLog('[DEBUG] surroundSelectionOverlay: Selection indices:', startEnd);

            // Package this all up in a post request to the server's updateinstance endpoint
            var post_req = {
                type: "span",
                schema: schema,
                state: [
                    {
                        name: labelName,
                        start: startEnd["start"],
                        end: startEnd["end"],
                        title: title,
                        value: selText
                    }
                ],
                instance_id: instance_id
            };

            debugLog('[DEBUG] surroundSelectionOverlay: Sending span annotation request:', post_req);

            // Send the request
            fetch('/updateinstance', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(post_req)
            })
            .then(response => {
                if (response.ok) {
                    debugLog('[DEBUG] surroundSelectionOverlay: Span annotation created successfully');
                    // Reload the page to show the new annotation
                    location.reload();
                } else {
                    console.error('[DEBUG] surroundSelectionOverlay: Failed to create span annotation:', response.status);
                    return response.json().then(error => {
                        console.error('[DEBUG] surroundSelectionOverlay: Error details:', error);
                    });
                }
            })
            .catch(error => {
                console.error('[DEBUG] surroundSelectionOverlay: Network error:', error);
            });

            // Clear the current selection
            sel.empty();
            debugLog('[DEBUG] surroundSelectionOverlay: Span creation request sent, page will reload');
        } else {
            debugLog('[DEBUG] surroundSelectionOverlay: No valid selection found');
        }
    }
}

// Update the existing changeSpanLabel function to use the overlay approach
function changeSpanLabelOverlay(checkbox, schema, spanLabel, spanTitle, spanColor) {
    /*
     * Set up span annotation mode using the overlay approach.
     *
     * Args:
     *     checkbox: The checkbox element that was clicked
     *     schema: The annotation schema
     *     spanLabel: The span label
     *     spanTitle: The span title
     *     spanColor: The span color
     */
    debugLog('[DEBUG] changeSpanLabelOverlay called:', { schema, spanLabel, spanTitle, spanColor, checked: checkbox.checked });

    // Listen for when the user has highlighted some text (only when the label is checked)
    document.onmouseup = function (e) {
        var senderElement = e.target;
        // Avoid the case where the user clicks the delete button
        if (senderElement.getAttribute("class") == "span-close") {
            e.stopPropagation();
            return true;
        }
        if (checkbox.checked) {
            debugLog('[DEBUG] changeSpanLabelOverlay: Mouse up event - checkbox is checked, calling surroundSelectionOverlay');
            surroundSelectionOverlay(schema, spanLabel, spanTitle, spanColor);
        } else {
            debugLog('[DEBUG] changeSpanLabelOverlay: Mouse up event - checkbox is not checked');
        }
    };
}

// Update the restoreSpanAnnotationsFromHTML function to work with overlays
function restoreSpanAnnotationsFromHTMLOverlay() {
    /*
     * Extract span annotations from the overlay-based HTML structure.
     *
     * This function parses the overlay elements to reconstruct the span annotations.
     */
    const container = document.querySelector('.span-annotation-container');
    if (!container) return;

    const overlayElements = container.querySelectorAll('.span-overlay');
    const found = [];

    overlayElements.forEach(overlay => {
        const schema = overlay.getAttribute('data-schema');
        const name = overlay.getAttribute('data-label');
        const start = parseInt(overlay.getAttribute('data-start'));
        const end = parseInt(overlay.getAttribute('data-end'));
        const annotationId = overlay.getAttribute('data-annotation-id');

        found.push({
            schema,
            name,
            title: name, // Use name as title for now
            start,
            end,
            id: annotationId,
            value: '' // Value is not stored in overlay, would need to extract from original text
        });
    });

    currentSpanAnnotations = found;
    debugLog('[DEBUG] restoreSpanAnnotationsFromHTMLOverlay: found', found.length, 'spans:', found);
}

// ============================================================================
// ROBUST SPAN ANNOTATION FUNCTIONS (Based on potato-span-fix approach)
// ============================================================================

// Global variables for robust span annotation
let spanColors = {};
let originalText = '';
let spanAnnotations = [];

/**
 * Initialize robust span annotation system
 */
function initializeRobustSpanAnnotation() {
    debugLog('[ROBUST SPAN] Initializing robust span annotation system');

    // Load span colors from config
    loadSpanColors();

    // Set up text selection handlers
    setupRobustSpanSelection();

    // Render existing spans
    renderSpansRobust();
}

/**
 * Load span colors from the UI configuration
 */
async function loadSpanColors() {
    try {
        // Get colors from the current user state or config
        if (userState && userState.config && userState.config.ui && userState.config.ui.spans) {
            const configColors = userState.config.ui.spans.span_colors;
            // Flatten the color structure
            spanColors = {};
            for (const schema in configColors) {
                for (const label in configColors[schema]) {
                    spanColors[label] = configColors[schema][label];
                }
            }
        } else {
            // Fallback colors
            spanColors = {
                'happy': '(255, 230, 230)',
                'sad': '(230, 243, 255)',
                'angry': '(255, 230, 204)',
                'surprised': '(230, 255, 230)',
                'neutral': '(240, 240, 240)'
            };
        }
        debugLog('[ROBUST SPAN] Loaded colors:', spanColors);
    } catch (error) {
        console.error('[ROBUST SPAN] Error loading colors:', error);
    }
}

/**
 * Set up text selection handlers for robust span annotation
 */
function setupRobustSpanSelection() {
    const textContainer = document.getElementById('instance-text');
    if (!textContainer) {
        console.warn('[ROBUST SPAN] No text container found');
        return;
    }

    // Remove existing handlers to avoid conflicts
    textContainer.removeEventListener('mouseup', handleRobustTextSelection);
    textContainer.removeEventListener('keyup', handleRobustTextSelection);

    // Add new handlers
    textContainer.addEventListener('mouseup', handleRobustTextSelection);
    textContainer.addEventListener('keyup', handleRobustTextSelection);

    debugLog('[ROBUST SPAN] Text selection handlers set up');
}

/**
 * Handle text selection for robust span annotation
 */
function handleRobustTextSelection() {
    const selection = window.getSelection();
    if (!selection.rangeCount || selection.isCollapsed) return;

    // Check if any span label is selected
    const activeSpanLabel = getActiveSpanLabel();
    if (!activeSpanLabel) {
        debugLog('[ROBUST SPAN] No active span label selected');
        return;
    }

    const range = selection.getRangeAt(0);
    const selectedText = selection.toString().trim();
    if (!selectedText) return;

    // Calculate positions using original text
    const start = getRobustTextPosition(selectedText, range);
    const end = start + selectedText.length;

    debugLog('[ROBUST SPAN] Creating span:', {
        text: selectedText,
        start: start,
        end: end,
        label: activeSpanLabel
    });

    // Create the span annotation
    createRobustSpanAnnotation(selectedText, start, end, activeSpanLabel);

    // Clear selection
    selection.removeAllRanges();
}

/**
 * Get the currently active span label from checkboxes
 */
function getActiveSpanLabel() {
    const spanCheckboxes = document.querySelectorAll('input[type="checkbox"][name*="span_label"]:checked');
    if (spanCheckboxes.length === 0) return null;

    // Get the label from the first checked span checkbox
    const checkbox = spanCheckboxes[0];
    const labelMatch = checkbox.name.match(/span_label:::(.+):::(.+)/);
    if (labelMatch) {
        return labelMatch[2]; // Return the label name
    }
    return null;
}

/**
 * Calculate text position robustly using original text
 */
function getRobustTextPosition(selectedText, range) {
    // Get the original text from the instance
    if (!currentInstance || !currentInstance.text) {
        console.warn('[ROBUST SPAN] No original text available');
        return 0;
    }

    const originalText = currentInstance.text;

    // Find all occurrences of the selected text in the original text
    let indices = [];
    let idx = originalText.indexOf(selectedText);
    while (idx !== -1) {
        indices.push(idx);
        idx = originalText.indexOf(selectedText, idx + 1);
    }

    if (indices.length === 0) {
        console.warn('[ROBUST SPAN] Selected text not found in original text');
        return 0;
    }

    if (indices.length === 1) {
        return indices[0];
    }

    // If multiple occurrences, use the first one for now
    // In a more sophisticated implementation, we could use DOM position to disambiguate
    debugLog('[ROBUST SPAN] Multiple occurrences found, using first:', indices[0]);
    return indices[0];
}

/**
 * Create a new span annotation using the robust approach
 */
async function createRobustSpanAnnotation(spanText, start, end, label) {
    try {
        debugLog('[ROBUST SPAN] Creating annotation:', { spanText, start, end, label });

        // Use the existing /updateinstance endpoint
        const postData = {
            type: "span",
            schema: "emotion", // This should come from the config
            state: [
                {
                    name: label,
                    start: start,
                    end: end,
                    title: label,
                    value: spanText
                }
            ],
            instance_id: currentInstance.id
        };

        const response = await fetch('/updateinstance', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(postData)
        });

        if (response.ok) {
            debugLog('[ROBUST SPAN] Span annotation created successfully');
            // Reload the instance to show the new annotation
            await loadCurrentInstance();
        } else {
            console.error('[ROBUST SPAN] Failed to create span annotation:', await response.text());
        }
    } catch (error) {
        console.error('[ROBUST SPAN] Error creating span annotation:', error);
    }
}

/**
 * Render spans using the robust boundary-based algorithm
 */
function renderSpansRobust() {
    const textContainer = document.getElementById('instance-text');
    if (!textContainer || !currentInstance) {
        console.warn('[ROBUST SPAN] Cannot render spans - missing container or instance');
        return;
    }

    // Get the original text
    originalText = currentInstance.text || '';
    if (!originalText) {
        console.warn('[ROBUST SPAN] No original text available');
        return;
    }

    // Get span annotations from user state
    spanAnnotations = [];
    if (userState && userState.annotations && userState.annotations.by_instance) {
        const instanceAnnotations = userState.annotations.by_instance[currentInstance.id];
        if (instanceAnnotations) {
            // Extract span annotations from the server format
            for (const [key, value] of Object.entries(instanceAnnotations)) {
                // Look for span annotations (this is a simplified approach)
                // In practice, we'd need to parse the actual span data structure
                if (typeof value === 'object' && value.start !== undefined && value.end !== undefined) {
                    spanAnnotations.push({
                        id: key,
                        span: value.value || '',
                        label: value.name || key,
                        start: value.start,
                        end: value.end
                    });
                }
            }
        }
    }

    debugLog('[ROBUST SPAN] Rendering spans:', spanAnnotations);

    if (spanAnnotations.length === 0) {
        // No spans - just show the original text
        textContainer.innerHTML = escapeHtml(originalText);
        return;
    }

    // Use the boundary-based algorithm from potato-span-fix
    const html = renderTextWithSpans(originalText, spanAnnotations);
    textContainer.innerHTML = html;
}

/**
 * Render text with spans using boundary-based algorithm
 */
function renderTextWithSpans(text, annotations) {
    // Create a list of all annotation boundaries (start and end points)
    const boundaries = [];
    annotations.forEach(annotation => {
        boundaries.push({ position: annotation.start, type: 'start', annotation });
        boundaries.push({ position: annotation.end, type: 'end', annotation });
    });

    // Sort boundaries by position
    boundaries.sort((a, b) => a.position - b.position);

    // Build HTML by walking through the text and opening/closing spans
    let html = '';
    let currentPos = 0;
    let openSpans = [];

    boundaries.forEach(boundary => {
        // Add text before this boundary
        if (boundary.position > currentPos) {
            html += escapeHtml(text.substring(currentPos, boundary.position));
        }

        if (boundary.type === 'start') {
            // Open a new span
            const backgroundColor = getSpanColor(boundary.annotation.label);
            const span = `<span class="span-highlight" data-annotation-id="${boundary.annotation.id}" data-label="${boundary.annotation.label}" style="background-color: ${backgroundColor}"><span class="span-delete" onclick="deleteRobustSpan('${boundary.annotation.id}')">×</span><span class="span-label">${boundary.annotation.label}</span>`;
            html += span;
            openSpans.push(boundary.annotation);
        } else {
            // Close a span
            html += '</span>';
            // Remove the closed span from openSpans
            const index = openSpans.findIndex(span => span.id === boundary.annotation.id);
            if (index !== -1) {
                openSpans.splice(index, 1);
            }
        }

        currentPos = boundary.position;
    });

    // Add remaining text
    if (currentPos < text.length) {
        html += escapeHtml(text.substring(currentPos));
    }

    // Close any remaining open spans
    openSpans.forEach(() => {
        html += '</span>';
    });

    return html;
}

/**
 * Get span color for a label
 */
function getSpanColor(label) {
    const color = spanColors[label];
    if (!color) return '#f0f0f0'; // Default gray

    // Convert RGB format to hex
    const rgb = color.match(/\((\d+),\s*(\d+),\s*(\d+)\)/);
    if (rgb) {
        const r = parseInt(rgb[1]);
        const g = parseInt(rgb[2]);
        const b = parseInt(rgb[3]);
        return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`;
    }

    return '#f0f0f0';
}

/**
 * Delete a span annotation
 */
async function deleteRobustSpan(annotationId) {
    try {
        debugLog('[ROBUST SPAN] Deleting span:', annotationId);

        // Find the annotation to delete
        const annotation = spanAnnotations.find(a => a.id === annotationId);
        if (!annotation) {
            console.warn('[ROBUST SPAN] Annotation not found:', annotationId);
            return;
        }

        // Use the existing /updateinstance endpoint with value: null to delete
        const postData = {
            type: "span",
            schema: "emotion", // This should come from the config
            state: [
                {
                    name: annotation.label,
                    start: annotation.start,
                    end: annotation.end,
                    title: annotation.label,
                    value: null // This signals deletion
                }
            ],
            instance_id: currentInstance.id
        };

        const response = await fetch('/updateinstance', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(postData)
        });

        if (response.ok) {
            debugLog('[ROBUST SPAN] Span annotation deleted successfully');
            // Reload the instance to show the updated state
            await loadCurrentInstance();
        } else {
            console.error('[ROBUST SPAN] Failed to delete span annotation:', await response.text());
        }
    } catch (error) {
        console.error('[ROBUST SPAN] Error deleting span annotation:', error);
    }
}

/**
 * Escape HTML content
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Initialize robust span annotation when the page loads
document.addEventListener('DOMContentLoaded', function () {
    // Wait for the initial load to complete, then initialize robust spans
    // DISABLED: Legacy robust span system conflicts with new interval-based system
    // setTimeout(() => {
    //     initializeRobustSpanAnnotation();
    // }, 500);
});

/**
 * Delete a span annotation - called from the HTML onclick
 */
async function deleteSpanAnnotation(annotationId, label, start, end) {
    try {
        debugLog('[SPAN DELETE] Deleting span:', { annotationId, label, start, end });

        // Use the existing /updateinstance endpoint with value: null to delete
        const postData = {
            type: "span",
            schema: "emotion", // This should come from the config
            state: [
                {
                    name: label,
                    start: start,
                    end: end,
                    title: label,
                    value: null // This signals deletion
                }
            ],
            instance_id: currentInstance.id
        };

        const response = await fetch('/updateinstance', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(postData)
        });

        if (response.ok) {
            debugLog('[SPAN DELETE] Span annotation deleted successfully');
            // Reload the instance to show the updated state
            await loadCurrentInstance();
        } else {
            console.error('[SPAN DELETE] Failed to delete span annotation:', await response.text());
        }
    } catch (error) {
        console.error('[SPAN DELETE] Error deleting span annotation:', error);
    }
}

// Add this function to help debug and clear erroneous span annotations
async function debugAndClearSpans() {
    debugLog('🔍 [DEBUG] debugAndClearSpans() - ENTRY POINT');

    if (!currentInstance || !currentInstance.id) {
        debugLog('🔍 [DEBUG] debugAndClearSpans() - No current instance');
        return;
    }

    debugLog(`🔍 [DEBUG] debugAndClearSpans() - Current instance ID: ${currentInstance.id}`);

    try {
        // First, check what spans exist for this instance
        const response = await fetch(`/api/spans/${currentInstance.id}`);
        if (response.ok) {
            const data = await response.json();
            debugLog(`🔍 [DEBUG] debugAndClearSpans() - Current spans for instance ${currentInstance.id}:`, data.spans);

            if (data.spans && data.spans.length > 0) {
                debugLog(`🔍 [DEBUG] debugAndClearSpans() - Found ${data.spans.length} spans, clearing them...`);

                // Clear the spans
                const clearResponse = await fetch(`/api/spans/${currentInstance.id}/clear`, {
                    method: 'POST',
                    credentials: 'include'
                });

                if (clearResponse.ok) {
                    const clearData = await clearResponse.json();
                    debugLog(`🔍 [DEBUG] debugAndClearSpans() - Cleared ${clearData.spans_cleared} spans`);

                    // Reload the page to see the effect
                    debugLog('🔍 [DEBUG] debugAndClearSpans() - Reloading page...');
                    window.location.reload();
                } else {
                    console.error('🔍 [DEBUG] debugAndClearSpans() - Failed to clear spans:', await clearResponse.text());
                }
            } else {
                debugLog(`🔍 [DEBUG] debugAndClearSpans() - No spans found for instance ${currentInstance.id}`);
            }
        } else {
            console.error('🔍 [DEBUG] debugAndClearSpans() - Failed to get spans:', await response.text());
        }
    } catch (error) {
        console.error('🔍 [DEBUG] debugAndClearSpans() - Error:', error);
    }
}

// Make the function available globally for debugging
window.debugAndClearSpans = debugAndClearSpans;

// Add this function to help debug instance_id values
function debugInstanceId() {
    debugLog('🔍 [DEBUG] debugInstanceId() - ENTRY POINT');

    // Check DOM instance_id
    const domInstanceId = document.getElementById('instance_id');
    const domValue = domInstanceId ? domInstanceId.value : 'not found';
    debugLog(`🔍 [DEBUG] debugInstanceId() - DOM instance_id value: '${domValue}'`);

    // Check currentInstance
    const currentInstanceId = currentInstance ? currentInstance.id : 'not set';
    debugLog(`🔍 [DEBUG] debugInstanceId() - currentInstance.id: '${currentInstanceId}'`);

    // Check if they match
    if (domValue === currentInstanceId) {
        debugLog('🔍 [DEBUG] debugInstanceId() - ✅ DOM and currentInstance match');
    } else {
        debugLog('🔍 [DEBUG] debugInstanceId() - ❌ DOM and currentInstance do NOT match');
    }

    // Check what the API would return
    if (currentInstance && currentInstance.id) {
        debugLog(`🔍 [DEBUG] debugInstanceId() - API would be called with: /api/spans/${currentInstance.id}`);
    }
}

// Make the function available globally for debugging
window.debugInstanceId = debugInstanceId;

// Add this function to help debug and fix the instance_id issue in production
function debugAndFixInstanceId() {
    debugLog('🔍 [DEBUG] debugAndFixInstanceId() - ENTRY POINT');

    // Check current state
    const domInstanceId = document.getElementById('instance_id');
    const domValue = domInstanceId ? domInstanceId.value : 'not found';
    debugLog(`🔍 [DEBUG] debugAndFixInstanceId() - Current DOM instance_id: '${domValue}'`);

    // Check if we can force a hard refresh
    debugLog('🔍 [DEBUG] debugAndFixInstanceId() - Attempting to force hard refresh...');

    // Clear any cached data
    if (window.caches) {
        caches.keys().then(names => {
            names.forEach(name => {
                debugLog(`🔍 [DEBUG] debugAndFixInstanceId() - Clearing cache: ${name}`);
                caches.delete(name);
            });
        });
    }

    // Force a hard refresh by adding a timestamp
    const currentUrl = window.location.href;
    const separator = currentUrl.includes('?') ? '&' : '?';
    const newUrl = currentUrl + separator + '_t=' + Date.now();
    debugLog(`🔍 [DEBUG] debugAndFixInstanceId() - Redirecting to: ${newUrl}`);

    // Redirect to force a fresh page load
    window.location.href = newUrl;
}

// Add this function to check if the page is cached
function checkPageCache() {
    debugLog('🔍 [DEBUG] checkPageCache() - ENTRY POINT');

    // Check if the page was loaded from cache
    if (window.performance && window.performance.navigation) {
        const navigationType = window.performance.navigation.type;
        debugLog(`🔍 [DEBUG] checkPageCache() - Navigation type: ${navigationType}`);

        if (navigationType === 1) {
            debugLog('🔍 [DEBUG] checkPageCache() - Page was reloaded');
        } else if (navigationType === 2) {
            debugLog('🔍 [DEBUG] checkPageCache() - Page was loaded from back/forward cache');
        } else {
            debugLog('🔍 [DEBUG] checkPageCache() - Page was loaded normally');
        }
    }

    // Check if the page was loaded from cache using the newer API
    if (window.performance && window.performance.getEntriesByType) {
        const navigationEntries = window.performance.getEntriesByType('navigation');
        if (navigationEntries.length > 0) {
            const entry = navigationEntries[0];
            debugLog(`🔍 [DEBUG] checkPageCache() - Transfer size: ${entry.transferSize}`);
            debugLog(`🔍 [DEBUG] checkPageCache() - Encoded body size: ${entry.encodedBodySize}`);

            if (entry.transferSize === 0 && entry.encodedBodySize > 0) {
                debugLog('🔍 [DEBUG] checkPageCache() - Page was loaded from cache!');
            } else {
                debugLog('🔍 [DEBUG] checkPageCache() - Page was loaded from network');
            }
        }
    }
}

// Make the function available globally for debugging
window.debugAndFixInstanceId = debugAndFixInstanceId;
window.checkPageCache = checkPageCache;

// Add this function to help clear erroneous span annotations and fix overlay persistence
async function clearErroneousSpans() {
    debugLog('🔍 [DEBUG] clearErroneousSpans() - ENTRY POINT');

    if (!currentInstance || !currentInstance.id) {
        debugLog('🔍 [DEBUG] clearErroneousSpans() - No current instance');
        return;
    }

    debugLog(`🔍 [DEBUG] clearErroneousSpans() - Current instance ID: ${currentInstance.id}`);

    try {
        // Clear spans for the current instance
        const response = await fetch(`/api/spans/${currentInstance.id}/clear`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            }
        });

        if (response.ok) {
            const result = await response.json();
            debugLog(`🔍 [DEBUG] clearErroneousSpans() - Clear result:`, result);

            // Force reload the page to get fresh data
            debugLog('🔍 [DEBUG] clearErroneousSpans() - Reloading page to get fresh data');
            window.location.reload();
        } else {
            console.error(`🔍 [DEBUG] clearErroneousSpans() - Clear failed:`, response.status);
        }
    } catch (error) {
        console.error(`🔍 [DEBUG] clearErroneousSpans() - Error:`, error);
    }
}

// Make the function available globally for debugging
window.clearErroneousSpans = clearErroneousSpans;

// Add Firefox-specific instance_id fix that runs after page load
function firefoxInstanceIdFix() {
    const isFirefox = navigator.userAgent.toLowerCase().includes('firefox');
    if (!isFirefox) {
        return; // Only apply to Firefox
    }

    debugLog('🔍 [DEBUG] firefoxInstanceIdFix: Starting Firefox-specific instance_id fix');

    // Wait a bit for the page to fully load
    setTimeout(() => {
        const instanceIdInput = document.getElementById('instance_id');
        if (!instanceIdInput) {
            debugLog('🔍 [DEBUG] firefoxInstanceIdFix: No instance_id input found');
            return;
        }

        // Get the current instance from the server-rendered data
        const currentInstanceId = currentInstance?.id;
        const domInstanceId = instanceIdInput.value;

        debugLog(`🔍 [DEBUG] firefoxInstanceIdFix: DOM instance_id: '${domInstanceId}', currentInstance.id: '${currentInstanceId}'`);

        if (currentInstanceId && domInstanceId !== currentInstanceId) {
            debugLog('🔍 [DEBUG] firefoxInstanceIdFix: Mismatch detected - fixing instance_id');

            // Force update the input value
            instanceIdInput.value = currentInstanceId;

            // Force DOM update
            instanceIdInput.dispatchEvent(new Event('input', { bubbles: true }));
            instanceIdInput.dispatchEvent(new Event('change', { bubbles: true }));

            // Force reflow
            instanceIdInput.offsetHeight;

            debugLog(`🔍 [DEBUG] firefoxInstanceIdFix: Fixed instance_id to '${currentInstanceId}'`);
        } else {
            debugLog('🔍 [DEBUG] firefoxInstanceIdFix: No mismatch detected');
        }
    }, 100); // Small delay to ensure page is loaded
}

// Call the Firefox fix after page load
document.addEventListener('DOMContentLoaded', firefoxInstanceIdFix);
window.addEventListener('load', firefoxInstanceIdFix);

// Add function to test the Firefox instance_id fix
function testFirefoxInstanceIdFix() {
    debugLog('🔍 [DEBUG] testFirefoxInstanceIdFix: Testing Firefox instance_id fix');

    const isFirefox = navigator.userAgent.toLowerCase().includes('firefox');
    debugLog(`🔍 [DEBUG] testFirefoxInstanceIdFix: Is Firefox: ${isFirefox}`);

    const instanceIdInput = document.getElementById('instance_id');
    if (!instanceIdInput) {
        debugLog('🔍 [DEBUG] testFirefoxInstanceIdFix: No instance_id input found');
        return;
    }

    const domInstanceId = instanceIdInput.value;
    const currentInstanceId = currentInstance?.id;

    debugLog(`🔍 [DEBUG] testFirefoxInstanceIdFix: DOM instance_id: '${domInstanceId}'`);
    debugLog(`🔍 [DEBUG] testFirefoxInstanceIdFix: currentInstance.id: '${currentInstanceId}'`);

    if (domInstanceId === currentInstanceId) {
        debugLog('🔍 [DEBUG] testFirefoxInstanceIdFix: ✅ Instance IDs match');
    } else {
        debugLog('🔍 [DEBUG] testFirefoxInstanceIdFix: ❌ Instance IDs do not match');

        // Try to fix it
        debugLog('🔍 [DEBUG] testFirefoxInstanceIdFix: Attempting to fix...');
        firefoxInstanceIdFix();

        // Check again after a short delay
        setTimeout(() => {
            const newDomInstanceId = instanceIdInput.value;
            debugLog(`🔍 [DEBUG] testFirefoxInstanceIdFix: After fix - DOM instance_id: '${newDomInstanceId}'`);

            if (newDomInstanceId === currentInstanceId) {
                debugLog('🔍 [DEBUG] testFirefoxInstanceIdFix: ✅ Fix successful');
            } else {
                debugLog('🔍 [DEBUG] testFirefoxInstanceIdFix: ❌ Fix failed');
            }
        }, 200);
    }
}

// Make the function available globally for debugging
window.testFirefoxInstanceIdFix = testFirefoxInstanceIdFix;

// Add aggressive Firefox-specific instance_id fix
function aggressiveFirefoxInstanceIdFix() {
    const isFirefox = navigator.userAgent.toLowerCase().includes('firefox');
    if (!isFirefox) {
        return; // Only apply to Firefox
    }

    debugLog('🔍 [DEBUG] aggressiveFirefoxInstanceIdFix: Starting aggressive Firefox fix');

    // Wait for the page to fully load
    setTimeout(() => {
        // Method 1: Force reload the instance_id input element
        const instanceIdInput = document.getElementById('instance_id');
        if (!instanceIdInput) {
            debugLog('🔍 [DEBUG] aggressiveFirefoxInstanceIdFix: No instance_id input found');
            return;
        }

        // Get the current value from the DOM
        const currentDomValue = instanceIdInput.value;
        debugLog(`🔍 [DEBUG] aggressiveFirefoxInstanceIdFix: Current DOM value: '${currentDomValue}'`);

        // Method 2: Try to get the correct value from the server-rendered data
        // Look for any script tags or data attributes that might contain the correct instance_id
        let correctInstanceId = null;

        // Check if there's a script tag with instance data
        const scriptTags = document.querySelectorAll('script');
        for (const script of scriptTags) {
            const content = script.textContent || script.innerHTML;
            if (content.includes('instance_id') || content.includes('currentInstance')) {
                debugLog('🔍 [DEBUG] aggressiveFirefoxInstanceIdFix: Found script with instance data');
                // Try to extract instance_id from script content
                const match = content.match(/instance_id['"]?\s*[:=]\s*['"]([^'"]+)['"]/);
                if (match) {
                    correctInstanceId = match[1];
                    debugLog(`🔍 [DEBUG] aggressiveFirefoxInstanceIdFix: Found instance_id in script: '${correctInstanceId}'`);
                    break;
                }
            }
        }

        // Method 3: If we can't find it in scripts, try to infer from the URL or other page elements
        if (!correctInstanceId) {
            // Check if the URL contains an instance_id parameter
            const urlParams = new URLSearchParams(window.location.search);
            const urlInstanceId = urlParams.get('instance_id');
            if (urlInstanceId) {
                correctInstanceId = urlInstanceId;
                debugLog(`🔍 [DEBUG] aggressiveFirefoxInstanceIdFix: Found instance_id in URL: '${correctInstanceId}'`);
            }
        }

        // Method 4: If we still don't have it, try to get it from the server via API
        if (!correctInstanceId) {
            debugLog('🔍 [DEBUG] aggressiveFirefoxInstanceIdFix: No instance_id found, trying API call');

            // Make an API call to get the current instance info
            fetch('/api/current_instance', {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                }
            })
                .then(response => response.json())
                .then(data => {
                    if (data && data.instance_id) {
                        correctInstanceId = data.instance_id;
                        debugLog(`🔍 [DEBUG] aggressiveFirefoxInstanceIdFix: Got instance_id from API: '${correctInstanceId}'`);
                        applyInstanceIdFix(instanceIdInput, correctInstanceId);
                    }
                })
                .catch(error => {
                    debugLog('🔍 [DEBUG] aggressiveFirefoxInstanceIdFix: API call failed:', error);
                });
        } else {
            // Apply the fix immediately if we found the correct instance_id
            applyInstanceIdFix(instanceIdInput, correctInstanceId);
        }
    }, 200); // Longer delay to ensure page is fully loaded
}

// Helper function to apply the instance_id fix
function applyInstanceIdFix(instanceIdInput, correctInstanceId) {
    const currentValue = instanceIdInput.value;

    if (currentValue !== correctInstanceId) {
        debugLog(`🔍 [DEBUG] applyInstanceIdFix: Fixing instance_id from '${currentValue}' to '${correctInstanceId}'`);

        // Force update the input value
        instanceIdInput.value = correctInstanceId;

        // Force DOM update with multiple methods
        instanceIdInput.dispatchEvent(new Event('input', { bubbles: true }));
        instanceIdInput.dispatchEvent(new Event('change', { bubbles: true }));
        instanceIdInput.dispatchEvent(new Event('blur', { bubbles: true }));

        // Force reflow
        instanceIdInput.offsetHeight;

        // Update currentInstance if it exists
        if (window.currentInstance) {
            window.currentInstance.id = correctInstanceId;
            debugLog(`🔍 [DEBUG] applyInstanceIdFix: Updated window.currentInstance.id to '${correctInstanceId}'`);
        }

        // Update currentInstance global variable if it exists
        if (typeof currentInstance !== 'undefined' && currentInstance) {
            currentInstance.id = correctInstanceId;
            debugLog(`🔍 [DEBUG] applyInstanceIdFix: Updated currentInstance.id to '${correctInstanceId}'`);
        }

        debugLog(`🔍 [DEBUG] applyInstanceIdFix: Fix applied successfully`);
    } else {
        debugLog(`🔍 [DEBUG] applyInstanceIdFix: No fix needed, instance_id is already correct: '${currentValue}'`);
    }
}

// Call the aggressive fix after page load
document.addEventListener('DOMContentLoaded', aggressiveFirefoxInstanceIdFix);
window.addEventListener('load', aggressiveFirefoxInstanceIdFix);

// Also call it when the page becomes visible (in case of tab switching)
document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
        setTimeout(aggressiveFirefoxInstanceIdFix, 100);
    }
});

// Add function to test the aggressive Firefox fix
function testAggressiveFirefoxFix() {
    debugLog('🔍 [DEBUG] testAggressiveFirefoxFix: Testing aggressive Firefox fix');

    const isFirefox = navigator.userAgent.toLowerCase().includes('firefox');
    debugLog(`🔍 [DEBUG] testAggressiveFirefoxFix: Is Firefox: ${isFirefox}`);

    if (!isFirefox) {
        debugLog('🔍 [DEBUG] testAggressiveFirefoxFix: Not Firefox, skipping test');
        return;
    }

    // Call the aggressive fix
    debugLog('🔍 [DEBUG] testAggressiveFirefoxFix: Calling aggressiveFirefoxInstanceIdFix');
    aggressiveFirefoxInstanceIdFix();

    // Check the result after a delay
    setTimeout(() => {
        const instanceIdInput = document.getElementById('instance_id');
        if (!instanceIdInput) {
            debugLog('🔍 [DEBUG] testAggressiveFirefoxFix: No instance_id input found');
            return;
        }

        const finalInstanceId = instanceIdInput.value;
        const currentInstanceId = currentInstance?.id;

        debugLog(`🔍 [DEBUG] testAggressiveFirefoxFix: Final DOM instance_id: '${finalInstanceId}'`);
        debugLog(`🔍 [DEBUG] testAggressiveFirefoxFix: currentInstance.id: '${currentInstanceId}'`);

        if (finalInstanceId === currentInstanceId) {
            debugLog('🔍 [DEBUG] testAggressiveFirefoxFix: ✅ Fix successful - instance IDs match');
        } else {
            debugLog('🔍 [DEBUG] testAggressiveFirefoxFix: ❌ Fix failed - instance IDs do not match');
        }
    }, 500);
}




// Make the function available globally for debugging
window.testAggressiveFirefoxFix = testAggressiveFirefoxFix;
window.navigateToNext = navigateToNext;
window.navigateToPrevious = navigateToPrevious;
window.loadCurrentInstance = loadCurrentInstance;
