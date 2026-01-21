// Debug logging utility - respects the debug setting from server config
function aiDebugLog(...args) {
    if (window.config && window.config.debug) {
        console.log(...args);
    }
}

class AIAssistantManager {
    constructor() {
        this.loadingStates = new Set();
        this.activeTooltips = new Set();
        this.keywordHighlightStates = new Map();
        this.highlightedLabels = new Map(); // Track highlighted labels by annotationId

        // Add new AI assistant types here
        this.assistantConfig = {
            hint: {
                apiEndpoint: '/api/get_ai_suggestion',
                loadingText: 'Loading hint...',
                errorText: 'Failed to load hint',
                className: 'hint-tooltip'
            },
            keyword: {
                apiEndpoint: '/api/get_ai_suggestion',
                loadingText: 'Loading keywords...',
                errorText: 'Failed to load keywords',
                className: 'keyword-tooltip'
            },
            random: {
                apiEndpoint: '/api/get_ai_suggestion',
                loadingText: 'Loading random...',
                errorText: 'Failed to load random',
                className: 'random-tooltip'
            },
        };

        this.init();
    }

    init() {
        this.setupEventDelegation();
        this.setupClickOutside();
    }

    setupClickOutside() {
        document.addEventListener('click', (event) => {
            // Don't close if clicking on a tooltip or its contents
            const clickedTooltip = event.target.closest('.tooltip');
            const clickedAiHelper = event.target.closest('.ai-help, .ai-assistant-container');
            const clickedAiOverlay = event.target.closest('#instance-text');
            const clickedOption = event.target.closest(".shadcn-span-option");

            // If clicked outside tooltips and AI helper elements, close all tooltips
            if (!clickedTooltip && !clickedAiHelper && !clickedAiOverlay && !clickedOption) {
                this.closeAllTooltips();
            }
        });

        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') {
                this.closeAllTooltips();
            }
        });
    }

    setupEventDelegation() {
        document.querySelectorAll('.ai-help').forEach((node, index) => {
            const annotationForm = node.closest('.annotation-form');
            if (!annotationForm) return;

            const annotationId = annotationForm.getAttribute("data-annotation-id");
            const tooltip = node.querySelector('.tooltip');

            node.addEventListener("click", (event) => {
                const clickedHint = event.target.closest('.hint');
                const clickKeyword = event.target.closest('.keyword');
                event.stopPropagation();
                event.preventDefault();

                // Add new ai suggestion
                if (clickedHint && node.contains(clickedHint)) {
                    this.toggleAssistant("hint", annotationId, tooltip);
                } else if (clickKeyword && node.contains(clickKeyword)) {
                    this.toggleAssistant("keyword", annotationId, tooltip);
                }

            });
        });
    }

    async fetchAssistantData(assistantType, annotationId) {
        const config = this.assistantConfig[assistantType];
        if (!config) {
            throw new Error(`Unknown assistant type: ${assistantType}`);
        }

        const params = new URLSearchParams({
            annotationId: annotationId,
            aiAssistant: assistantType
        });

        try {
            const response = await fetch(`${config.apiEndpoint}?${params.toString()}`, {
                method: 'GET',
                headers: { 'Content-Type': 'application/json' }
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const contentType = response.headers.get("content-type");
            let data = {}
            if (contentType && contentType.includes("application/json")) {
                data.res = await response.json();
                data.type = "json";
            } else {
                data.res = await response.json();
                data.type = "text";
            }
            return data;
        } catch (error) {
            console.error('Fetch error:', error);
            throw error;
        }
    }

    startLoading(tooltip, assistantType) {
        if (!tooltip || assistantType == "keyword") return;

        // this.closeOtherTooltips(tooltip);
        const config = this.assistantConfig[assistantType];

        tooltip.classList.add('active');
        tooltip.classList.add(config.className);
        tooltip.innerHTML = `
            <div class="loading">
                <span>${config.loadingText}</span>
            </div>
        `;

        this.activeTooltips.add(tooltip);
    }

    toggleAssistant(assistantType, annotationId, tooltip) {
        if (assistantType == "keyword") {
            if (window.spanManager.inAiSpans(annotationId)) {
                window.spanManager.deleteOneAiSpan(annotationId);
                return;
            }
            // const isCurrentlyActive = this.keywordHighlightStates.get(annotationId);

            // if (isCurrentlyActive) {
            //     window.spanManager.renderSpans();
            //     this.keywordHighlightStates.set(annotationId, false);
            //     return;
            // }
            // this.keywordHighlightStates.set(annotationId, true);
        }
        if (tooltip.classList.contains('active') &&
            tooltip.classList.contains(this.assistantConfig[assistantType].className)) {
            this.hideTooltip(tooltip);
            return;
        }

        this.getAiAssistantDefault(assistantType, annotationId, tooltip);
    }


    async getAiAssistantDefault(assistantType, annotationId, tooltip) {
        if (!tooltip) {
            console.error('Tooltip element not found');
            return;
        }

        try {
            this.startLoading(tooltip, assistantType);
            const data = await this.fetchAssistantData(assistantType, annotationId);
            console.log("2132132114213221")
            this.renderAssistant(tooltip, assistantType, data, annotationId);
            console.log("eerrrererrereereerr")
        } catch (error) {
            console.error('Error getting AI assistant:', error);
            this.showError(tooltip, assistantType);
        }
    }

    showError(tooltip, assistantType) {
        const config = this.assistantConfig[assistantType];
        tooltip.innerHTML = `
            <div class="error">
                <span>${config.errorText}</span>
            </div>
        `;
    }

    renderAssistant(tooltip, assistantType, data, annotationId) {
        let content = '';

        if (data.type === "json") {
            switch (assistantType) {
                case 'hint':
                    content = this.renderHint(data.res);
                    // Highlight the suggested label if present
                    if (data.res.suggestive_choice) {
                        this.highlightSuggestedLabel(annotationId, data.res.suggestive_choice);
                    }
                    break;
                case 'keyword':
                    this.renderKeyword(data.res, annotationId);
                    return;
                default:
                    content = '<div>Unknown assistant type</div>';
            }
        } else {
            content = data.res;
        }


        tooltip.innerHTML = `
            <div class="assistant-content">
                ${content}
            </div>
        `;

        this.activeTooltips.add(tooltip);
        console.log(this.activeTooltips);
    }

    renderHint(data) {
        return `
            <div class="hint-section">
                <div class="content-item">
                    <span class="label">Hint:</span>
                    <span class="value">${data.hint || 'No hint available'}</span>
                </div>
                ${data.suggestive_choice ? `
                    <div class="content-item">
                        <span class="label">Suggestion:</span>
                        <span class="value suggestion">${data.suggestive_choice}</span>
                    </div>
                ` : ''}
            </div>
        `;
    }

    renderKeyword(data, annotationId) {
        window.spanManager.insertAiSpans(data["keywords"], annotationId);
    }

    renderRandom(data) {
        return `
            <div class="random-section">
                <div class="content-item">
                    <span class="label">Random Suggestion:</span>
                    <span class="value">${data.random || 'No random suggestion available'}</span>
                </div>
            </div>
        `;
    }

    /**
     * Highlight a suggested label on the annotation form
     * @param {string} annotationId - The annotation ID
     * @param {string|number} suggestedLabel - The suggested label value
     */
    highlightSuggestedLabel(annotationId, suggestedLabel) {
        aiDebugLog('[AIAssistant] highlightSuggestedLabel:', { annotationId, suggestedLabel });

        // Clear any existing highlights for this annotation
        this.clearLabelHighlights(annotationId);

        // Find the annotation form with this ID
        const annotationForm = document.querySelector(`.annotation-form[data-annotation-id="${annotationId}"]`);
        if (!annotationForm) {
            console.warn('[AIAssistant] Annotation form not found for ID:', annotationId);
            return;
        }

        // Convert suggestedLabel to string for comparison
        const suggestedLabelStr = String(suggestedLabel).toLowerCase().trim();

        // Find all label inputs (radio buttons, checkboxes) in the form
        const labelInputs = annotationForm.querySelectorAll('input[type="radio"], input[type="checkbox"]');
        const highlightedElements = [];

        labelInputs.forEach(input => {
            // Get the label text - check value, id, or associated label element
            const inputValue = input.value?.toLowerCase().trim();
            const inputId = input.id?.toLowerCase().trim();

            // Also check the text of the associated label element
            const labelElement = annotationForm.querySelector(`label[for="${input.id}"]`);
            const labelText = labelElement?.textContent?.toLowerCase().trim();

            // Check if this input matches the suggested label
            const isMatch = inputValue === suggestedLabelStr ||
                            inputId?.includes(suggestedLabelStr) ||
                            labelText?.includes(suggestedLabelStr) ||
                            suggestedLabelStr.includes(inputValue);

            if (isMatch) {
                aiDebugLog('[AIAssistant] Found matching label:', { inputValue, labelText, suggestedLabelStr });

                // Add highlight class to the input
                input.classList.add('ai-suggested');

                // Add highlight class to the associated label element
                if (labelElement) {
                    labelElement.classList.add('ai-suggested-label');

                    // Add a sparkle/star indicator
                    if (!labelElement.querySelector('.ai-suggestion-indicator')) {
                        const indicator = document.createElement('span');
                        indicator.className = 'ai-suggestion-indicator';
                        indicator.innerHTML = ' &#x2728;'; // Sparkle emoji
                        indicator.title = 'AI Suggested';
                        indicator.style.marginLeft = '4px';
                        labelElement.appendChild(indicator);
                    }

                    highlightedElements.push(labelElement);
                }

                // Also highlight the parent container if it exists
                const parentOption = input.closest('.shadcn-radio-option, .shadcn-checkbox-option, .shadcn-span-option, .option-item');
                if (parentOption) {
                    parentOption.classList.add('ai-suggested-option');
                    highlightedElements.push(parentOption);
                }

                highlightedElements.push(input);
            }
        });

        // Store the highlighted elements for later cleanup
        if (highlightedElements.length > 0) {
            this.highlightedLabels.set(annotationId, highlightedElements);
            console.log(`[AIAssistant] Highlighted ${highlightedElements.length} elements for annotation ${annotationId}`);
        }
    }

    /**
     * Clear label highlights for a specific annotation
     * @param {string} annotationId - The annotation ID (optional, clears all if not provided)
     */
    clearLabelHighlights(annotationId = null) {
        if (annotationId) {
            const elements = this.highlightedLabels.get(annotationId);
            if (elements) {
                elements.forEach(el => {
                    el.classList.remove('ai-suggested', 'ai-suggested-label', 'ai-suggested-option');
                    const indicator = el.querySelector('.ai-suggestion-indicator');
                    if (indicator) {
                        indicator.remove();
                    }
                });
                this.highlightedLabels.delete(annotationId);
            }
        } else {
            // Clear all highlights
            this.highlightedLabels.forEach((elements, id) => {
                elements.forEach(el => {
                    el.classList.remove('ai-suggested', 'ai-suggested-label', 'ai-suggested-option');
                    const indicator = el.querySelector('.ai-suggestion-indicator');
                    if (indicator) {
                        indicator.remove();
                    }
                });
            });
            this.highlightedLabels.clear();
        }
    }

    async getAiAssistantName() {
        document.querySelectorAll('.annotation-form').forEach(async (node) => {
            const aiHelp = node.querySelector(".ai-help");
            // Skip if no ai-help element exists (e.g., video/audio annotation forms)
            if (!aiHelp) {
                return;
            }

            const annotationId = node.getAttribute("data-annotation-id");
            const params = new URLSearchParams({
                annotationId: annotationId
            });

            try {
                const response = await fetch(`/api/ai_assistant?${params.toString()}`, {
                    method: 'GET',
                    headers: { 'Content-Type': 'application/json' }
                });
                const data = await response.text();

                if (!data || !data.trim()) {
                    return;
                }
                aiHelp.classList.remove("none");
                aiHelp.insertAdjacentHTML('afterbegin', data);
            } catch (error) {
                aiDebugLog('[AIAssistant] Error fetching AI assistant:', error);
                if (aiHelp) {
                    aiHelp.innerHTML = '<span class="error">Error loading AI assistant</span>';
                }
            }
        });
    }

    // Utility methods
    isTooltipActive(tooltip) {
        return tooltip?.classList.contains('active') || false;
    }

    hideTooltip(tooltip) {
        if (!tooltip) return;

        tooltip.className = "tooltip";
        tooltip.innerHTML = '';
        this.activeTooltips.delete(tooltip);
    }

    closeAllTooltips() {
        this.activeTooltips.forEach(tooltip => {
            this.hideTooltip(tooltip);
        });

        // Clear AI spans if spanManager exists
        if (window.spanManager && typeof window.spanManager.clearAiSpans === 'function') {
            window.spanManager.clearAiSpans();
        }

        // Clear label highlights
        this.clearLabelHighlights();
    }

    closeOtherTooltips(currentTooltip) {
        this.activeTooltips.forEach(tooltip => {
            if (currentTooltip !== tooltip) {
                this.hideTooltip(tooltip);
            }
        });
    }
}