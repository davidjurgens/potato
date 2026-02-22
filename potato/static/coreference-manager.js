/**
 * Coreference Chain Manager
 *
 * Manages coreference annotation chains — groups of text spans
 * that refer to the same entity. Built on top of the span annotation
 * and span_link infrastructure.
 *
 * Data is stored as span_link entries with link_type="coreference"
 * in the hidden input field for form submission.
 */

(function() {
    'use strict';

    class CoreferenceManager {
        constructor(container) {
            this.container = container;
            this.config = JSON.parse(container.dataset.corefConfig || '{}');
            this.schemaName = this.config.schemaName || '';
            this.spanSchema = this.config.spanSchema || '';
            this.entityTypes = this.config.entityTypes || [];
            this.allowSingletons = this.config.allowSingletons !== false;
            this.highlightMode = this.config.highlightMode || 'background';
            this.colorPalette = this.config.colors || [
                '#6E56CF', '#EF4444', '#22C55E', '#3B82F6', '#F59E0B',
                '#EC4899', '#06B6D4', '#F97316', '#8B5CF6', '#10B981'
            ];

            this.chains = [];  // Array of chain objects
            this.nextChainId = 1;
            this.activeChainId = null;
            this.selectedSpanIds = [];

            this._bindElements();
            this._bindEvents();
            this._loadExistingData();
        }

        _bindElements() {
            var name = this.schemaName;
            this.chainList = document.getElementById(name + '_chain_list');
            this.chainCount = document.getElementById(name + '_chain_count');
            this.chainData = document.getElementById(name + '_chain_data');
            this.newChainBtn = document.getElementById(name + '_new_chain');
            this.addToChainBtn = document.getElementById(name + '_add_to_chain');
            this.mergeBtn = document.getElementById(name + '_merge_chains');
            this.removeBtn = document.getElementById(name + '_remove_mention');
        }

        _bindEvents() {
            var self = this;

            if (this.newChainBtn) {
                this.newChainBtn.addEventListener('click', function() {
                    self.createChain();
                });
            }

            if (this.addToChainBtn) {
                this.addToChainBtn.addEventListener('click', function() {
                    self.addSelectedToActiveChain();
                });
            }

            if (this.mergeBtn) {
                this.mergeBtn.addEventListener('click', function() {
                    self.mergeSelectedChains();
                });
            }

            if (this.removeBtn) {
                this.removeBtn.addEventListener('click', function() {
                    self.removeSelectedMention();
                });
            }

            // Listen for span selection events from span-manager
            document.addEventListener('spanSelected', function(e) {
                if (e.detail && e.detail.schema === self.spanSchema) {
                    self._onSpanSelected(e.detail.spanId);
                }
            });

            document.addEventListener('spanDeselected', function(e) {
                if (e.detail && e.detail.schema === self.spanSchema) {
                    self._onSpanDeselected(e.detail.spanId);
                }
            });
        }

        _loadExistingData() {
            if (!this.chainData || !this.chainData.value) return;
            try {
                var data = JSON.parse(this.chainData.value);
                if (!Array.isArray(data) || data.length === 0) return;

                for (var i = 0; i < data.length; i++) {
                    var link = data[i];
                    this.chains.push({
                        id: link.id || ('chain_' + this.nextChainId++),
                        entityType: link.link_type || link.entity_type || '',
                        spanIds: link.span_ids || [],
                        color: link.color || this.colorPalette[this.chains.length % this.colorPalette.length]
                    });
                }
                this._render();
            } catch (e) {
                console.warn('CoreferenceManager: Failed to load existing data', e);
            }
        }

        _onSpanSelected(spanId) {
            if (this.selectedSpanIds.indexOf(spanId) === -1) {
                this.selectedSpanIds.push(spanId);
            }
            this._updateButtonStates();
        }

        _onSpanDeselected(spanId) {
            var idx = this.selectedSpanIds.indexOf(spanId);
            if (idx !== -1) {
                this.selectedSpanIds.splice(idx, 1);
            }
            this._updateButtonStates();
        }

        createChain() {
            if (this.selectedSpanIds.length === 0 && !this.allowSingletons) return;
            if (this.selectedSpanIds.length === 0) return;

            // Get selected entity type
            var entityType = '';
            if (this.entityTypes.length > 0) {
                var checkedRadio = this.container.querySelector(
                    'input[name="' + this.schemaName + '_entity_type"]:checked'
                );
                entityType = checkedRadio ? checkedRadio.value : this.entityTypes[0];
            }

            var chain = {
                id: 'chain_' + this.nextChainId++,
                entityType: entityType,
                spanIds: this.selectedSpanIds.slice(),
                color: this.colorPalette[(this.chains.length) % this.colorPalette.length]
            };

            // Remove these spans from any other chain
            for (var i = 0; i < chain.spanIds.length; i++) {
                this._removeSpanFromAllChains(chain.spanIds[i]);
            }

            this.chains.push(chain);
            this.activeChainId = chain.id;
            this.selectedSpanIds = [];
            this._render();
            this._save();
        }

        addSelectedToActiveChain() {
            if (!this.activeChainId || this.selectedSpanIds.length === 0) return;

            var chain = this._getChainById(this.activeChainId);
            if (!chain) return;

            for (var i = 0; i < this.selectedSpanIds.length; i++) {
                var spanId = this.selectedSpanIds[i];
                this._removeSpanFromAllChains(spanId);
                if (chain.spanIds.indexOf(spanId) === -1) {
                    chain.spanIds.push(spanId);
                }
            }

            this.selectedSpanIds = [];
            this._render();
            this._save();
        }

        mergeSelectedChains() {
            // Merge active chain with chains that contain selected spans
            if (!this.activeChainId) return;

            var targetChain = this._getChainById(this.activeChainId);
            if (!targetChain) return;

            var chainsToMerge = [];
            for (var i = 0; i < this.selectedSpanIds.length; i++) {
                var chain = this._getChainContainingSpan(this.selectedSpanIds[i]);
                if (chain && chain.id !== this.activeChainId &&
                    chainsToMerge.indexOf(chain) === -1) {
                    chainsToMerge.push(chain);
                }
            }

            for (var j = 0; j < chainsToMerge.length; j++) {
                var mergeChain = chainsToMerge[j];
                for (var k = 0; k < mergeChain.spanIds.length; k++) {
                    if (targetChain.spanIds.indexOf(mergeChain.spanIds[k]) === -1) {
                        targetChain.spanIds.push(mergeChain.spanIds[k]);
                    }
                }
                this._deleteChain(mergeChain.id);
            }

            this.selectedSpanIds = [];
            this._render();
            this._save();
        }

        removeSelectedMention() {
            if (this.selectedSpanIds.length === 0) return;

            for (var i = 0; i < this.selectedSpanIds.length; i++) {
                var spanId = this.selectedSpanIds[i];
                var chain = this._getChainContainingSpan(spanId);
                if (chain) {
                    var idx = chain.spanIds.indexOf(spanId);
                    if (idx !== -1) {
                        chain.spanIds.splice(idx, 1);
                    }
                    // Remove chain if empty (or singleton and singletons not allowed)
                    if (chain.spanIds.length === 0 ||
                        (!this.allowSingletons && chain.spanIds.length < 2)) {
                        this._deleteChain(chain.id);
                    }
                }
            }

            this.selectedSpanIds = [];
            this._render();
            this._save();
        }

        deleteChain(chainId) {
            this._deleteChain(chainId);
            if (this.activeChainId === chainId) {
                this.activeChainId = null;
            }
            this._render();
            this._save();
        }

        setActiveChain(chainId) {
            this.activeChainId = chainId;
            this._render();
        }

        // Internal helpers

        _getChainById(id) {
            for (var i = 0; i < this.chains.length; i++) {
                if (this.chains[i].id === id) return this.chains[i];
            }
            return null;
        }

        _getChainContainingSpan(spanId) {
            for (var i = 0; i < this.chains.length; i++) {
                if (this.chains[i].spanIds.indexOf(spanId) !== -1) {
                    return this.chains[i];
                }
            }
            return null;
        }

        _removeSpanFromAllChains(spanId) {
            for (var i = this.chains.length - 1; i >= 0; i--) {
                var chain = this.chains[i];
                var idx = chain.spanIds.indexOf(spanId);
                if (idx !== -1) {
                    chain.spanIds.splice(idx, 1);
                    if (chain.spanIds.length === 0) {
                        this.chains.splice(i, 1);
                    }
                }
            }
        }

        _deleteChain(chainId) {
            for (var i = 0; i < this.chains.length; i++) {
                if (this.chains[i].id === chainId) {
                    this.chains.splice(i, 1);
                    return;
                }
            }
        }

        _updateButtonStates() {
            var hasSelection = this.selectedSpanIds.length > 0;
            var hasActiveChain = this.activeChainId !== null;

            if (this.newChainBtn) this.newChainBtn.disabled = !hasSelection;
            if (this.addToChainBtn) this.addToChainBtn.disabled = !(hasSelection && hasActiveChain);
            if (this.mergeBtn) this.mergeBtn.disabled = !(hasSelection && hasActiveChain);
            if (this.removeBtn) this.removeBtn.disabled = !hasSelection;
        }

        _render() {
            this._renderChainList();
            this._updateChainCount();
            this._updateButtonStates();
            this._updateMentionHighlights();
        }

        _renderChainList() {
            if (!this.chainList) return;

            if (this.chains.length === 0) {
                this.chainList.innerHTML = '<p class="coref-no-chains-message">' +
                    'No coreference chains created yet. Select spans and click "New Chain" to start.</p>';
                return;
            }

            var html = '';
            for (var i = 0; i < this.chains.length; i++) {
                var chain = this.chains[i];
                var isActive = chain.id === this.activeChainId;
                var mentionTexts = this._getMentionTexts(chain.spanIds);

                html += '<div class="coref-chain-item' + (isActive ? ' active' : '') + '"' +
                    ' data-chain-id="' + chain.id + '"' +
                    ' style="--chain-color: ' + chain.color + '">';

                html += '<span class="coref-chain-color" style="background-color: ' + chain.color + '"></span>';

                html += '<div class="coref-chain-info">';
                var label = chain.entityType || ('Chain ' + (i + 1));
                html += '<div class="coref-chain-label">' + this._escapeHtml(label) +
                    ' <span style="color:#94a3b8;font-weight:normal">(' + chain.spanIds.length + ')</span></div>';

                html += '<div class="coref-chain-mentions">';
                for (var j = 0; j < mentionTexts.length; j++) {
                    if (j > 0) html += ', ';
                    html += '<span class="coref-chain-mention-tag">' +
                        this._escapeHtml(this._truncate(mentionTexts[j], 30)) + '</span>';
                }
                html += '</div></div>';

                html += '<button class="coref-chain-delete" data-chain-id="' + chain.id +
                    '" title="Delete chain">&times;</button>';
                html += '</div>';
            }

            this.chainList.innerHTML = html;

            // Bind click events
            var self = this;
            var items = this.chainList.querySelectorAll('.coref-chain-item');
            for (var k = 0; k < items.length; k++) {
                (function(item) {
                    item.addEventListener('click', function(e) {
                        if (!e.target.closest('.coref-chain-delete')) {
                            self.setActiveChain(item.dataset.chainId);
                        }
                    });
                })(items[k]);
            }

            var delBtns = this.chainList.querySelectorAll('.coref-chain-delete');
            for (var d = 0; d < delBtns.length; d++) {
                (function(btn) {
                    btn.addEventListener('click', function(e) {
                        e.stopPropagation();
                        self.deleteChain(btn.dataset.chainId);
                    });
                })(delBtns[d]);
            }
        }

        _updateChainCount() {
            if (this.chainCount) {
                var n = this.chains.length;
                this.chainCount.textContent = n + (n === 1 ? ' chain' : ' chains');
            }
        }

        _updateMentionHighlights() {
            // Remove all existing highlights
            var existing = document.querySelectorAll('.coref-mention-highlight-background, ' +
                '.coref-mention-highlight-bracket, .coref-mention-highlight-underline');
            for (var i = 0; i < existing.length; i++) {
                existing[i].classList.remove(
                    'coref-mention-highlight-background',
                    'coref-mention-highlight-bracket',
                    'coref-mention-highlight-underline'
                );
                existing[i].style.removeProperty('--chain-color');
                existing[i].style.removeProperty('background-color');
            }

            // Apply highlights for each chain
            var highlightClass = 'coref-mention-highlight-' + this.highlightMode;
            for (var j = 0; j < this.chains.length; j++) {
                var chain = this.chains[j];
                for (var k = 0; k < chain.spanIds.length; k++) {
                    var spanEl = document.querySelector('[data-span-id="' + chain.spanIds[k] + '"]');
                    if (spanEl) {
                        spanEl.classList.add(highlightClass);
                        spanEl.style.setProperty('--chain-color', chain.color);
                        if (this.highlightMode === 'background') {
                            spanEl.style.backgroundColor = chain.color + '30'; // 30 = ~19% opacity
                        }
                    }
                }
            }
        }

        _getMentionTexts(spanIds) {
            var texts = [];
            for (var i = 0; i < spanIds.length; i++) {
                var spanEl = document.querySelector('[data-span-id="' + spanIds[i] + '"]');
                if (spanEl) {
                    texts.push(spanEl.textContent || spanEl.innerText || '');
                } else {
                    texts.push('(span ' + spanIds[i] + ')');
                }
            }
            return texts;
        }

        _save() {
            if (!this.chainData) return;

            var data = [];
            for (var i = 0; i < this.chains.length; i++) {
                var chain = this.chains[i];
                data.push({
                    id: chain.id,
                    schema: this.schemaName,
                    link_type: chain.entityType || 'coreference',
                    span_ids: chain.spanIds,
                    direction: 'undirected',
                    properties: { color: chain.color }
                });
            }

            this.chainData.value = JSON.stringify(data);
        }

        _escapeHtml(str) {
            var div = document.createElement('div');
            div.textContent = str;
            return div.innerHTML;
        }

        _truncate(str, maxLen) {
            if (str.length <= maxLen) return str;
            return str.substring(0, maxLen - 3) + '...';
        }
    }

    // Auto-initialize on DOM ready
    function initCoreferenceManagers() {
        var containers = document.querySelectorAll('.coref-container');
        for (var i = 0; i < containers.length; i++) {
            if (!containers[i]._coreferenceManager) {
                containers[i]._coreferenceManager = new CoreferenceManager(containers[i]);
            }
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initCoreferenceManagers);
    } else {
        initCoreferenceManagers();
    }

    // Expose globally
    window.CoreferenceManager = CoreferenceManager;
})();
