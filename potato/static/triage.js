/**
 * Triage Schema JavaScript
 *
 * Handles the binary accept/reject/skip triage interface for rapid data curation.
 * Features:
 * - Button click handling
 * - Keyboard shortcut support
 * - Auto-advance to next item
 * - Visual feedback on selection
 * - Progress tracking
 */

(function() {
    'use strict';

    // Debug logging helper
    function debugLog(...args) {
        if (window.config && window.config.debug) {
            console.log('[TRIAGE]', ...args);
        }
    }

    /**
     * Initialize triage handlers when DOM is ready
     */
    function initTriage() {
        debugLog('Initializing triage handlers');

        // Find all triage forms
        const triageForms = document.querySelectorAll('.annotation-form.triage');

        if (triageForms.length === 0) {
            debugLog('No triage forms found');
            return;
        }

        triageForms.forEach(form => {
            initTriageForm(form);
        });

        // Set up global keyboard handler for triage shortcuts
        setupTriageKeyboardHandler();

        // Update progress indicators if available
        updateTriageProgress();

        // Watch for changes to the progress counter (for AJAX navigation)
        setupProgressObserver();
    }

    /**
     * Initialize a single triage form
     */
    function initTriageForm(form) {
        const schemaName = form.getAttribute('data-schema-name');
        const autoAdvance = form.getAttribute('data-auto-advance') === 'true';

        debugLog(`Initializing triage form: ${schemaName}, auto-advance: ${autoAdvance}`);

        // Set up button click handlers
        const buttons = form.querySelectorAll('.triage-btn');
        buttons.forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                handleTriageSelection(form, this.getAttribute('data-value'), autoAdvance);
            });
        });

        // Load any existing value
        loadExistingTriageValue(form);
    }

    /**
     * Handle triage button selection
     */
    function handleTriageSelection(form, value, autoAdvance) {
        const schemaName = form.getAttribute('data-schema-name');
        debugLog(`Triage selection: ${value} for schema: ${schemaName}`);

        // Update hidden input
        const hiddenInput = form.querySelector('.triage-input');
        if (hiddenInput) {
            hiddenInput.value = value;

            // Trigger change event for annotation system
            hiddenInput.dispatchEvent(new Event('change', { bubbles: true }));

            // Call registerAnnotation if available (compatibility with potato annotation system)
            if (typeof window.registerAnnotation === 'function') {
                window.registerAnnotation(hiddenInput);
            }
        }

        // Update button visual states
        updateButtonStates(form, value);

        // Auto-advance if enabled
        if (autoAdvance) {
            debugLog('Auto-advancing to next item');
            // Small delay to allow visual feedback
            setTimeout(() => {
                advanceToNextItem();
            }, 150);
        }
    }

    /**
     * Update visual states of triage buttons
     */
    function updateButtonStates(form, selectedValue) {
        const buttons = form.querySelectorAll('.triage-btn');
        buttons.forEach(btn => {
            const btnValue = btn.getAttribute('data-value');
            if (btnValue === selectedValue) {
                btn.classList.add('selected');
                btn.setAttribute('aria-pressed', 'true');
            } else {
                btn.classList.remove('selected');
                btn.setAttribute('aria-pressed', 'false');
            }
        });
    }

    /**
     * Load existing triage value from hidden input
     */
    function loadExistingTriageValue(form) {
        const hiddenInput = form.querySelector('.triage-input');
        if (hiddenInput && hiddenInput.value) {
            debugLog(`Loading existing value: ${hiddenInput.value}`);
            updateButtonStates(form, hiddenInput.value);
        }
    }

    /**
     * Set up global keyboard handler for triage shortcuts
     */
    function setupTriageKeyboardHandler() {
        document.addEventListener('keydown', function(e) {
            // Don't handle if typing in text input
            const isTextInput = e.target.tagName === 'TEXTAREA' ||
                (e.target.tagName === 'INPUT' &&
                 e.target.type !== 'radio' &&
                 e.target.type !== 'checkbox' &&
                 e.target.type !== 'hidden');

            if (isTextInput) {
                return;
            }

            // Find active triage forms
            const triageForms = document.querySelectorAll('.annotation-form.triage');
            triageForms.forEach(form => {
                const buttons = form.querySelectorAll('.triage-btn');
                buttons.forEach(btn => {
                    const keyBind = btn.getAttribute('data-key');
                    if (keyBind && e.key.toLowerCase() === keyBind.toLowerCase()) {
                        e.preventDefault();
                        btn.click();
                    }
                });
            });
        });
    }

    /**
     * Advance to the next item in the annotation queue
     */
    function advanceToNextItem() {
        // Call navigateToNext directly instead of clicking the button
        // This ensures navigation works even if the button is temporarily disabled
        if (typeof window.navigateToNext === 'function') {
            debugLog('Calling navigateToNext() directly');
            window.navigateToNext();
        } else {
            // Fallback: Try clicking the next button
            const nextBtn = document.getElementById('next-btn');
            if (nextBtn) {
                debugLog('Clicking next button (fallback)');
                nextBtn.click();
            } else {
                debugLog('No navigation method available');
            }
        }
    }

    /**
     * Update progress indicators for triage forms
     */
    function updateTriageProgress() {
        // Try to get progress info from the page's progress counter element
        // which shows "finished/total_count" format
        const progressCounter = document.getElementById('progress-counter');
        let currentIndex = 0;
        let totalItems = 0;

        if (progressCounter) {
            const text = progressCounter.textContent.trim();
            const match = text.match(/(\d+)\s*\/\s*(\d+)/);
            if (match) {
                currentIndex = parseInt(match[1], 10);
                totalItems = parseInt(match[2], 10);
            }
        }

        // Fallback to window.config if available
        if (totalItems === 0 && window.config) {
            currentIndex = (window.config.currentIndex || 0) + 1;
            totalItems = window.config.totalItems || 0;
        }

        if (totalItems === 0) {
            // Hide progress indicators if no progress info available
            const progressContainers = document.querySelectorAll('.triage-progress');
            progressContainers.forEach(container => {
                container.style.display = 'none';
            });
            return;
        }

        const progressContainers = document.querySelectorAll('.triage-progress');
        progressContainers.forEach(container => {
            container.style.display = '';  // Ensure visible
            const currentSpan = container.querySelector('.triage-progress-current');
            const totalSpan = container.querySelector('.triage-progress-total');
            const progressFill = container.querySelector('.triage-progress-fill');

            if (currentSpan) {
                currentSpan.textContent = currentIndex;
            }
            if (totalSpan) {
                totalSpan.textContent = totalItems;
            }
            if (progressFill) {
                const percentage = (currentIndex / totalItems) * 100;
                progressFill.style.width = `${percentage}%`;
            }
        });
    }

    /**
     * Set up a MutationObserver to watch for progress counter changes
     * This handles AJAX-based navigation where the page doesn't fully reload
     */
    function setupProgressObserver() {
        const progressCounter = document.getElementById('progress-counter');
        if (!progressCounter) {
            debugLog('No progress counter found for observation');
            return;
        }

        // Create observer to watch for text content changes
        const observer = new MutationObserver(function(mutations) {
            mutations.forEach(function(mutation) {
                if (mutation.type === 'childList' || mutation.type === 'characterData') {
                    debugLog('Progress counter changed, updating triage progress');
                    updateTriageProgress();
                }
            });
        });

        // Observe the progress counter for changes
        observer.observe(progressCounter, {
            childList: true,
            characterData: true,
            subtree: true
        });

        debugLog('Progress observer set up');
    }

    /**
     * Programmatically set a triage value for a schema
     */
    function setTriageValue(schemaName, value) {
        const form = document.querySelector(`.annotation-form.triage[data-schema-name="${schemaName}"]`);
        if (form) {
            handleTriageSelection(form, value, false);
        }
    }

    /**
     * Get the current triage value for a schema
     */
    function getTriageValue(schemaName) {
        const form = document.querySelector(`.annotation-form.triage[data-schema-name="${schemaName}"]`);
        if (form) {
            const hiddenInput = form.querySelector('.triage-input');
            return hiddenInput ? hiddenInput.value : null;
        }
        return null;
    }

    // Expose API for external use
    window.triageManager = {
        init: initTriage,
        setValue: setTriageValue,
        getValue: getTriageValue,
        updateProgress: updateTriageProgress
    };

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initTriage);
    } else {
        // DOM already loaded
        initTriage();
    }

})();
