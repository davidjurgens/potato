/**
 * Entity Linking Module
 *
 * Provides functionality to link span annotations to external knowledge bases
 * like Wikidata and UMLS. Features include:
 * - Search modal for finding KB entities
 * - Entity details popup on hover
 * - Auto-search when spans are created
 * - Visual indicators for linked spans
 */

(function() {
    'use strict';

    // Module state
    const EntityLinking = {
        initialized: false,
        configuredKBs: [],
        currentSpanId: null,
        currentInstanceId: null,
        searchTimeout: null,
        modal: null,
        config: null
    };

    /**
     * Initialize the entity linking module
     */
    function init() {
        if (EntityLinking.initialized) {
            console.log('[EntityLinking] Already initialized');
            return;
        }

        console.log('[EntityLinking] Initializing...');

        // Check if entity linking is enabled for any schema
        const schemas = document.querySelectorAll('[data-entity-linking]');
        if (schemas.length === 0) {
            console.log('[EntityLinking] No schemas with entity linking enabled');
            return;
        }

        // Parse config from the first schema (they should all be the same)
        try {
            const configStr = schemas[0].getAttribute('data-entity-linking');
            EntityLinking.config = JSON.parse(configStr);
            console.log('[EntityLinking] Config:', EntityLinking.config);
        } catch (e) {
            console.error('[EntityLinking] Failed to parse config:', e);
            return;
        }

        // Create the search modal
        createSearchModal();

        // Fetch configured knowledge bases
        fetchConfiguredKBs();

        // Set up event listeners
        setupEventListeners();

        EntityLinking.initialized = true;
        console.log('[EntityLinking] Initialized successfully');
    }

    /**
     * Fetch the list of configured knowledge bases from the server
     */
    async function fetchConfiguredKBs() {
        try {
            const response = await fetch('/api/entity_linking/configured_kbs');
            if (response.ok) {
                const data = await response.json();
                EntityLinking.configuredKBs = data.knowledge_bases || [];
                console.log('[EntityLinking] Configured KBs:', EntityLinking.configuredKBs);

                // Update the KB selector in the modal
                updateKBSelector();
            }
        } catch (e) {
            console.error('[EntityLinking] Failed to fetch configured KBs:', e);
        }
    }

    /**
     * Update the KB selector dropdown with available knowledge bases
     */
    function updateKBSelector() {
        const selector = document.getElementById('el-kb-selector');
        if (!selector) return;

        selector.innerHTML = '';

        EntityLinking.configuredKBs.forEach(kb => {
            const option = document.createElement('option');
            option.value = kb.name;
            option.textContent = `${kb.name} (${kb.type})`;
            selector.appendChild(option);
        });
    }

    /**
     * Create the entity linking search modal
     */
    function createSearchModal() {
        // Check if modal already exists
        if (document.getElementById('entity-linking-modal')) {
            EntityLinking.modal = document.getElementById('entity-linking-modal');
            return;
        }

        const modal = document.createElement('div');
        modal.id = 'entity-linking-modal';
        modal.className = 'el-modal';
        modal.innerHTML = `
            <div class="el-modal-content">
                <div class="el-modal-header">
                    <h3>Link to Knowledge Base Entity</h3>
                    <button class="el-close-btn" title="Close">&times;</button>
                </div>
                <div class="el-modal-body">
                    <div class="el-span-info">
                        <strong>Selected text:</strong>
                        <span id="el-selected-text" class="el-selected-text"></span>
                    </div>
                    <div class="el-search-container">
                        <select id="el-kb-selector" class="el-kb-selector">
                            <option value="">Select Knowledge Base...</option>
                        </select>
                        <input type="text" id="el-search-input" class="el-search-input"
                               placeholder="Search for entity...">
                        <button id="el-search-btn" class="el-search-btn">Search</button>
                    </div>
                    <div id="el-loading" class="el-loading" style="display: none;">
                        <span class="el-spinner"></span> Searching...
                    </div>
                    <div id="el-results" class="el-results"></div>
                    <div id="el-current-link" class="el-current-link" style="display: none;">
                        <strong>Currently linked to:</strong>
                        <div id="el-current-entity"></div>
                        <button id="el-remove-link" class="el-remove-link-btn">Remove Link</button>
                    </div>
                </div>
                <div class="el-modal-footer">
                    <button id="el-cancel-btn" class="el-cancel-btn">Cancel</button>
                </div>
            </div>
        `;

        document.body.appendChild(modal);
        EntityLinking.modal = modal;

        // Set up modal event listeners
        modal.querySelector('.el-close-btn').addEventListener('click', closeModal);
        modal.querySelector('#el-cancel-btn').addEventListener('click', closeModal);
        modal.querySelector('#el-search-btn').addEventListener('click', performSearch);
        modal.querySelector('#el-search-input').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                performSearch();
            }
        });
        modal.querySelector('#el-search-input').addEventListener('input', debounceSearch);
        modal.querySelector('#el-remove-link').addEventListener('click', removeCurrentLink);

        // Close on backdrop click
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                closeModal();
            }
        });
    }

    /**
     * Set up event listeners for span interactions
     */
    function setupEventListeners() {
        // Listen for span creation events
        document.addEventListener('spanCreated', handleSpanCreated);

        // Add click handlers to existing spans with link icons
        addLinkIconsToSpans();

        // Listen for span hover to show entity info
        document.addEventListener('mouseover', handleSpanHover);
        document.addEventListener('mouseout', handleSpanHoverOut);
    }

    /**
     * Add link icons to all span highlights
     */
    function addLinkIconsToSpans() {
        const spans = document.querySelectorAll('.span-highlight');
        spans.forEach(span => {
            if (!span.querySelector('.el-link-icon')) {
                addLinkIconToSpan(span);
            }
        });
    }

    /**
     * Add a link icon to a specific span
     */
    function addLinkIconToSpan(span) {
        const icon = document.createElement('span');
        icon.className = 'el-link-icon';
        icon.innerHTML = span.classList.contains('has-entity-link') ?
            '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>' :
            '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>';
        icon.title = span.classList.contains('has-entity-link') ?
            'Edit entity link' : 'Link to knowledge base';

        icon.addEventListener('click', (e) => {
            e.stopPropagation();
            openModal(span);
        });

        span.appendChild(icon);
    }

    /**
     * Handle span creation event
     */
    function handleSpanCreated(event) {
        const span = event.detail.span;
        const spanElement = event.detail.element;

        if (!spanElement) return;

        // Add link icon
        addLinkIconToSpan(spanElement);

        // Auto-search if enabled
        if (EntityLinking.config && EntityLinking.config.auto_search) {
            openModal(spanElement);
        }
    }

    /**
     * Handle hover over a span with entity link
     */
    function handleSpanHover(event) {
        const span = event.target.closest('.span-highlight.has-entity-link');
        if (!span) return;

        const kbId = span.getAttribute('data-kb-id');
        const kbSource = span.getAttribute('data-kb-source');
        const kbLabel = span.getAttribute('data-kb-label');

        if (!kbId || !kbSource) return;

        // Create tooltip
        showEntityTooltip(span, kbId, kbSource, kbLabel);
    }

    /**
     * Handle hover out from span
     */
    function handleSpanHoverOut(event) {
        const span = event.target.closest('.span-highlight.has-entity-link');
        if (!span) return;

        hideEntityTooltip();
    }

    /**
     * Show entity tooltip on hover
     */
    function showEntityTooltip(span, kbId, kbSource, kbLabel) {
        // Remove existing tooltip
        hideEntityTooltip();

        const tooltip = document.createElement('div');
        tooltip.id = 'el-entity-tooltip';
        tooltip.className = 'el-entity-tooltip';
        tooltip.innerHTML = `
            <div class="el-tooltip-header">
                <span class="el-tooltip-kb">${kbSource}</span>
                <span class="el-tooltip-id">${kbId}</span>
            </div>
            <div class="el-tooltip-label">${kbLabel || 'Loading...'}</div>
        `;

        // Position tooltip near the span
        const rect = span.getBoundingClientRect();
        tooltip.style.position = 'fixed';
        tooltip.style.left = `${rect.left}px`;
        tooltip.style.top = `${rect.bottom + 5}px`;

        document.body.appendChild(tooltip);

        // Fetch full entity details if we only have ID
        if (!kbLabel) {
            fetchEntityDetails(kbId, kbSource, tooltip);
        }
    }

    /**
     * Hide entity tooltip
     */
    function hideEntityTooltip() {
        const tooltip = document.getElementById('el-entity-tooltip');
        if (tooltip) {
            tooltip.remove();
        }
    }

    /**
     * Fetch entity details for tooltip
     */
    async function fetchEntityDetails(kbId, kbSource, tooltip) {
        try {
            const response = await fetch(`/api/entity_linking/entity/${kbSource}/${kbId}`);
            if (response.ok) {
                const data = await response.json();
                const entity = data.entity;

                if (tooltip && document.body.contains(tooltip)) {
                    tooltip.querySelector('.el-tooltip-label').textContent = entity.label;
                    if (entity.description) {
                        const desc = document.createElement('div');
                        desc.className = 'el-tooltip-desc';
                        desc.textContent = entity.description;
                        tooltip.appendChild(desc);
                    }
                }
            }
        } catch (e) {
            console.error('[EntityLinking] Failed to fetch entity details:', e);
        }
    }

    /**
     * Open the entity linking modal for a span
     */
    function openModal(spanElement) {
        if (!EntityLinking.modal) return;

        // Get span info
        EntityLinking.currentSpanId = spanElement.getAttribute('data-annotation-id');
        EntityLinking.currentInstanceId = document.getElementById('instance_id')?.value;

        // Get selected text
        const selectedText = spanElement.textContent.replace(/\s*$/, '');
        document.getElementById('el-selected-text').textContent = selectedText;
        document.getElementById('el-search-input').value = selectedText;

        // Check for existing link
        const kbId = spanElement.getAttribute('data-kb-id');
        const kbSource = spanElement.getAttribute('data-kb-source');
        const kbLabel = spanElement.getAttribute('data-kb-label');

        if (kbId && kbSource) {
            showCurrentLink(kbId, kbSource, kbLabel);
        } else {
            document.getElementById('el-current-link').style.display = 'none';
        }

        // Clear previous results
        document.getElementById('el-results').innerHTML = '';
        document.getElementById('el-loading').style.display = 'none';

        // Show modal
        EntityLinking.modal.style.display = 'flex';
        document.getElementById('el-search-input').focus();

        // Auto-search with current text
        if (selectedText && EntityLinking.configuredKBs.length > 0) {
            const selector = document.getElementById('el-kb-selector');
            if (!selector.value && EntityLinking.configuredKBs[0]) {
                selector.value = EntityLinking.configuredKBs[0].name;
            }
            performSearch();
        }
    }

    /**
     * Show current entity link in modal
     */
    function showCurrentLink(kbId, kbSource, kbLabel) {
        const container = document.getElementById('el-current-link');
        const entityDiv = document.getElementById('el-current-entity');

        entityDiv.innerHTML = `
            <span class="el-current-kb">${kbSource}</span>:
            <span class="el-current-id">${kbId}</span>
            ${kbLabel ? `<br><span class="el-current-label">${kbLabel}</span>` : ''}
        `;

        container.style.display = 'block';
    }

    /**
     * Close the modal
     */
    function closeModal() {
        if (EntityLinking.modal) {
            EntityLinking.modal.style.display = 'none';
        }
        EntityLinking.currentSpanId = null;
        EntityLinking.currentInstanceId = null;
    }

    /**
     * Debounced search
     */
    function debounceSearch() {
        clearTimeout(EntityLinking.searchTimeout);
        EntityLinking.searchTimeout = setTimeout(performSearch, 300);
    }

    /**
     * Perform entity search
     */
    async function performSearch() {
        const query = document.getElementById('el-search-input').value.trim();
        const kbName = document.getElementById('el-kb-selector').value;

        if (!query || !kbName) {
            return;
        }

        const loading = document.getElementById('el-loading');
        const results = document.getElementById('el-results');

        loading.style.display = 'flex';
        results.innerHTML = '';

        try {
            const response = await fetch(
                `/api/entity_linking/search?q=${encodeURIComponent(query)}&kb=${encodeURIComponent(kbName)}&limit=10`
            );

            if (response.ok) {
                const data = await response.json();
                displayResults(data.results);
            } else {
                results.innerHTML = '<div class="el-error">Search failed. Please try again.</div>';
            }
        } catch (e) {
            console.error('[EntityLinking] Search error:', e);
            results.innerHTML = '<div class="el-error">Search failed. Please try again.</div>';
        } finally {
            loading.style.display = 'none';
        }
    }

    /**
     * Display search results
     */
    function displayResults(entities) {
        const results = document.getElementById('el-results');

        if (!entities || entities.length === 0) {
            results.innerHTML = '<div class="el-no-results">No entities found.</div>';
            return;
        }

        results.innerHTML = entities.map(entity => `
            <div class="el-result-item" data-entity-id="${entity.entity_id}"
                 data-kb-source="${entity.kb_source}" data-label="${escapeHtml(entity.label)}">
                <div class="el-result-header">
                    <span class="el-result-label">${escapeHtml(entity.label)}</span>
                    <span class="el-result-id">${entity.entity_id}</span>
                </div>
                ${entity.description ? `<div class="el-result-desc">${escapeHtml(entity.description)}</div>` : ''}
                ${entity.aliases && entity.aliases.length > 0 ?
                    `<div class="el-result-aliases">Also: ${entity.aliases.slice(0, 3).map(a => escapeHtml(a)).join(', ')}</div>` : ''}
                ${entity.url ? `<a href="${entity.url}" target="_blank" class="el-result-link">View in KB</a>` : ''}
            </div>
        `).join('');

        // Add click handlers
        results.querySelectorAll('.el-result-item').forEach(item => {
            item.addEventListener('click', () => selectEntity(item));
        });
    }

    /**
     * Select an entity from search results
     */
    async function selectEntity(item) {
        const entityId = item.getAttribute('data-entity-id');
        const kbSource = item.getAttribute('data-kb-source');
        const label = item.getAttribute('data-label');

        if (!EntityLinking.currentSpanId || !EntityLinking.currentInstanceId) {
            console.error('[EntityLinking] No span selected');
            return;
        }

        try {
            const response = await fetch('/api/entity_linking/update_span', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    instance_id: EntityLinking.currentInstanceId,
                    span_id: EntityLinking.currentSpanId,
                    kb_id: entityId,
                    kb_source: kbSource,
                    kb_label: label
                })
            });

            if (response.ok) {
                // Update the span element
                const spanElement = document.querySelector(
                    `.span-highlight[data-annotation-id="${EntityLinking.currentSpanId}"]`
                );

                if (spanElement) {
                    spanElement.setAttribute('data-kb-id', entityId);
                    spanElement.setAttribute('data-kb-source', kbSource);
                    spanElement.setAttribute('data-kb-label', label);
                    spanElement.classList.add('has-entity-link');

                    // Update link icon
                    const icon = spanElement.querySelector('.el-link-icon');
                    if (icon) {
                        icon.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>';
                        icon.title = 'Edit entity link';
                    }
                }

                closeModal();
                console.log('[EntityLinking] Entity link saved:', entityId);
            } else {
                console.error('[EntityLinking] Failed to save entity link');
            }
        } catch (e) {
            console.error('[EntityLinking] Error saving entity link:', e);
        }
    }

    /**
     * Remove the current entity link
     */
    async function removeCurrentLink() {
        if (!EntityLinking.currentSpanId || !EntityLinking.currentInstanceId) {
            return;
        }

        try {
            const response = await fetch('/api/entity_linking/update_span', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    instance_id: EntityLinking.currentInstanceId,
                    span_id: EntityLinking.currentSpanId,
                    kb_id: null,
                    kb_source: null,
                    kb_label: null
                })
            });

            if (response.ok) {
                // Update the span element
                const spanElement = document.querySelector(
                    `.span-highlight[data-annotation-id="${EntityLinking.currentSpanId}"]`
                );

                if (spanElement) {
                    spanElement.removeAttribute('data-kb-id');
                    spanElement.removeAttribute('data-kb-source');
                    spanElement.removeAttribute('data-kb-label');
                    spanElement.classList.remove('has-entity-link');

                    // Update link icon
                    const icon = spanElement.querySelector('.el-link-icon');
                    if (icon) {
                        icon.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>';
                        icon.title = 'Link to knowledge base';
                    }
                }

                document.getElementById('el-current-link').style.display = 'none';
                console.log('[EntityLinking] Entity link removed');
            }
        } catch (e) {
            console.error('[EntityLinking] Error removing entity link:', e);
        }
    }

    /**
     * Escape HTML special characters
     */
    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Also initialize when spans are added to the page
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            mutation.addedNodes.forEach((node) => {
                if (node.nodeType === Node.ELEMENT_NODE) {
                    if (node.classList && node.classList.contains('span-highlight')) {
                        if (!node.querySelector('.el-link-icon')) {
                            addLinkIconToSpan(node);
                        }
                    }
                    // Also check child nodes
                    const spans = node.querySelectorAll && node.querySelectorAll('.span-highlight');
                    if (spans) {
                        spans.forEach(span => {
                            if (!span.querySelector('.el-link-icon')) {
                                addLinkIconToSpan(span);
                            }
                        });
                    }
                }
            });
        });
    });

    // Start observing when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            observer.observe(document.body, { childList: true, subtree: true });
        });
    } else {
        observer.observe(document.body, { childList: true, subtree: true });
    }

    // Expose for external use
    window.EntityLinking = {
        init: init,
        openModal: openModal,
        closeModal: closeModal,
        search: performSearch
    };

})();
