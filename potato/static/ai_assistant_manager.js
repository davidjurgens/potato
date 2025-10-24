class AIAssistantManager {
    constructor() {
        this.loadingStates = new Set();
        this.activeTooltips = new Set();

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

            // If clicked outside tooltips and AI helper elements, close all tooltips
            if (!clickedTooltip && !clickedAiHelper) {
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

                // Add new ai suggestion
                if (clickedHint && node.contains(clickedHint)) {
                    event.stopPropagation();
                    event.preventDefault();
                    this.getAiAssistantDefault("hint", annotationId, tooltip);
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
                // const raw = await response.text();
                // try {
                //     data.res = JSON.parse(raw);
                //     data.type = "json";
                // } catch (error) {
                //     data.res = raw;
                //     data.type = "text";
                // }
            }
            return data;
        } catch (error) {
            console.error('Fetch error:', error);
            throw error;
        }
    }

    startLoading(tooltip, assistantType) {
        if (!tooltip) return;

        this.closeOtherTooltips(tooltip);
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

    async getAiAssistantDefault(assistantType, annotationId, tooltip) {
        if (!tooltip) {
            console.error('Tooltip element not found');
            return;
        }

        try {
            this.startLoading(tooltip, assistantType);
            const data = await this.fetchAssistantData(assistantType, annotationId);
            this.renderAssistant(tooltip, assistantType, data);
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

    renderAssistant(tooltip, assistantType, data) {
        let content = '';

        if (data.type === "json") {
            switch (assistantType) {
                case 'hint':
                    content = this.renderHint(data.res);
                    break;
                case 'keyword':
                    content = this.renderKeyword(data.res);
                    break;
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

    renderKeyword(data) {
        return `
            <div class="keyword-section">
                <div class="content-item">
                    <span class="label">Keywords:</span>
                    <span class="value">${data.keywords || 'No keywords available'}</span>
                </div>
            </div>
        `;
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

    async getAiAssistantName() {
        document.querySelectorAll('.annotation-form').forEach(async (node) => {
            const aiHelp = node.querySelector(".ai-help");
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
                console.log(error);
                aiHelp.innerHTML = '<span class="error">Error loading AI assistant</span>';
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
    }

    closeOtherTooltips(currentTooltip) {
        this.activeTooltips.forEach(tooltip => {
            if (currentTooltip !== tooltip) {
                this.hideTooltip(tooltip);
            }
        });
    }
}

export { AIAssistantManager };