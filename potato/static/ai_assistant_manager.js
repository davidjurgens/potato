class AIAssistantManager {
    constructor() {
        this.loadingStates = new Set();
        this.activeTooltips = new Set();
        this.highlight = new Highlight();
        this.keywordHighlightStates = new Map();

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

        window.spanManager.clearAiSpans()
    }

    closeOtherTooltips(currentTooltip) {
        this.activeTooltips.forEach(tooltip => {
            if (currentTooltip !== tooltip) {
                this.hideTooltip(tooltip);
            }
        });
    }
}

// class Highlight {
//     constructor() {
//         this.colors = {};
//     }

//     async loadColors() {
//         try {
//             const response = await fetch('/api/colors');
//             if (!response.ok) {
//                 throw new Error(`HTTP ${response.status}: ${response.statusText}`);
//             }
//             this.colors = await response.json();
//             console.log('SpanManager: Colors loaded:', this.colors);
//         } catch (error) {
//             console.error('SpanManager: Error loading colors:', error);
//         }
//     }

//     highlightSpans(spans, textContainer, textContent, spanOverlays) {

//         spanOverlays.innerHTML = '';

//         if (!spans || spans.length === 0) {
//             return;
//         }

//         // Get container position for relative positioning
//         const containerRect = textContainer.getBoundingClientRect();

//         const sortedSpans = [...spans].sort((a, b) => a.start - b.start);

//         sortedSpans.forEach((span, index) => {
//             this.renderSpanOverlay(span, textContent, spanOverlays, containerRect);
//         });
//     }

//     renderSpanOverlay(span, textContent, spanOverlays, containerRect) {
//         console.log("fpowjeaf", span)
//         const textNode = textContent.firstChild;
//         if (!textNode || textNode.nodeType !== Node.TEXT_NODE) {
//             console.error('No text node found in textContent');
//             return;
//         }
//         const rects = this.getCharRangeBoundingRect(textContent, span.start + 21, span.end + 21);
//         if (!rects || rects.length === 0) {
//             console.warn('Could not get bounding rect for span', span);
//             return;
//         }

//         let sharedTooltip = null;
//         if (span.reasoning) {
//             sharedTooltip = document.createElement('div');
//             sharedTooltip.className = 'span-hover-tip';
//             sharedTooltip.textContent = span.reasoning;
//             sharedTooltip.style.position = 'fixed';
//             sharedTooltip.style.display = 'none';
//             sharedTooltip.style.maxWidth = '320px';
//             sharedTooltip.style.background = 'rgba(0, 0, 0, 0.92)';
//             sharedTooltip.style.color = '#fff';
//             sharedTooltip.style.padding = '6px 8px';
//             sharedTooltip.style.borderRadius = '4px';
//             sharedTooltip.style.fontSize = '12px';
//             sharedTooltip.style.lineHeight = '1.35';
//             sharedTooltip.style.zIndex = '2000';
//             sharedTooltip.style.pointerEvents = 'none';
//             sharedTooltip.style.whiteSpace = 'normal';
//             sharedTooltip.style.boxShadow = '0 4px 12px rgba(0, 0, 0, 0.25)';
//             document.body.appendChild(sharedTooltip);
//         }

//         const createOverlays = () => {
//             rects.forEach((rect, rectIndex) => {
//                 const overlay = document.createElement('div');
//                 overlay.className = 'span-overlay';
//                 overlay.dataset.spanId = span.id;
//                 overlay.dataset.start = span.start;
//                 overlay.dataset.end = span.end;
//                 overlay.dataset.label = span.label;
//                 overlay.style.position = 'absolute';
//                 overlay.style.pointerEvents = 'auto';
//                 overlay.style.cursor = 'pointer';

//                 const left = rect.left - containerRect.left;
//                 const top = rect.top - containerRect.top;
//                 const width = Math.max(1, rect.right - rect.left);
//                 const height = Math.max(1, rect.bottom - rect.top);
//                 overlay.style.left = `${left}px`;
//                 overlay.style.top = `${top}px`;
//                 overlay.style.width = `${width}px`;
//                 overlay.style.height = `${height}px`;
//                 overlay.style.zIndex = '10';
//                 // Apply color
//                 const baseColor = this.colors[span.schema]?.[span.label] || '#ffff03';
//                 const backgroundColor = this.addTransparency(baseColor, 0.65); // 65% opacity
//                 overlay.style.backgroundColor = backgroundColor;

//                 if (rectIndex === 0) {
//                     const label = document.createElement('span');

//                     label.className = 'span-label';
//                     label.textContent = span.label;
//                     label.style.position = 'absolute';
//                     label.style.top = '-25px';
//                     label.style.left = '0';
//                     label.style.fontSize = '11px';
//                     label.style.fontWeight = 'bold';
//                     label.style.backgroundColor = 'rgba(0,0,0,0.9)';
//                     label.style.color = 'white';
//                     label.style.padding = '3px 6px';
//                     label.style.borderRadius = '4px';
//                     label.style.whiteSpace = 'nowrap';
//                     label.style.pointerEvents = 'auto';
//                     label.style.zIndex = '1000';
//                     label.style.display = 'inline-flex';
//                     label.style.alignItems = 'center';
//                     label.style.gap = '6px';
//                     overlay.appendChild(label);
//                 }

//                 if (sharedTooltip) {
//                     overlay.addEventListener('mouseenter', (e) => {
//                         sharedTooltip.style.display = 'block';
//                         // Position tooltip near cursor with offset
//                         sharedTooltip.style.left = (e.clientX + 15) + 'px';
//                         sharedTooltip.style.top = (e.clientY + 15) + 'px';
//                     });

//                     overlay.addEventListener('mousemove', (e) => {
//                         sharedTooltip.style.left = (e.clientX + 15) + 'px';
//                         sharedTooltip.style.top = (e.clientY + 15) + 'px';
//                     });

//                     overlay.addEventListener('mouseleave', (e) => {
//                         sharedTooltip.style.display = 'none';
//                     });
//                 }

//                 spanOverlays.appendChild(overlay);
//             });
//         };
//         createOverlays();
//     }

//     addTransparency(color, alpha = 0.65) {
//         // If color already has alpha channel, return as is
//         if (color.startsWith('rgba')) {
//             return color;
//         }

//         // If color is in rgb format
//         if (color.startsWith('rgb(')) {
//             return color.replace('rgb(', 'rgba(').replace(')', `, ${alpha})`);
//         }

//         // If color is in hex format
//         if (color.startsWith('#')) {
//             // Remove # and handle 3 or 6 character hex
//             let hex = color.slice(1);

//             // Convert 3-char hex to 6-char
//             if (hex.length === 3) {
//                 hex = hex.split('').map(char => char + char).join('');
//             }

//             // Convert hex to rgb
//             const r = parseInt(hex.slice(0, 2), 16);
//             const g = parseInt(hex.slice(2, 4), 16);
//             const b = parseInt(hex.slice(4, 6), 16);

//             return `rgba(${r}, ${g}, ${b}, ${alpha})`;
//         }

//         // Fallback: return color as is
//         return color;
//     }

//     getCharRangeBoundingRect(container, start, end) {
//         const textNode = container.firstChild;
//         if (!textNode || textNode.nodeType !== Node.TEXT_NODE) return null;

//         const range = document.createRange();
//         range.setStart(textNode, start);
//         range.setEnd(textNode, end);

//         let rects = range.getClientRects();

//         if (rects.length === 0) return null;
//         return Array.from(rects);
//     }
// }

export { AIAssistantManager };