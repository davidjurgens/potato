// Global state
let currentInstance = null;
let currentAnnotations = {};
let userState = null;
let isLoading = false;
let textSaveTimer = null;
let currentSpanAnnotations = [];

// DEBUG: Add overlay tracking
let debugOverlayCount = 0;
let debugLastInstanceId = null;

// Initialize the application
document.addEventListener('DOMContentLoaded', function() {
    console.log('🔍 [DEBUG] DOM Content Loaded - Starting application initialization');
    loadCurrentInstance();
    setupEventListeners();
    // Initial validation check
    validateRequiredFields();
    // Initialize span manager integration
    initializeSpanManagerIntegration();
});

// DEBUG: Add overlay tracking function
function debugTrackOverlays(action, instanceId = null) {
    const spanOverlays = document.getElementById('span-overlays');
    const overlayCount = spanOverlays ? spanOverlays.children.length : 0;
    const instanceText = document.getElementById('instance-text');
    const textContent = document.getElementById('text-content');

    console.log(`🔍 [DEBUG OVERLAY TRACKING] ${action}:`, {
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

// DEBUG: Add overlay cleanup verification
function debugVerifyOverlayCleanup() {
    const spanOverlays = document.getElementById('span-overlays');
    if (!spanOverlays) {
        console.warn('🔍 [DEBUG] span-overlays container not found during cleanup verification');
        return;
    }

    const overlayCount = spanOverlays.children.length;
    console.log(`🔍 [DEBUG] Overlay cleanup verification:`, {
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
        console.warn('🔍 [DEBUG] WARNING: Overlays still present after expected cleanup!');
    }
}

function setupEventListeners() {
    // Go to button
    document.getElementById('go-to-btn').addEventListener('click', function() {
        const goToValue = document.getElementById('go_to').value;
        if (goToValue && goToValue > 0) {
            navigateToInstance(parseInt(goToValue));
        }
    });

    // Enter key on go to input
    document.getElementById('go_to').addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            document.getElementById('go-to-btn').click();
        }
    });

    // Keyboard navigation
    document.addEventListener('keydown', function(e) {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
            return; // Don't handle navigation when typing
        }

        switch(e.key) {
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
}

/**
 * Initialize integration with the frontend span manager
 */
function initializeSpanManagerIntegration() {
    // Wait for span manager to be available
    const checkSpanManager = () => {
        if (window.spanManager && window.spanManager.isInitialized) {
            console.log('Annotation.js: Span manager integration initialized');
            setupSpanLabelSelector();
        } else {
            setTimeout(checkSpanManager, 100);
        }
    };
    checkSpanManager();
}

/**
 * Setup span label selector based on annotation scheme
 */
function setupSpanLabelSelector() {
    const labelSelector = document.getElementById('span-label-selector');
    const labelButtons = document.getElementById('label-buttons');

    if (!labelSelector || !labelButtons) {
        console.warn('Annotation.js: Span label selector elements not found');
        return;
    }

    // Check if there are span annotation forms in the DOM
    const spanForms = document.querySelectorAll('.annotation-form.span');

    if (spanForms.length > 0) {
        // Extract labels from the existing span form checkboxes
        const existingCheckboxes = document.querySelectorAll('.annotation-form.span input[type="checkbox"]');
        const labels = [];

        existingCheckboxes.forEach(checkbox => {
            const label = checkbox.getAttribute('value');
            if (label && !labels.includes(label)) {
                labels.push(label);
            }
        });

        if (labels.length > 0) {
            // Clear and regenerate label buttons
            labelButtons.innerHTML = '';
            labels.forEach(label => {
                const button = document.createElement('button');
                button.className = 'label-button';
                button.dataset.label = label;
                button.textContent = label;
                labelButtons.appendChild(button);
            });

            labelSelector.style.display = 'block';
            console.log('Annotation.js: Span label selector shown with labels:', labels);
        }
    } else {
        labelSelector.style.display = 'none';
    }
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
    if (!window.spanManager || !currentInstance) {
        return;
    }

    try {
        // DEBUG: Track overlays before loading span annotations
        debugTrackOverlays('BEFORE_LOAD_SPAN_ANNOTATIONS', currentInstance.id);

        // Check if spans are already rendered in the displayed_text
        const instanceText = document.getElementById('instance-text');
        const hasRenderedSpans = instanceText.innerHTML.includes('span-highlight');

        if (hasRenderedSpans) {
            console.log('Annotation.js: Spans already rendered by backend, skipping frontend rendering');
            // Still load annotations for the span manager state, but don't render
            await window.spanManager.loadAnnotations(currentInstance.id);
            return;
        }

        // If no spans are rendered, load and render them
        await window.spanManager.loadAnnotations(currentInstance.id);
        console.log('Annotation.js: Span annotations loaded for instance:', currentInstance.id);

        // DEBUG: Track overlays after loading span annotations
        debugTrackOverlays('AFTER_LOAD_SPAN_ANNOTATIONS', currentInstance.id);
    } catch (error) {
        console.error('Annotation.js: Error loading span annotations:', error);
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

        // Load span annotations and setup label selector
        await loadSpanAnnotations();
        setupSpanLabelSelector();

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
    console.log('Progress display updated from server-rendered HTML');
}

function updateInstanceDisplay() {
    // Instance text is already displayed in the HTML template
    // Just ensure the instance_id is set correctly
    const instanceIdInput = document.getElementById('instance_id');
    if (instanceIdInput && currentInstance && currentInstance.id) {
        instanceIdInput.value = currentInstance.id;
    }
    console.log('[DEBUG] updateInstanceDisplay: Instance display updated from server-rendered HTML');
}

async function loadAnnotations() {
    try {
        console.log('🔍 Loading annotations for instance:', currentInstance.id);

        // Since we're not using the admin API, we'll get annotations from the DOM
        // The server should have pre-populated the form fields with existing annotations
        currentAnnotations = {};

        // We'll populate annotations from the DOM in populateInputValues()
        console.log('🔍 Annotations will be loaded from DOM in populateInputValues()');
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
        console.log('[DEBUG] saveAnnotations: spanAnnotations to send:', spanAnnotations);

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
            console.log('[DEBUG] saveAnnotations: annotations saved:', result);
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
    if (isLoading) return;

    try {
        setLoading(true);

        // DEBUG: Track overlays before navigation
        debugTrackOverlays('BEFORE_PREV_NAVIGATION', currentInstance?.id);

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
                action: 'prev_instance',
                instance_id: currentInstance?.id
            })
        });

        if (response.ok) {
            console.log('🔍 [DEBUG] Navigation successful, about to reload page');
            // DEBUG: Clear overlays before reload
            const spanOverlays = document.getElementById('span-overlays');
            if (spanOverlays) {
                console.log('🔍 [DEBUG] Clearing span overlays before page reload');
                spanOverlays.innerHTML = '';
                debugVerifyOverlayCleanup();
            }
            // Reload the page to get the new instance data from the server
            window.location.reload();
        } else {
            throw new Error('Failed to navigate to previous instance');
        }
    } catch (error) {
        console.error('Error navigating to previous:', error);
        showError(true, error.message);
    } finally {
        setLoading(false);
    }
}

async function navigateToNext() {
    if (isLoading) return;

    // Save current annotations before navigating
    const saved = await saveAnnotations();
    if (!saved) return;

    try {
        setLoading(true);

        // DEBUG: Track overlays before navigation
        debugTrackOverlays('BEFORE_NEXT_NAVIGATION', currentInstance?.id);

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
                action: 'next_instance',
                instance_id: currentInstance?.id
            })
        });

        if (response.ok) {
            console.log('🔍 [DEBUG] Navigation successful, about to reload page');
            // DEBUG: Clear overlays before reload
            const spanOverlays = document.getElementById('span-overlays');
            if (spanOverlays) {
                console.log('🔍 [DEBUG] Clearing span overlays before page reload');
                spanOverlays.innerHTML = '';
                debugVerifyOverlayCleanup();
            }
            // Reload the page to get the new instance data from the server
            window.location.reload();
        } else {
            throw new Error('Failed to navigate to next instance');
        }
    } catch (error) {
        console.error('Error navigating to next:', error);
        showError(true, error.message);
    } finally {
        setLoading(false);
    }
}

async function navigateToInstance(instanceIndex) {
    if (isLoading) return;

    try {
        setLoading(true);

        // DEBUG: Track overlays before navigation
        debugTrackOverlays('BEFORE_GO_TO_NAVIGATION', currentInstance?.id);

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
            console.log('🔍 [DEBUG] Navigation successful, about to reload page');
            // DEBUG: Clear overlays before reload
            const spanOverlays = document.getElementById('span-overlays');
            if (spanOverlays) {
                console.log('🔍 [DEBUG] Clearing span overlays before page reload');
                spanOverlays.innerHTML = '';
                debugVerifyOverlayCleanup();
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
        if(checkbox.value == "None" && x[i].value != "None") x[i].checked = false;
        if(checkbox.value != "None" && x[i].value == "None") x[i].checked = false;
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
            input.addEventListener('input', function(event) {
                clearTimeout(timer);
                timer = setTimeout(() => {
                    handleInputChange(event.target);
                }, 1000);
            });
            console.log(`Set up event listener for ${tagName} element:`, input.id);
        } else if (inputType === 'radio' || inputType === 'checkbox') {
            // Radio/checkbox inputs - immediate saving
            input.addEventListener('change', function(event) {
                handleInputChange(event.target);
            });
        } else if (inputType === 'range') {
            // Slider inputs - immediate saving with value display
            input.addEventListener('input', function(event) {
                const valueDisplay = document.getElementById(`${input.name}-value`);
                if (valueDisplay) {
                    valueDisplay.textContent = event.target.value;
                }
                handleInputChange(event.target);
            });
        } else if (tagName === 'select') {
            // Select inputs - immediate saving
            input.addEventListener('change', function(event) {
                handleInputChange(event.target);
            });
        } else if (inputType === 'number') {
            // Number inputs - debounced saving
            let timer;
            input.addEventListener('input', function(event) {
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

    console.log(`handleInputChange called for ${tagName} element:`, element.id, 'schema:', schema, 'label:', labelName);

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
            console.log(`Removed annotation: ${schema}.${labelName}`);

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
    console.log(`Updated annotation: ${schema}.${labelName} = ${value}`);

    // Auto-save
    clearTimeout(textSaveTimer);
    textSaveTimer = setTimeout(() => {
        saveAnnotations();
    }, 500);
}

function populateInputValues() {
    if (!currentAnnotations || !userState) return;

    console.log('🔍 Populating input values with annotations:', currentAnnotations);

    // Populate text inputs and textareas
    const textInputs = document.querySelectorAll('input[type="text"], textarea.annotation-input');
    console.log('🔍 Found text inputs and textareas:', textInputs.length);

    textInputs.forEach(input => {
        const schema = input.getAttribute('schema');
        const labelName = input.getAttribute('label_name');
        console.log('🔍 Checking input:', input.id, 'schema:', schema, 'label:', labelName);

        if (schema && labelName && currentAnnotations[schema] && currentAnnotations[schema][labelName]) {
            input.value = currentAnnotations[schema][labelName];
            console.log(`✅ Populated ${input.tagName} ${input.id} with value:`, currentAnnotations[schema][labelName]);
        } else {
            console.log(`❌ Could not populate ${input.tagName} ${input.id}:`, {
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
            console.log(`Populated radio ${input.id}: ${input.checked ? 'checked' : 'unchecked'}`);
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
            console.log(`Populated checkbox ${input.id}: ${hasAnnotation ? 'checked' : 'unchecked'}`);
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
            console.log(`Populated slider ${input.id} with value:`, currentAnnotations[schema][labelName]);
        }
    });

    // Populate select dropdowns
    const selectInputs = document.querySelectorAll('select.annotation-input');
    selectInputs.forEach(input => {
        const schema = input.getAttribute('schema');
        const labelName = input.getAttribute('label_name');

        if (schema && labelName && currentAnnotations[schema] && currentAnnotations[schema][labelName]) {
            input.value = currentAnnotations[schema][labelName];
            console.log(`Populated select ${input.id} with value:`, currentAnnotations[schema][labelName]);
        }
    });

    // Populate number inputs
    const numberInputs = document.querySelectorAll('input[type="number"].annotation-input');
    numberInputs.forEach(input => {
        const schema = input.getAttribute('schema');
        const labelName = input.getAttribute('label_name');

        if (schema && labelName && currentAnnotations[schema] && currentAnnotations[schema][labelName]) {
            input.value = currentAnnotations[schema][labelName];
            console.log(`Populated number ${input.id} with value:`, currentAnnotations[schema][labelName]);
        }
    });

    validateRequiredFields();
}

// Span annotation functions
function onlyOne(checkbox) {
    var x = document.getElementsByClassName(checkbox.className);
    var i;
    for (i = 0; i < x.length; i++) {
        if (x[i].value != checkbox.value) x[i].checked = false;
    }
}

function extractSpanAnnotationsFromDOM() {
    /*
     * Extract span annotations from the DOM using the overlay system.
     *
     * Returns:
     *     Array of span annotation objects with schema, name, start, end, title, value
     */
    console.log('[DEBUG] extractSpanAnnotationsFromDOM called');

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

    console.log('[DEBUG] extractSpanAnnotationsFromDOM: found', spanAnnotations.length, 'spans:', spanAnnotations);
    return spanAnnotations;
}

function alignSpanOverlays() {
    /*
     * Align each .span-overlay to the union of its covered .text-segment spans.
     * This function positions overlays to match the actual text segments in the DOM.
     */
    console.log('[DEBUG] alignSpanOverlays called');

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

        console.log('[DEBUG] alignSpanOverlays: Positioned overlay', annotationId, 'at',
                   minLeft, minTop, maxRight - minLeft, maxBottom - minTop);
    }
}

// Robust selection mapping for overlay system
function getSelectionIndicesOverlay() {
    // Get the user selection
    var selection = window.getSelection();
    if (selection.rangeCount === 0) {
        console.log('[DEBUG] getSelectionIndicesOverlay: No selection');
        return { start: -1, end: -1 };
    }
    var range = selection.getRangeAt(0);
    var originalText = $(range.commonAncestorContainer).closest('.original-text')[0];
    if (!originalText) {
        console.log('[DEBUG] getSelectionIndicesOverlay: Not within .original-text');
        return { start: -2, end: -2 };
    }
    // Find all .text-segment spans in the selection
    const segments = Array.from(originalText.querySelectorAll('.text-segment'));
    let selStart = null, selEnd = null;
    let involvedSegments = [];
    segments.forEach(seg => {
        const segRect = seg.getBoundingClientRect();
        const segStart = parseInt(seg.getAttribute('data-start'));
        const segEnd = parseInt(seg.getAttribute('data-end'));
        // If the segment is (partially) within the selection range
        if (range.intersectsNode(seg)) {
            involvedSegments.push({segStart, segEnd, text: seg.textContent});
            if (selStart === null || segStart < selStart) selStart = segStart;
            if (selEnd === null || segEnd > selEnd) selEnd = segEnd;
        }
    });
    if (selStart === null || selEnd === null) {
        // Fallback: use textContent index
        var fullText = originalText.textContent || originalText.innerText;
        var selectedText = selection.toString();
        var startIndex = fullText.indexOf(selectedText);
        var endIndex = startIndex + selectedText.length;
        console.log('[DEBUG] getSelectionIndicesOverlay: fallback', {fullText, selectedText, startIndex, endIndex});
        return { start: startIndex, end: endIndex };
    }
    var selectedText = selection.toString();
    console.log('[DEBUG] getSelectionIndicesOverlay: final', {selStart, selEnd, selectedText, involvedSegments});
    return { start: selStart, end: selEnd };
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
    console.log('[DEBUG] changeSpanLabel called:', {schema, spanLabel, spanTitle, spanColor, checked: checkbox.checked});

    // Use the new span manager if available
    if (window.spanManager && window.spanManager.isInitialized) {
        console.log('[DEBUG] changeSpanLabel: Using new span manager');

        // Select the label and schema in the span manager
        window.spanManager.selectLabel(spanLabel, schema);

        // Set up text selection handler
        const textContainer = document.getElementById('instance-text');
        if (textContainer) {
            // Remove existing handlers to avoid conflicts
            textContainer.removeEventListener('mouseup', window.spanManager.handleTextSelection.bind(window.spanManager));
            textContainer.removeEventListener('keyup', window.spanManager.handleTextSelection.bind(window.spanManager));

            // Add new handlers only when checkbox is checked
            if (checkbox.checked) {
                textContainer.addEventListener('mouseup', window.spanManager.handleTextSelection.bind(window.spanManager));
                textContainer.addEventListener('keyup', window.spanManager.handleTextSelection.bind(window.spanManager));
                console.log('[DEBUG] changeSpanLabel: Text selection handlers added for span manager');
            }
        }
    } else {
        // Fallback to old overlay system if span manager not available
        console.log('[DEBUG] changeSpanLabel: Span manager not available, using overlay system');
        changeSpanLabelOverlay(checkbox, schema, spanLabel, spanTitle, spanColor);
    }
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

function getSelectionIndicesOverlay() {
    /*
     * Get selection indices for the overlay-based approach.
     *
     * This function works with the original text element and maps
     * DOM selection to original text offsets.
     *
     * Returns:
     *     Object with start and end indices in the original text
     */
    console.log('[DEBUG] getSelectionIndicesOverlay called');

    // Get the user selection
    var selection = window.getSelection();

    if (selection.rangeCount === 0) {
        console.log('[DEBUG] getSelectionIndicesOverlay: No selection');
        return { start: -1, end: -1 }; // No selection
    }

    // Get the range object representing the selected portion
    var range = selection.getRangeAt(0);

    console.log('[DEBUG] getSelectionIndicesOverlay: Selection details:', {
        selectionText: selection.toString(),
        selectionLength: selection.toString().length,
        rangeStartContainer: range.startContainer,
        rangeStartOffset: range.startOffset,
        rangeEndContainer: range.endContainer,
        rangeEndOffset: range.endOffset,
        commonAncestor: range.commonAncestorContainer
    });

    // Find the original text element within the span annotation container
    var originalTextElement = $(range.commonAncestorContainer).closest('.original-text')[0];

    if (!originalTextElement) {
        console.log('[DEBUG] getSelectionIndicesOverlay: Not within .original-text');
        return { start: -2, end: -2 }; // Not within the original text
    }

    // Get the original text from the data attribute for comparison
    var originalTextFromData = originalTextElement.getAttribute('data-original-text');
    console.log('[DEBUG] getSelectionIndicesOverlay: Original text from data attribute:', originalTextFromData);
    console.log('[DEBUG] getSelectionIndicesOverlay: Original text length from data:', originalTextFromData ? originalTextFromData.length : 0);

    // For the overlay approach, we can use a simpler offset calculation
    // since the original text is unchanged and we can directly map DOM positions
    var result = getOriginalTextOffsetsOverlay(originalTextElement, range);

    console.log('[DEBUG] getSelectionIndicesOverlay: Final result:', result);

    return result;
}

function getOriginalTextOffsetsOverlay(container, range) {
    /*
     * Get original text offsets for the overlay approach.
     *
     * Since the original text is unchanged in the DOM, we can directly
     * map DOM positions to original text positions.
     *
     * Args:
     *     container: The original text container element
     *     range: The DOM range object
     *
     * Returns:
     *     Object with start and end offsets in the original text
     */
    console.log('[DEBUG] getOriginalTextOffsetsOverlay called');

    // Get the original text from the data attribute (this is the clean text without HTML markup)
    var originalText = container.getAttribute('data-original-text');
    if (!originalText) {
        console.log('[DEBUG] getOriginalTextOffsetsOverlay: WARNING - no data-original-text attribute found, falling back to DOM text');
        originalText = container.textContent || container.innerText;
    }
    console.log('[DEBUG] getOriginalTextOffsetsOverlay: originalText from data attribute:', originalText);
    console.log('[DEBUG] getOriginalTextOffsetsOverlay: originalText length:', originalText.length);

    // Get the selected text
    var selectedText = window.getSelection().toString();
    console.log('[DEBUG] getOriginalTextOffsetsOverlay: selectedText:', selectedText);
    console.log('[DEBUG] getOriginalTextOffsetsOverlay: selectedText length:', selectedText.length);

    // Find the selection in the original text
    var startIndex = originalText.indexOf(selectedText);
    var endIndex = startIndex + selectedText.length;

    console.log('[DEBUG] getOriginalTextOffsetsOverlay: mapped indices:', {startIndex, endIndex});

    // Verify the indices by extracting text
    if (startIndex !== -1) {
        var extractedText = originalText.substring(startIndex, endIndex);
        console.log('[DEBUG] getOriginalTextOffsetsOverlay: extracted text using indices:', extractedText);
        console.log('[DEBUG] getOriginalTextOffsetsOverlay: extracted text matches selected text:', extractedText === selectedText);
    } else {
        console.log('[DEBUG] getOriginalTextOffsetsOverlay: WARNING - selected text not found in original text!');
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
    console.log('[DEBUG] surroundSelectionOverlay called:', {schema, labelName, title, selectionColor});

    // Check that this wasn't a spurious click or the click for the delete button which
    // also seems to trigger this selection event
    if (window.getSelection().rangeCount == 0) {
        console.log('[DEBUG] surroundSelectionOverlay: No selection range found');
        return;
    }
    var range = window.getSelection().getRangeAt(0);

    if (range.startOffset == range.endOffset) {
        console.log('[DEBUG] surroundSelectionOverlay: Selection start and end offsets are the same');
        return;
    }

    // Get the instance id
    var instance_id = document.getElementById("instance_id").value;
    console.log('[DEBUG] surroundSelectionOverlay: Instance ID:', instance_id);

    if (window.getSelection) {
        var sel = window.getSelection();

        // Check that we're labeling something in the original text that
        // we want to annotate
        if (!sel.anchorNode.parentElement) {
            console.log('[DEBUG] surroundSelectionOverlay: No anchor node parent element');
            return;
        }

        // Otherwise, we're going to be adding a new span annotation, if
        // the user has selected some non-empty part of the text
        if (sel.rangeCount && sel.toString().trim().length > 0) {
            console.log('[DEBUG] surroundSelectionOverlay: Valid selection found, creating span');

            // Get the selection text as a string
            var selText = window.getSelection().toString().trim();
            console.log('[DEBUG] surroundSelectionOverlay: Selected text:', selText);

            // Get the offsets for the server using the overlay approach
            var startEnd = getSelectionIndicesOverlay();
            console.log('[DEBUG] surroundSelectionOverlay: Selection indices:', startEnd);

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

            console.log('[DEBUG] surroundSelectionOverlay: Sending span annotation request:', post_req);

            // Send the post request
            fetch("/updateinstance", {
                method: "POST",
                body: JSON.stringify(post_req),
                credentials: "same-origin",
                headers: {
                    "Content-type": "application/json; charset=UTF-8",
                },
            }).then(response => {
                if (response.ok) {
                    // Reload the page to show the new span
                    location.reload();
                } else {
                    console.error('Failed to save span annotation');
                }
            });

            // Clear the current selection
            sel.empty();
            console.log('[DEBUG] surroundSelectionOverlay: Span creation request sent, page will reload');
        } else {
            console.log('[DEBUG] surroundSelectionOverlay: No valid selection found');
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
    console.log('[DEBUG] changeSpanLabelOverlay called:', {schema, spanLabel, spanTitle, spanColor, checked: checkbox.checked});

    // Listen for when the user has highlighted some text (only when the label is checked)
    document.onmouseup = function (e) {
        var senderElement = e.target;
        // Avoid the case where the user clicks the delete button
        if (senderElement.getAttribute("class") == "span-close") {
            e.stopPropagation();
            return true;
        }
        if (checkbox.checked) {
            console.log('[DEBUG] changeSpanLabelOverlay: Mouse up event - checkbox is checked, calling surroundSelectionOverlay');
            surroundSelectionOverlay(schema, spanLabel, spanTitle, spanColor);
        } else {
            console.log('[DEBUG] changeSpanLabelOverlay: Mouse up event - checkbox is not checked');
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
    console.log('[DEBUG] restoreSpanAnnotationsFromHTMLOverlay: found', found.length, 'spans:', found);
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
    console.log('[ROBUST SPAN] Initializing robust span annotation system');

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
        console.log('[ROBUST SPAN] Loaded colors:', spanColors);
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

    console.log('[ROBUST SPAN] Text selection handlers set up');
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
        console.log('[ROBUST SPAN] No active span label selected');
        return;
    }

    const range = selection.getRangeAt(0);
    const selectedText = selection.toString().trim();
    if (!selectedText) return;

    // Calculate positions using original text
    const start = getRobustTextPosition(selectedText, range);
    const end = start + selectedText.length;

    console.log('[ROBUST SPAN] Creating span:', {
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
    console.log('[ROBUST SPAN] Multiple occurrences found, using first:', indices[0]);
    return indices[0];
}

/**
 * Create a new span annotation using the robust approach
 */
async function createRobustSpanAnnotation(spanText, start, end, label) {
    try {
        console.log('[ROBUST SPAN] Creating annotation:', { spanText, start, end, label });

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
            console.log('[ROBUST SPAN] Span annotation created successfully');
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

    console.log('[ROBUST SPAN] Rendering spans:', spanAnnotations);

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
        console.log('[ROBUST SPAN] Deleting span:', annotationId);

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
            console.log('[ROBUST SPAN] Span annotation deleted successfully');
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
document.addEventListener('DOMContentLoaded', function() {
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
        console.log('[SPAN DELETE] Deleting span:', { annotationId, label, start, end });

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
            console.log('[SPAN DELETE] Span annotation deleted successfully');
            // Reload the instance to show the updated state
            await loadCurrentInstance();
        } else {
            console.error('[SPAN DELETE] Failed to delete span annotation:', await response.text());
        }
    } catch (error) {
        console.error('[SPAN DELETE] Error deleting span annotation:', error);
    }
}