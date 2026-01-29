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
        this.colors = {}; // Label colors loaded from API

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
            rationale: {
                apiEndpoint: '/api/get_ai_suggestion',
                loadingText: 'Loading rationales...',
                errorText: 'Failed to load rationales',
                className: 'rationale-tooltip'
            },
        };

        this.init();
    }

    init() {
        this.loadColors();
        this.setupEventDelegation();
        this.setupClickOutside();
    }

    /**
     * Load label colors from the server API
     */
    async loadColors() {
        try {
            const response = await fetch('/api/colors');
            if (response.ok) {
                this.colors = await response.json();
                console.log('[AIAssistant] Colors loaded:', this.colors);
            }
        } catch (error) {
            console.warn('[AIAssistant] Error loading colors:', error);
        }
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
            // Note: We DON'T capture tooltip here because getAiAssistantName() replaces
            // the aiHelp innerHTML later, which creates a new tooltip element.
            // Instead, we query for the tooltip fresh in the click handler.

            node.addEventListener("click", (event) => {
                const clickedHint = event.target.closest('.hint');
                const clickKeyword = event.target.closest('.keyword');
                const clickedRationale = event.target.closest('.rationale');

                // Query tooltip fresh each time - it may have been replaced by getAiAssistantName()
                const tooltip = node.querySelector('.tooltip');

                console.log('[AIAssistant] Click detected on ai-help:', {
                    target: event.target.className,
                    clickedHint: !!clickedHint,
                    clickKeyword: !!clickKeyword,
                    clickedRationale: !!clickedRationale,
                    annotationId,
                    hasTooltip: !!tooltip
                });

                event.stopPropagation();
                event.preventDefault();

                // Add new ai suggestion
                if (clickedHint && node.contains(clickedHint)) {
                    this.toggleAssistant("hint", annotationId, tooltip);
                } else if (clickKeyword && node.contains(clickKeyword)) {
                    this.toggleAssistant("keyword", annotationId, tooltip);
                } else if (clickedRationale && node.contains(clickedRationale)) {
                    this.toggleAssistant("rationale", annotationId, tooltip);
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
                data.res = await response.text();
                data.type = "text";
            }
            return data;
        } catch (error) {
            console.error('Fetch error:', error);
            throw error;
        }
    }

    positionTooltip(tooltip) {
        // Get the parent ai-help element to position relative to
        const aiHelp = tooltip.closest('.ai-help');
        console.log('[AIAssistant] positionTooltip called, aiHelp:', aiHelp);
        if (!aiHelp) {
            console.log('[AIAssistant] No aiHelp found, cannot position');
            return;
        }

        const rect = aiHelp.getBoundingClientRect();
        const tooltipRect = tooltip.getBoundingClientRect();
        console.log('[AIAssistant] aiHelp rect:', rect);
        console.log('[AIAssistant] tooltip rect:', tooltipRect);

        // Position below the button, centered
        let top = rect.bottom + 8; // 8px gap below the button
        let left = rect.left + (rect.width / 2) - (tooltipRect.width / 2);

        // Keep tooltip within viewport
        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;

        // Adjust horizontal position if needed
        if (left < 10) left = 10;
        if (left + tooltipRect.width > viewportWidth - 10) {
            left = viewportWidth - tooltipRect.width - 10;
        }

        // If tooltip would go below viewport, position above the button
        if (top + tooltipRect.height > viewportHeight - 10) {
            top = rect.top - tooltipRect.height - 8;
        }

        console.log('[AIAssistant] Setting tooltip position:', { top, left });
        tooltip.style.top = `${top}px`;
        tooltip.style.left = `${left}px`;
        console.log('[AIAssistant] Tooltip computed style:', window.getComputedStyle(tooltip).cssText.substring(0, 200));
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

        // Position the tooltip after adding content
        requestAnimationFrame(() => this.positionTooltip(tooltip));
    }

    toggleAssistant(assistantType, annotationId, tooltip) {
        console.log('[AIAssistant] toggleAssistant called:', { assistantType, annotationId, hasTooltip: !!tooltip });

        if (assistantType == "keyword") {
            console.log('[AIAssistant] Keyword clicked, checking spanManager:', {
                spanManagerExists: !!window.spanManager,
                inAiSpans: window.spanManager?.inAiSpans?.(annotationId)
            });
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
        console.log('[AIAssistant] getAiAssistantDefault called:', { assistantType, annotationId, hasTooltip: !!tooltip });

        if (!tooltip) {
            console.error('Tooltip element not found');
            return;
        }

        // Track AI request
        if (window.interactionTracker) {
            window.interactionTracker.trackAIRequest(annotationId);
        }

        try {
            this.startLoading(tooltip, assistantType);
            console.log('[AIAssistant] Fetching data for:', assistantType);
            const data = await this.fetchAssistantData(assistantType, annotationId);
            console.log('[AIAssistant] Received data:', data);

            // Track AI response
            if (window.interactionTracker) {
                const suggestions = this.extractSuggestionsFromData(data);
                window.interactionTracker.trackAIResponse(annotationId, suggestions);
            }

            this.renderAssistant(tooltip, assistantType, data, annotationId);
        } catch (error) {
            console.error('Error getting AI assistant:', error);
            this.showError(tooltip, assistantType);
        }
    }

    /**
     * Extract suggestion values from AI response data for tracking
     */
    extractSuggestionsFromData(data) {
        if (!data || !data.res) return [];

        if (data.type === "json") {
            const res = data.res;
            const suggestions = [];

            // Extract suggestive_choice if present
            if (res.suggestive_choice) {
                suggestions.push(res.suggestive_choice);
            }

            // Extract keywords if present
            if (res.keywords && Array.isArray(res.keywords)) {
                suggestions.push(...res.keywords.map(k => k.label || k.name || k));
            }

            return suggestions;
        }

        return [];
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
                case 'rationale':
                    content = this.renderRationale(data.res);
                    break;
                default:
                    content = '<div>Unknown assistant type</div>';
            }
        } else {
            content = data.res;
        }


        console.log('[AIAssistant] Setting tooltip content:', content);
        tooltip.innerHTML = `
            <div class="assistant-content">
                ${content}
            </div>
        `;
        console.log('[AIAssistant] Tooltip innerHTML set, tooltip element:', tooltip);

        this.activeTooltips.add(tooltip);
        console.log(this.activeTooltips);

        // Position the tooltip after content is set
        requestAnimationFrame(() => this.positionTooltip(tooltip));
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
        console.log('[AIAssistant] renderKeyword called:', { data, annotationId });

        // Get the text-content element (not instance-text) to match positioning calculations
        // #instance-text contains both #text-content and #span-overlays, which causes offset mismatches
        const textContent = document.getElementById('text-content');
        if (!textContent) {
            console.error('[AIAssistant] text-content element not found');
            return;
        }

        const text = textContent.textContent || textContent.innerText;
        console.log('[AIAssistant] Text content length:', text.length);

        // Parse the new label_keywords format
        const labelKeywords = data.label_keywords;
        if (!labelKeywords || !Array.isArray(labelKeywords)) {
            console.error('[AIAssistant] Invalid label_keywords format:', data);
            return;
        }

        // Get the annotation form to find the schema name
        // The form's id attribute is the schema name (e.g., "sentiment")
        const annotationForm = document.querySelector(`.annotation-form[data-annotation-id="${annotationId}"]`);
        const schemaName = annotationForm?.id || annotationForm?.dataset.schemaName || 'default';

        // Find keywords in text and create highlight data
        const highlights = [];
        console.log('[AIAssistant] Processing label_keywords:', labelKeywords);

        labelKeywords.forEach(({ label, keywords }) => {
            if (!keywords || !Array.isArray(keywords)) {
                console.log('[AIAssistant] Skipping label with no keywords:', label);
                return;
            }

            console.log(`[AIAssistant] Finding keywords for label "${label}":`, keywords);

            keywords.forEach(keyword => {
                if (!keyword || typeof keyword !== 'string') return;

                // Find all occurrences of this keyword in the text (case-insensitive)
                const lowerText = text.toLowerCase();
                const lowerKeyword = keyword.toLowerCase().trim();
                let startIndex = 0;

                while ((startIndex = lowerText.indexOf(lowerKeyword, startIndex)) !== -1) {
                    const foundText = text.substring(startIndex, startIndex + keyword.length);
                    console.log(`[AIAssistant] Found "${foundText}" at position ${startIndex}-${startIndex + keyword.length}`);
                    highlights.push({
                        label: label,
                        start: startIndex,
                        end: startIndex + keyword.length,
                        text: foundText,
                        schema: schemaName
                    });
                    startIndex += keyword.length;
                }
            });
        });

        console.log('[AIAssistant] Total highlights found:', highlights.length, highlights);

        if (highlights.length === 0) {
            console.log('[AIAssistant] No keywords found in text');
            return;
        }

        // Always use spanManager for keyword highlighting
        // This ensures consistent positioning and z-index with other overlays
        if (window.spanManager && typeof window.spanManager.insertAiKeywordHighlights === 'function') {
            window.spanManager.insertAiKeywordHighlights(highlights, annotationId);
        } else {
            console.error('[AIAssistant] spanManager.insertAiKeywordHighlights not available - cannot display keyword highlights');
        }
    }

    /**
     * Get the color for a label from the loaded colors or schema colors
     */
    getLabelColor(label, schemaName) {
        // Default colors for common labels
        const defaultColors = {
            'positive': 'rgba(34, 197, 94, 0.8)',   // green
            'negative': 'rgba(239, 68, 68, 0.8)',   // red
            'neutral': 'rgba(156, 163, 175, 0.8)', // gray
            'yes': 'rgba(34, 197, 94, 0.8)',        // green
            'no': 'rgba(239, 68, 68, 0.8)',         // red
            'maybe': 'rgba(245, 158, 11, 0.8)',     // amber
        };

        // 1. Try to get from AIAssistantManager's loaded colors
        if (this.colors && schemaName && this.colors[schemaName]) {
            const schemaColors = this.colors[schemaName];
            if (schemaColors[label]) {
                return schemaColors[label];
            }
        }

        // 2. Try to get from spanManager colors (if available)
        if (window.spanManager && window.spanManager.colors) {
            const schemaColors = window.spanManager.colors[schemaName];
            if (schemaColors && schemaColors[label]) {
                const color = schemaColors[label];
                if (color.startsWith('(')) {
                    return `rgba${color.replace(')', ', 0.8)')}`;
                }
                return color;
            }
        }

        // 3. Try named default colors (case-insensitive)
        const lowerLabel = label.toLowerCase();
        if (defaultColors[lowerLabel]) {
            return defaultColors[lowerLabel];
        }

        // 4. Fallback to amber
        return 'rgba(245, 158, 11, 0.8)';
    }

    renderRationale(data) {
        console.log('[AIAssistant] renderRationale called with data:', data);
        console.log('[AIAssistant] rationales:', data.rationales);

        // Handle error responses
        if (data.error) {
            return `
                <div class="rationale-section">
                    <div class="content-item">
                        <span class="label">Error:</span>
                        <span class="value">${this.escapeHtml(data.error)}</span>
                    </div>
                </div>
            `;
        }

        const rationales = data.rationales || [];

        if (rationales.length === 0) {
            return `
                <div class="rationale-section">
                    <div class="content-item">
                        <span class="label">Rationale:</span>
                        <span class="value">No rationales available</span>
                    </div>
                </div>
            `;
        }

        const rationaleItems = rationales.map(r => `
            <div class="rationale-item">
                <span class="rationale-label">${this.escapeHtml(r.label)}:</span>
                <span class="rationale-reasoning">${this.escapeHtml(r.reasoning)}</span>
            </div>
        `).join('');

        return `
            <div class="rationale-section">
                <div class="rationale-header">Rationales for each label:</div>
                ${rationaleItems}
            </div>
        `;
    }

    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
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
        console.log('[AIAssistant] getAiAssistantName() called');
        const forms = document.querySelectorAll('.annotation-form');
        console.log('[AIAssistant] Found annotation forms:', forms.length);

        forms.forEach(async (node) => {
            const aiHelp = node.querySelector(".ai-help");
            const annotationId = node.getAttribute("data-annotation-id");
            aiDebugLog('[AIAssistant] Looking for .ai-help in form:', node.id, 'annotationId:', annotationId, '- Found:', aiHelp !== null);

            // Skip if no ai-help element exists (e.g., video/audio annotation forms)
            if (!aiHelp) {
                aiDebugLog('[AIAssistant] No .ai-help element found, skipping');
                return;
            }

            // Skip if AI assistant buttons are already loaded (check for both spellings)
            const existingButtons = aiHelp.querySelector('.ai-assistant-containter, .ai-assistant-container');
            if (existingButtons) {
                aiDebugLog('[AIAssistant] AI buttons already loaded, skipping');
                return;
            }

            // Mark as loading to prevent duplicate requests
            if (aiHelp.dataset.aiLoading === 'true') {
                aiDebugLog('[AIAssistant] Already loading, skipping duplicate request');
                return;
            }
            aiHelp.dataset.aiLoading = 'true';

            aiDebugLog('[AIAssistant] Fetching AI assistant for annotationId:', annotationId);

            const params = new URLSearchParams({
                annotationId: annotationId
            });

            try {
                const response = await fetch(`/api/ai_assistant?${params.toString()}`, {
                    method: 'GET',
                    headers: { 'Content-Type': 'application/json' }
                });
                const data = await response.text();
                aiDebugLog('[AIAssistant] Response received, data length:', data?.length);

                if (!data || !data.trim()) {
                    aiDebugLog('[AIAssistant] Empty response, not inserting');
                    aiHelp.dataset.aiLoading = 'false';
                    return;
                }

                // Double-check no buttons were added while we were fetching
                const buttonsAddedDuringFetch = aiHelp.querySelector('.ai-assistant-containter, .ai-assistant-container');
                if (buttonsAddedDuringFetch) {
                    aiDebugLog('[AIAssistant] Buttons were added during fetch, skipping');
                    aiHelp.dataset.aiLoading = 'false';
                    return;
                }

                aiDebugLog('[AIAssistant] Inserting HTML and removing "none" class');
                aiHelp.classList.remove("none");

                // Clear any existing content before inserting (except tooltip)
                const tooltip = aiHelp.querySelector('.tooltip');
                const tooltipHTML = tooltip ? tooltip.outerHTML : '<div class="tooltip"></div>';
                aiHelp.innerHTML = data + tooltipHTML;

                aiDebugLog('[AIAssistant] HTML inserted successfully');
            } catch (error) {
                console.error('[AIAssistant] Error fetching AI assistant:', error);
                if (aiHelp) {
                    aiHelp.innerHTML = '<span class="error">Error loading AI assistant</span><div class="tooltip"></div>';
                }
            } finally {
                aiHelp.dataset.aiLoading = 'false';
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