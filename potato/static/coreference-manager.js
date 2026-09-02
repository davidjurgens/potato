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

            // Sync the buttons to the (empty) selection. Without this they keep
            // whatever the server rendered, which is how New Chain came up
            // enabled on a page with nothing selected -- it looked live and did
            // nothing when pressed.
            this._updateButtonStates();
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

            // Nothing in Potato dispatched those two events, so selectedSpanIds
            // was never appended to, `hasSelection` was permanently false, and
            // Add to Chain / Merge / Remove sat disabled however many mentions
            // the annotator drew. The manager itself worked -- dispatching the
            // event by hand from the console drove it correctly -- so the whole
            // scheme was one missing input away from functioning.
            //
            // Collect the selection the way span_link already does: delegate on
            // document, resolve the overlay with closest(), and dispatch. The
            // events stay the seam, so anything else listening for them (and
            // the span layer, if it ever emits them itself) still works.
            this._bindSpanSelection();
        }

        /** Overlay elements this manager will accept clicks on. */
        static get OVERLAY_SELECTOR() {
            return '.span-overlay-pure, .span-overlay, .span-overlay-ai, .span-highlight';
        }

        _bindSpanSelection() {
            var self = this;

            // Kept as a reference so destroy() can remove it. An anonymous
            // listener on `document` outlives the panel it belongs to, and the
            // panel is rebuilt on every instance navigation.
            this._clickHandler = function(e) {
                // span_link owns the click while its link mode is active; it
                // stops propagation, but capture order between two listeners on
                // document is registration order, so check explicitly.
                if (document.body.classList.contains('span-link-mode-active')) return;

                var overlay = e.target.closest(CoreferenceManager.OVERLAY_SELECTOR);
                if (!overlay) {
                    var segment = e.target.closest('.span-highlight-segment');
                    if (segment) overlay = segment.closest(CoreferenceManager.OVERLAY_SELECTOR);
                }
                if (!overlay || !overlay.dataset.annotationId) return;
                if (self.spanSchema && overlay.dataset.schema !== self.spanSchema) return;

                // preventDefault only. stopPropagation would starve any other
                // manager listening on document -- a page with two coreference
                // schemes over different span schemas is a normal config, and
                // whichever one registered first would swallow every click.
                //
                // But exactly one manager may turn a click into an event.
                // Two managers over the SAME span schema would otherwise each
                // dispatch, and since both also listen, the second dispatch
                // reads the state the first one just set and flips it back:
                // one click, no net change.
                if (e._corefHandled) return;
                e._corefHandled = true;

                e.preventDefault();
                self._toggleSpan(overlay);
            };
            document.addEventListener('click', this._clickHandler, true);

            this._makeSpansSelectable();

            // Overlays are re-rendered on every span change and on instance
            // navigation, and a fresh overlay comes back with the stylesheet's
            // `pointer-events: none`. Without this, only the spans that existed
            // when the manager booted were ever clickable.
            var container = document.getElementById('span-overlays') || document.body;
            this._overlayObserver = new MutationObserver(function() {
                self._makeSpansSelectable();
                self._pruneSelection();
                self._syncSelectionVisuals();
            });
            this._overlayObserver.observe(container, {childList: true, subtree: true});
        }

        /**
         * Overlays carry `pointer-events: none` so they do not block the drag
         * that draws a span. A mention cannot be clicked until that is lifted.
         */
        _makeSpansSelectable() {
            var self = this;
            document.querySelectorAll(CoreferenceManager.OVERLAY_SELECTOR).forEach(function(overlay) {
                if (self.spanSchema && overlay.dataset.schema !== self.spanSchema) return;
                overlay.style.pointerEvents = 'auto';
                overlay.style.cursor = 'pointer';
                overlay.classList.add('coref-selectable');
            });
            document.querySelectorAll('.span-highlight-segment').forEach(function(segment) {
                segment.style.pointerEvents = 'auto';
            });
        }

        _toggleSpan(overlay) {
            var spanId = overlay.dataset.annotationId;
            var selected = this.selectedSpanIds.indexOf(spanId) !== -1;
            // No class toggle here: the event updates selectedSpanIds, which
            // calls _updateButtonStates, which paints. One source of truth.
            document.dispatchEvent(new CustomEvent(selected ? 'spanDeselected' : 'spanSelected', {
                detail: {
                    spanId: spanId,
                    schema: overlay.dataset.schema,
                    label: overlay.dataset.label,
                    text: overlay.textContent
                }
            }));
        }

        /**
         * Drop selections whose overlay is gone.
         *
         * Navigating to the next instance replaces every overlay. Stale ids
         * left in the selection would enable the chain buttons on an instance
         * where nothing is selected, and then write a chain referring to
         * mentions from the previous item.
         */
        _pruneSelection() {
            var self = this;
            var live = this.selectedSpanIds.filter(function(spanId) {
                return !!document.querySelector(
                    '[data-annotation-id="' + (window.CSS && CSS.escape
                        ? CSS.escape(spanId) : spanId) + '"]');
            });
            if (live.length !== this.selectedSpanIds.length) {
                this.selectedSpanIds = live;
                this._updateButtonStates();
            }
        }

        /**
         * Detach from the document.
         *
         * The click listener and the MutationObserver both outlive the panel
         * otherwise, and the panel is rebuilt on every instance navigation --
         * so without this an annotator accumulates one live manager per item
         * they have visited, each still dispatching selection events.
         */
        destroy() {
            if (this._clickHandler) {
                document.removeEventListener('click', this._clickHandler, true);
                this._clickHandler = null;
            }
            if (this._overlayObserver) {
                this._overlayObserver.disconnect();
                this._overlayObserver = null;
            }
        }

        _loadExistingData() {
            this._adoptLinks(this._parseInputValue());

            // The hidden input is not populated server-side, so on a revisit it
            // reads "[]" while the chains sit in the user's link annotations.
            // Ask the server, the way span_link does.
            this._loadFromServer();
        }

        _parseInputValue() {
            if (!this.chainData || !this.chainData.value) return [];
            try {
                var data = JSON.parse(this.chainData.value);
                return Array.isArray(data) ? data : [];
            } catch (e) {
                console.warn('CoreferenceManager: Failed to parse chain data', e);
                return [];
            }
        }

        _loadFromServer() {
            var self = this;
            var instanceId = document.getElementById('instance_id')?.value;
            if (!instanceId) return;

            fetch('/api/links/' + encodeURIComponent(instanceId))
                .then(function(r) { return r.ok ? r.json() : null; })
                .then(function(payload) {
                    if (!payload || !Array.isArray(payload.links)) return;
                    // Only this scheme's links; one instance can carry several.
                    var mine = payload.links.filter(function(link) {
                        return link.schema === self.schemaName;
                    });
                    if (!mine.length) return;
                    self.chains = [];
                    self._adoptLinks(mine);
                })
                .catch(function(err) {
                    console.warn('CoreferenceManager: failed to load chains', err);
                });
        }

        /** Turn stored SpanLink records into chains and paint them. */
        _adoptLinks(links) {
            if (!Array.isArray(links) || links.length === 0) return;

            for (var i = 0; i < links.length; i++) {
                var link = links[i];
                var props = link.properties || {};
                this.chains.push({
                    id: link.id || ('chain_' + this.nextChainId++),
                    entityType: link.link_type || link.entity_type || '',
                    spanIds: link.span_ids || [],
                    color: props.color || link.color
                        || this.colorPalette[this.chains.length % this.colorPalette.length]
                });
            }

            // Keep the next generated id clear of the ones just restored, or a
            // new chain reuses an existing id and overwrites it on save.
            var self = this;
            this.chains.forEach(function(chain) {
                var match = /^chain_(\d+)$/.exec(chain.id || '');
                if (match) {
                    self.nextChainId = Math.max(self.nextChainId, parseInt(match[1], 10) + 1);
                }
            });

            // Seed the delete bookkeeping from what is already stored, and
            // render. Deliberately no _save(): restoring is not a change, and
            // writing here would POST the server's own data back to it on every
            // page load.
            this._savedChainIds = this.chains.map(function(chain) { return chain.id; });
            if (this.chainData) {
                var self2 = this;
                this.chainData.value = JSON.stringify(
                    this.chains.map(function(chain) { return self2._chainToLink(chain); }));
            }
            this._render();
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

            this._syncSelectionVisuals();
        }

        /**
         * Reconcile the outline on each overlay against selectedSpanIds.
         *
         * Driven from state rather than toggled at the click, because the
         * selection is also cleared in code -- createChain() and
         * addSelectedToActiveChain() both empty it -- and a class toggled only
         * on click stayed behind, leaving mentions outlined as selected while
         * the panel's buttons had already gone back to disabled.
         */
        _syncSelectionVisuals() {
            var selected = this.selectedSpanIds;
            document.querySelectorAll(CoreferenceManager.OVERLAY_SELECTOR).forEach(function(overlay) {
                var id = overlay.dataset.annotationId;
                overlay.classList.toggle('coref-selected', !!id && selected.indexOf(id) !== -1);
            });
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

        /** The SpanLink form of one chain. Same shape span_link posts. */
        _chainToLink(chain) {
            return {
                id: chain.id,
                schema: this.schemaName,
                link_type: chain.entityType || 'coreference',
                span_ids: chain.spanIds,
                direction: 'undirected',
                properties: { color: chain.color }
            };
        }

        /**
         * Persist the chains.
         *
         * This used to assign the hidden input's value and stop. That input
         * carries neither the `schema`/`label_name` attributes nor the
         * `annotation-input` class that syncAnnotationsFromDOM requires, so
         * nothing ever picked the value up: every chain the annotator built was
         * gone the moment they moved to the next item, and came back as
         * "0 chains" on the way back.
         *
         * Chains are SpanLinks, and span_link already has a working round trip
         * -- POST /updateinstance with `link_annotations`, DELETE
         * /api/links/<instance>/<id>, GET /api/links/<instance>. Use it rather
         * than inventing a second one. The input keeps its value for form
         * submission and for anything reading the DOM.
         */
        _save() {
            if (!this.chainData) return;

            var self = this;
            var links = this.chains.map(function(chain) { return self._chainToLink(chain); });
            this.chainData.value = JSON.stringify(links);

            var instanceId = document.getElementById('instance_id')?.value;
            if (!instanceId) return;  // Phase page or preview: nothing to save against.

            // Chains removed since the last save have to be deleted explicitly;
            // POSTing the survivors only ever adds or updates.
            var liveIds = {};
            links.forEach(function(link) { liveIds[link.id] = true; });
            (this._savedChainIds || []).forEach(function(id) {
                if (!liveIds[id]) self._deleteChainOnServer(instanceId, id);
            });
            this._savedChainIds = Object.keys(liveIds);

            if (links.length === 0) return;

            fetch('/updateinstance', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    instance_id: instanceId,
                    annotations: {},  // Required for frontend format detection
                    link_annotations: links
                })
            }).catch(function(err) {
                console.error('CoreferenceManager: failed to save chains', err);
            });
        }

        /** Not `_deleteChain` -- that name is taken by the local-array removal
         *  below, and a class body's later definition silently wins. */
        _deleteChainOnServer(instanceId, chainId) {
            fetch('/api/links/' + encodeURIComponent(instanceId) + '/' + encodeURIComponent(chainId),
                  {method: 'DELETE'})
                .catch(function(err) {
                    console.error('CoreferenceManager: failed to delete chain', chainId, err);
                });
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
    // Live managers, so the ones whose panel has been replaced can be detached.
    var liveManagers = [];

    function initCoreferenceManagers() {
        // Instance navigation re-renders the panel, so the container this
        // manager was built around is gone while its document-level click
        // listener is not. Drop those first, or an annotator accumulates one
        // live manager per item visited and each still dispatches selection
        // events.
        liveManagers = liveManagers.filter(function(manager) {
            if (document.contains(manager.container)) return true;
            manager.destroy();
            return false;
        });

        var containers = document.querySelectorAll('.coref-container');
        for (var i = 0; i < containers.length; i++) {
            if (!containers[i]._coreferenceManager) {
                containers[i]._coreferenceManager = new CoreferenceManager(containers[i]);
                liveManagers.push(containers[i]._coreferenceManager);
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
