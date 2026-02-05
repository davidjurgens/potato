/**
 * Adjudication Module - Main Controller
 *
 * Manages the adjudication workflow: queue navigation, item loading,
 * decision submission, and timing tracking.
 */

(function () {
    'use strict';

    var config = window.ADJ_CONFIG || {};
    var schemes = window.ANNOTATION_SCHEMES || [];
    var queue = [];
    var currentItemId = null;
    var currentQueueIndex = -1;
    var itemStartTime = null;
    var currentFilter = 'pending';
    var navHistory = [];
    var navHistoryPos = -1;

    // DOM references
    var queueList = document.getElementById('adj-queue-list');
    var itemView = document.getElementById('adj-item-view');
    var emptyState = document.getElementById('adj-empty-state');
    var navBar = document.getElementById('adj-nav-bar');

    /**
     * Initialize the adjudication interface
     */
    function init() {
        loadQueue(currentFilter === 'all' ? null : currentFilter);
        bindNavigation();
        bindFilters();
    }

    /**
     * Load the adjudication queue from API
     */
    function loadQueue(statusFilter) {
        var url = '/adjudicate/api/queue';
        if (statusFilter && statusFilter !== 'all') {
            url += '?status=' + statusFilter;
        }

        fetch(url)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                queue = data.items || [];
                renderQueue();
                updateProgress();

                // If we had a current item, re-select it (skip history since it's a refresh)
                if (currentItemId) {
                    var found = queue.findIndex(function (i) { return i.instance_id === currentItemId; });
                    if (found >= 0) {
                        selectQueueItem(found, true);
                    }
                }
            })
            .catch(function (err) {
                console.error('Failed to load adjudication queue:', err);
            });
    }

    /**
     * Render the queue sidebar
     */
    function renderQueue() {
        if (!queueList) return;
        queueList.innerHTML = '';

        if (queue.length === 0) {
            queueList.innerHTML = '<div class="text-center text-muted p-3" style="font-size: 0.85rem;">' +
                'No items in queue</div>';
            return;
        }

        queue.forEach(function (item, index) {
            var el = document.createElement('div');
            el.className = 'adj-queue-item';
            if (item.status === 'completed') el.className += ' completed';
            if (item.status === 'skipped') el.className += ' skipped';
            if (item.instance_id === currentItemId) el.className += ' active';

            var agBadge = getAgreementBadge(item.overall_agreement);

            el.innerHTML = '<div class="adj-queue-item-id">' +
                AdjudicationForms.escapeHtml(item.instance_id) + '</div>' +
                '<div class="adj-queue-item-meta">' +
                '<span>' + item.num_annotators + ' annotators</span>' +
                agBadge +
                '</div>';

            el.addEventListener('click', function () {
                selectQueueItem(index);
            });

            queueList.appendChild(el);
        });
    }

    /**
     * Get agreement badge HTML
     */
    function getAgreementBadge(agreement) {
        var pct = Math.round(agreement * 100);
        var cls = 'adj-agreement-low';
        if (agreement >= 0.75) cls = 'adj-agreement-high';
        else if (agreement >= 0.5) cls = 'adj-agreement-medium';

        return '<span class="adj-agreement-badge ' + cls + '">' + pct + '%</span>';
    }

    /**
     * Update progress display
     */
    function updateProgress() {
        fetch('/adjudicate/api/stats')
            .then(function (r) { return r.json(); })
            .then(function (stats) {
                var fill = document.getElementById('adj-progress-fill');
                var text = document.getElementById('adj-progress-text');
                if (fill) {
                    fill.style.width = Math.round(stats.completion_rate * 100) + '%';
                }
                if (text) {
                    text.textContent = stats.completed + '/' + stats.total +
                        ' completed (' + Math.round(stats.completion_rate * 100) + '%)';
                }
            });
    }

    /**
     * Push an item to navigation history (browser-style back/forward)
     */
    function pushToHistory(instanceId) {
        // Truncate any forward history
        if (navHistoryPos < navHistory.length - 1) {
            navHistory = navHistory.slice(0, navHistoryPos + 1);
        }
        // Don't push consecutive duplicates
        if (navHistory.length === 0 || navHistory[navHistory.length - 1] !== instanceId) {
            navHistory.push(instanceId);
        }
        navHistoryPos = navHistory.length - 1;
    }

    /**
     * Select and load a queue item
     * @param {number} index - Index in the current queue array
     * @param {boolean} skipHistory - If true, don't push to navigation history
     */
    function selectQueueItem(index, skipHistory) {
        if (index < 0 || index >= queue.length) return;

        currentQueueIndex = index;
        var item = queue[index];
        currentItemId = item.instance_id;

        if (!skipHistory) {
            pushToHistory(currentItemId);
        }

        // Update active state in sidebar
        queueList.querySelectorAll('.adj-queue-item').forEach(function (el, i) {
            el.classList.toggle('active', i === index);
        });

        loadItem(item.instance_id);
    }

    /**
     * Load full item data from API
     */
    function loadItem(instanceId) {
        fetch('/adjudicate/api/item/' + encodeURIComponent(instanceId))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.error) {
                    console.error('Error loading item:', data.error);
                    return;
                }
                renderItem(data);

                // Phase 3: render similar items and annotator signals
                if (data.similar_items && data.similar_items.length > 0) {
                    renderSimilarItems(data.similar_items);
                } else {
                    var simPanel = document.getElementById('adj-similar-items-panel');
                    if (simPanel) simPanel.style.display = 'none';
                }
                if (data.annotator_signals) {
                    renderAnnotatorSignals(data.annotator_signals);
                }

                itemStartTime = Date.now();
            })
            .catch(function (err) {
                console.error('Failed to load item:', err);
            });
    }

    /**
     * Render a loaded item
     */
    function renderItem(data) {
        var item = data.item;
        var itemText = data.item_text || '';
        var itemData = data.item_data || {};
        var decision = data.decision;

        // Show item view, hide empty state
        if (emptyState) emptyState.style.display = 'none';
        if (itemView) itemView.style.display = 'block';
        if (navBar) navBar.style.display = 'flex';

        // Item header
        var idEl = document.getElementById('adj-item-id');
        if (idEl) idEl.textContent = 'Item: ' + item.instance_id;

        var agEl = document.getElementById('adj-item-agreement');
        if (agEl) {
            agEl.innerHTML = getAgreementBadge(item.overall_agreement);
        }

        var annEl = document.getElementById('adj-item-annotators');
        if (annEl) annEl.textContent = item.num_annotators + ' annotators';

        // Check if any schema is a span type
        var hasSpans = schemes.some(function(s) {
            return s.annotation_type === 'span';
        });

        // Item text - render with span overlay container if needed
        var textEl = document.getElementById('adj-item-text');
        if (textEl) {
            if (hasSpans && itemText) {
                // Render text with a span overlay container for dashed overlays
                textEl.innerHTML = '<div class="adj-span-text-container" id="adj-span-text-container">' +
                    '<div class="adj-span-overlays" id="adj-span-overlays"></div>' +
                    '<div class="adj-span-text-content" id="adj-span-text-content">' +
                    AdjudicationForms.escapeHtml(itemText) + '</div></div>';
            } else if (typeof itemData === 'object' && Object.keys(itemData).length > 0) {
                // Show all fields
                var html = '';
                Object.keys(itemData).forEach(function (key) {
                    var val = itemData[key];
                    if (typeof val === 'string') {
                        html += '<div style="margin-bottom: 8px;">' +
                            '<strong style="font-size: 0.8rem; color: #6b7280;">' +
                            AdjudicationForms.escapeHtml(key) + ':</strong><br>' +
                            AdjudicationForms.escapeHtml(val) + '</div>';
                    }
                });
                textEl.innerHTML = html || AdjudicationForms.escapeHtml(itemText);
            } else {
                textEl.textContent = itemText;
            }
        }

        // Reset form state
        AdjudicationForms.resetColors();
        // Clear adopted spans
        window._adjAdoptedSpans = {};
        // Store span data globally for adopt functions
        window._adjSpanData = item.span_annotations || {};

        // Render annotator responses + decision forms per schema
        renderResponsesAndForms(item);

        // Render span overlays on the text if we have spans
        if (hasSpans && item.span_annotations) {
            renderSpanOverlays(item.span_annotations, itemText);
        }

        // If there's an existing decision, populate it
        if (decision) {
            populateExistingDecision(decision);
        }

        // Reset metadata fields
        resetMetadata();

        // Bind form interactions
        AdjudicationForms.bindFormEvents();
    }

    /**
     * Render dashed span overlays for all annotators on the text
     */
    function renderSpanOverlays(spanAnnotations, text) {
        var container = document.getElementById('adj-span-text-content');
        var overlayContainer = document.getElementById('adj-span-overlays');
        if (!container || !overlayContainer || !text) return;

        // Wait a frame for layout to settle
        requestAnimationFrame(function() {
            var containerRect = container.getBoundingClientRect();
            overlayContainer.innerHTML = '';

            // Color palette for annotators (matching chip colors but as border colors)
            var borderColors = [
                '#3b82f6', '#22c55e', '#f59e0b', '#ec4899',
                '#6366f1', '#f97316', '#10b981', '#a855f7'
            ];
            var annotatorColorIdx = 0;
            var annotatorColors = {};

            Object.keys(spanAnnotations).forEach(function(userId) {
                if (!annotatorColors[userId]) {
                    annotatorColors[userId] = borderColors[annotatorColorIdx % borderColors.length];
                    annotatorColorIdx++;
                }

                var spans = spanAnnotations[userId];
                if (!spans || spans.length === 0) return;

                var color = annotatorColors[userId];

                spans.forEach(function(span) {
                    var start = span.start;
                    var end = span.end;
                    if (start === undefined || end === undefined) return;

                    // Calculate positions using Range API
                    var positions = getTextPositions(container, start, end);
                    if (!positions || positions.length === 0) return;

                    positions.forEach(function(pos) {
                        var overlay = document.createElement('div');
                        overlay.className = 'adj-span-overlay';
                        overlay.style.left = pos.left + 'px';
                        overlay.style.top = pos.top + 'px';
                        overlay.style.width = pos.width + 'px';
                        overlay.style.height = pos.height + 'px';
                        overlay.style.borderColor = color;
                        overlay.title = (span.name || 'span') + ' (' + userId + ')';

                        // Add a label on the first segment
                        if (pos === positions[0]) {
                            var label = document.createElement('span');
                            label.className = 'adj-span-overlay-label';
                            label.style.backgroundColor = color;
                            label.textContent = (span.name || 'span') + ' (' + userId + ')';
                            overlay.appendChild(label);
                        }

                        overlayContainer.appendChild(overlay);
                    });
                });
            });
        });
    }

    /**
     * Get pixel positions for a text range using the Range API
     */
    function getTextPositions(container, startOffset, endOffset) {
        var textNode = null;
        var walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, null, false);
        var currentOffset = 0;
        var positions = [];

        // Find the text nodes and create a range
        var range = document.createRange();
        var rangeStartSet = false;
        var rangeEndSet = false;

        while (walker.nextNode()) {
            var node = walker.currentNode;
            var nodeLen = node.textContent.length;
            var nodeStart = currentOffset;
            var nodeEnd = currentOffset + nodeLen;

            if (!rangeStartSet && startOffset >= nodeStart && startOffset <= nodeEnd) {
                range.setStart(node, startOffset - nodeStart);
                rangeStartSet = true;
            }

            if (!rangeEndSet && endOffset >= nodeStart && endOffset <= nodeEnd) {
                range.setEnd(node, endOffset - nodeStart);
                rangeEndSet = true;
                break;
            }

            currentOffset = nodeEnd;
        }

        if (!rangeStartSet || !rangeEndSet) return positions;

        var containerRect = container.getBoundingClientRect();
        var rects = range.getClientRects();

        for (var i = 0; i < rects.length; i++) {
            positions.push({
                left: rects[i].left - containerRect.left,
                top: rects[i].top - containerRect.top,
                width: rects[i].width,
                height: rects[i].height
            });
        }

        return positions;
    }

    /**
     * Render annotator response cards and decision forms for each schema
     */
    function renderResponsesAndForms(item) {
        var responsesContainer = document.getElementById('adj-responses-container');
        var decisionsContainer = document.getElementById('adj-decision-forms');

        if (!responsesContainer || !decisionsContainer) return;

        responsesContainer.innerHTML = '';
        decisionsContainer.innerHTML = '';

        schemes.forEach(function (schema) {
            var schemaName = schema.name || '';
            var schemaType = schema.annotation_type || '';

            // Skip display-only types
            if (schemaType === 'pure_display' || schemaType === 'video') return;

            // For span type, check span_annotations instead of annotations
            var isSpanType = (schemaType === 'span');
            var isComplexType = (schemaType === 'image_annotation' || schemaType === 'audio_annotation' || schemaType === 'video_annotation');

            var agreement = item.agreement_scores[schemaName];
            var agreementHtml = '';
            if (agreement !== undefined && config.show_agreement_scores) {
                agreementHtml = getAgreementBadge(agreement);
            }

            // Annotator responses section
            var responseHtml = '<div class="adj-schema-group">';
            responseHtml += '<div class="adj-schema-header">';
            responseHtml += '<span class="adj-schema-name">' +
                AdjudicationForms.escapeHtml(schemaName) +
                ' <span class="text-muted" style="font-weight: normal; font-size: 0.8rem;">(' + schemaType + ')</span></span>';
            responseHtml += '<span>' + agreementHtml + '</span>';
            responseHtml += '</div>';

            if (isSpanType) {
                // For spans, show summary per annotator (spans are visualized as dashed overlays on text)
                responseHtml += '<div class="adj-annotator-cards">';
                Object.keys(item.span_annotations || {}).forEach(function (userId) {
                    var spans = item.span_annotations[userId] || [];
                    var schemaSpans = spans.filter(function(s) { return s.schema === schemaName || !s.schema; });
                    if (schemaSpans.length === 0) return;

                    var timing = AdjudicationForms.formatTime(
                        item.behavioral_data[userId] ?
                            (item.behavioral_data[userId].total_time_ms || 0) : 0
                    );

                    responseHtml += '<div class="adj-annotator-card" data-annotator="' + userId + '">';
                    responseHtml += '<div class="adj-annotator-name">' +
                        (config.show_annotator_names ? AdjudicationForms.escapeHtml(userId) : 'Annotator') + '</div>';
                    responseHtml += '<div class="adj-annotator-value">' + schemaSpans.length + ' span(s)</div>';
                    schemaSpans.forEach(function(span) {
                        responseHtml += '<div class="adj-span-summary">' +
                            '<span class="adj-span-label-badge" style="font-size:0.7rem;">' +
                            AdjudicationForms.escapeHtml(span.name || 'span') + '</span> ' +
                            '<span style="font-size:0.75rem;color:#6b7280;">' +
                            AdjudicationForms.escapeHtml(span.title || ('chars ' + span.start + '-' + span.end)) + '</span></div>';
                    });
                    if (config.show_timing_data && timing) {
                        responseHtml += '<div class="adj-annotator-timing">';
                        responseHtml += '<i class="fas fa-clock"></i> ' + timing;
                        responseHtml += '</div>';
                    }
                    responseHtml += '</div>';
                });
                responseHtml += '</div>';
            } else if (isComplexType) {
                // For image/audio/video, show summary per annotator
                responseHtml += '<div class="adj-annotator-cards">';
                Object.keys(item.annotations).forEach(function (userId) {
                    var userAnn = item.annotations[userId];
                    var schemaVal = userAnn[schemaName];
                    if (schemaVal === undefined) return;

                    var summary = formatComplexAnnotationSummary(schemaVal, schemaType);
                    var timing = AdjudicationForms.formatTime(
                        item.behavioral_data[userId] ?
                            (item.behavioral_data[userId].total_time_ms || 0) : 0
                    );

                    responseHtml += '<div class="adj-annotator-card" data-annotator="' + userId + '">';
                    responseHtml += '<div class="adj-annotator-name">' +
                        (config.show_annotator_names ? AdjudicationForms.escapeHtml(userId) : 'Annotator') + '</div>';
                    responseHtml += '<div class="adj-annotator-value">' + summary + '</div>';
                    if (config.show_timing_data && timing) {
                        responseHtml += '<div class="adj-annotator-timing">';
                        responseHtml += '<i class="fas fa-clock"></i> ' + timing;
                        responseHtml += '</div>';
                    }
                    responseHtml += '</div>';
                });
                responseHtml += '</div>';
            } else {
                // Standard label annotations
                responseHtml += '<div class="adj-annotator-cards">';
                Object.keys(item.annotations).forEach(function (userId) {
                    var userAnn = item.annotations[userId];
                    var schemaVal = userAnn[schemaName];
                    if (schemaVal === undefined) return;

                    var valueStr = formatAnnotationValue(schemaVal);
                    var timing = AdjudicationForms.formatTime(
                        item.behavioral_data[userId] ?
                            (item.behavioral_data[userId].total_time_ms || 0) : 0
                    );
                    var isFast = config.fast_decision_warning_ms > 0 &&
                        item.behavioral_data[userId] &&
                        item.behavioral_data[userId].total_time_ms > 0 &&
                        item.behavioral_data[userId].total_time_ms < config.fast_decision_warning_ms;

                    responseHtml += '<div class="adj-annotator-card" data-annotator="' + userId + '">';
                    responseHtml += '<div class="adj-annotator-name">' +
                        (config.show_annotator_names ? AdjudicationForms.escapeHtml(userId) : 'Annotator') + '</div>';
                    responseHtml += '<div class="adj-annotator-value">' + AdjudicationForms.escapeHtml(valueStr) + '</div>';

                    if (config.show_timing_data && timing) {
                        responseHtml += '<div class="adj-annotator-timing' + (isFast ? ' adj-timing-warning' : '') + '">';
                        responseHtml += '<i class="fas fa-clock"></i> ' + timing;
                        if (isFast) responseHtml += ' <i class="fas fa-exclamation-triangle"></i>';
                        responseHtml += '</div>';
                    }
                    responseHtml += '</div>';
                });
                responseHtml += '</div>';
            }

            responseHtml += '</div>';
            responsesContainer.innerHTML += responseHtml;

            // Decision form
            var formHtml = '<div class="adj-decision-schema">';
            formHtml += '<div class="adj-decision-schema-name">' + AdjudicationForms.escapeHtml(schemaName) + '</div>';
            formHtml += AdjudicationForms.renderForm(schema, item.annotations, item.behavioral_data, config, item.span_annotations);
            formHtml += '</div>';

            decisionsContainer.innerHTML += formHtml;
        });
    }

    /**
     * Format a summary of complex annotation data
     */
    function formatComplexAnnotationSummary(val, schemaType) {
        try {
            var data = typeof val === 'string' ? JSON.parse(val) : val;
            if (schemaType === 'image_annotation') {
                if (Array.isArray(data)) return data.length + ' annotation(s)';
                return '1 annotation';
            }
            if (schemaType === 'audio_annotation' || schemaType === 'video_annotation') {
                if (data.segments) return data.segments.length + ' segment(s)';
                return 'annotated';
            }
        } catch(e) { /* ignore */ }
        return 'annotated';
    }

    /**
     * Format an annotation value for display
     */
    function formatAnnotationValue(val) {
        if (typeof val === 'string') return val;
        if (typeof val === 'number') return String(val);
        if (typeof val === 'object' && val !== null) {
            var selected = Object.keys(val).filter(function (k) {
                return val[k] === true || val[k] === 'true' || val[k] === 1;
            });
            if (selected.length > 0) return selected.join(', ');
            return JSON.stringify(val);
        }
        return String(val);
    }

    /**
     * Populate forms with an existing decision
     */
    function populateExistingDecision(decision) {
        var labels = decision.label_decisions || {};
        Object.keys(labels).forEach(function (schema) {
            var val = labels[schema];

            // Try radio
            var radioInput = document.querySelector(
                'input[name="adj-radio-' + schema + '"][value="' + val + '"]'
            );
            if (radioInput) {
                radioInput.checked = true;
                var option = radioInput.closest('.adj-radio-option');
                if (option) option.classList.add('selected');
                return;
            }

            // Try checkbox
            if (typeof val === 'object') {
                Object.keys(val).forEach(function (k) {
                    if (val[k]) {
                        var cb = document.querySelector(
                            'input[name="adj-check-' + schema + '"][value="' + k + '"]'
                        );
                        if (cb) {
                            cb.checked = true;
                            var opt = cb.closest('.adj-checkbox-option');
                            if (opt) opt.classList.add('selected');
                        }
                    }
                });
                return;
            }

            // Try likert/slider
            var slider = document.querySelector('.adj-likert-input[data-schema="' + schema + '"]');
            if (slider) {
                slider.value = val;
                var valDisplay = document.getElementById('adj-likert-val-' + schema);
                if (valDisplay) valDisplay.textContent = val;
                return;
            }

            // Try text
            var textarea = document.querySelector('textarea[data-schema="' + schema + '"]');
            if (textarea) {
                textarea.value = String(val);
            }
        });

        // Populate metadata
        if (decision.confidence) {
            var confEl = document.getElementById('adj-confidence');
            if (confEl) confEl.value = decision.confidence;
        }

        if (decision.notes) {
            var notesEl = document.getElementById('adj-notes');
            if (notesEl) notesEl.value = decision.notes;
        }

        if (decision.error_taxonomy && decision.error_taxonomy.length > 0) {
            decision.error_taxonomy.forEach(function (tag) {
                var tagEl = document.querySelector('.adj-error-tag[data-tag="' + tag + '"]');
                if (tagEl) {
                    tagEl.classList.add('selected');
                    var cb = tagEl.querySelector('input[type="checkbox"]');
                    if (cb) cb.checked = true;
                }
            });
        }
    }

    /**
     * Reset metadata fields
     */
    function resetMetadata() {
        var conf = document.getElementById('adj-confidence');
        if (conf) conf.value = 'medium';

        var notes = document.getElementById('adj-notes');
        if (notes) notes.value = '';

        document.querySelectorAll('.adj-error-tag').forEach(function (tag) {
            tag.classList.remove('selected');
            var cb = tag.querySelector('input[type="checkbox"]');
            if (cb) cb.checked = false;
        });

        var gFlag = document.getElementById('adj-guideline-flag');
        if (gFlag) gFlag.checked = false;

        var gNotes = document.getElementById('adj-guideline-notes');
        if (gNotes) gNotes.classList.remove('visible');

        var gText = document.getElementById('adj-guideline-text');
        if (gText) gText.value = '';
    }

    /**
     * Submit the current adjudication decision
     */
    function submitDecision() {
        if (!currentItemId) return;

        var result = AdjudicationForms.collectDecisions();
        if (Object.keys(result.decisions).length === 0) {
            alert('Please make at least one annotation decision before submitting.');
            return;
        }

        var timeSpent = itemStartTime ? Date.now() - itemStartTime : 0;

        // Collect error taxonomy
        var errorTags = [];
        document.querySelectorAll('.adj-error-tag input:checked').forEach(function (cb) {
            errorTags.push(cb.value);
        });

        var payload = {
            instance_id: currentItemId,
            label_decisions: result.decisions,
            span_decisions: result.spanDecisions || [],
            source: result.sources,
            confidence: (document.getElementById('adj-confidence') || {}).value || 'medium',
            notes: (document.getElementById('adj-notes') || {}).value || '',
            error_taxonomy: errorTags,
            guideline_update_flag: (document.getElementById('adj-guideline-flag') || {}).checked || false,
            guideline_update_notes: (document.getElementById('adj-guideline-text') || {}).value || '',
            time_spent_ms: timeSpent
        };

        fetch('/adjudicate/api/submit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.error) {
                    alert('Error: ' + data.error);
                    return;
                }
                // Move to next item
                goToNext();
                // Refresh queue
                loadQueue(currentFilter === 'all' ? null : currentFilter);
            })
            .catch(function (err) {
                console.error('Failed to submit decision:', err);
                alert('Failed to submit decision. Please try again.');
            });
    }

    /**
     * Skip the current item
     */
    function skipItem() {
        if (!currentItemId) return;

        fetch('/adjudicate/api/skip/' + encodeURIComponent(currentItemId), {
            method: 'POST'
        })
            .then(function (r) { return r.json(); })
            .then(function () {
                goToNext();
                loadQueue(currentFilter === 'all' ? null : currentFilter);
            });
    }

    /**
     * Navigate to next item
     */
    function goToNext() {
        if (currentQueueIndex < queue.length - 1) {
            selectQueueItem(currentQueueIndex + 1);
        } else {
            // Try to fetch next from API
            fetch('/adjudicate/api/next')
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (data.item) {
                        loadQueue(currentFilter === 'all' ? null : currentFilter);
                    } else {
                        // No more items
                        if (itemView) itemView.style.display = 'none';
                        if (emptyState) {
                            emptyState.style.display = 'flex';
                            emptyState.innerHTML = '<i class="fas fa-check-circle" style="color: #16a34a;"></i>' +
                                '<h5>All Done!</h5>' +
                                '<p>No more items to adjudicate.</p>';
                        }
                        if (navBar) navBar.style.display = 'none';
                    }
                });
        }
    }

    /**
     * Navigate to previous item using navigation history
     */
    function goToPrev() {
        if (navHistoryPos > 0) {
            navHistoryPos--;
            var prevId = navHistory[navHistoryPos];
            currentItemId = prevId;

            // Try to highlight in the sidebar queue
            var found = queue.findIndex(function (i) { return i.instance_id === prevId; });
            if (found >= 0) {
                currentQueueIndex = found;
                if (queueList) {
                    queueList.querySelectorAll('.adj-queue-item').forEach(function (el, i) {
                        el.classList.toggle('active', i === found);
                    });
                }
            } else {
                // Item not in current filtered queue (e.g. completed item in pending view)
                currentQueueIndex = -1;
                if (queueList) {
                    queueList.querySelectorAll('.adj-queue-item').forEach(function (el) {
                        el.classList.remove('active');
                    });
                }
            }

            loadItem(prevId);
        }
    }

    /**
     * Bind navigation button events
     */
    function bindNavigation() {
        var submitBtn = document.getElementById('adj-btn-submit');
        if (submitBtn) {
            submitBtn.addEventListener('click', submitDecision);
        }

        var skipBtn = document.getElementById('adj-btn-skip');
        if (skipBtn) {
            skipBtn.addEventListener('click', skipItem);
        }

        var prevBtn = document.getElementById('adj-btn-prev');
        if (prevBtn) {
            prevBtn.addEventListener('click', goToPrev);
        }

        // Keyboard shortcuts
        document.addEventListener('keydown', function (e) {
            // Only handle when not in an input/textarea
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') {
                return;
            }

            if (e.key === 'ArrowRight' || e.key === 'n') {
                e.preventDefault();
                goToNext();
            } else if (e.key === 'ArrowLeft' || e.key === 'p') {
                e.preventDefault();
                goToPrev();
            } else if (e.key === 'Enter' && e.ctrlKey) {
                e.preventDefault();
                submitDecision();
            }
        });
    }

    /**
     * Render similar items panel (Phase 3)
     */
    function renderSimilarItems(similarItems) {
        var panel = document.getElementById('adj-similar-items-panel');
        if (!panel || !similarItems || similarItems.length === 0) {
            if (panel) panel.style.display = 'none';
            return;
        }

        panel.style.display = 'block';

        var html = '<div class="adj-similar-header">' +
            '<h5><i class="fas fa-link"></i> Similar Items</h5>' +
            '<span class="text-muted" style="font-size:0.8rem;">' +
            similarItems.length + ' found</span></div>';

        html += '<div class="adj-similar-items-list">';

        similarItems.forEach(function (si, idx) {
            var pct = Math.round(si.similarity * 100);
            var scoreClass = 'adj-similarity-low';
            if (pct >= 70) scoreClass = 'adj-similarity-high';
            else if (pct >= 50) scoreClass = 'adj-similarity-medium';

            var metaHtml = '';
            if (si.decision === 'completed') {
                metaHtml += '<span class="adj-badge adj-badge-success">Decided</span>';
            } else if (si.consensus_label) {
                metaHtml += '<span class="adj-badge adj-badge-info">' +
                    AdjudicationForms.escapeHtml(si.consensus_label) + '</span>';
            }

            if (si.overall_agreement !== null && si.overall_agreement !== undefined) {
                metaHtml += getAgreementBadge(si.overall_agreement);
            }

            html += '<div class="adj-similar-item" data-similar-id="' +
                AdjudicationForms.escapeHtml(si.instance_id) + '">' +
                '<div class="adj-similarity-score ' + scoreClass + '">' +
                pct + '%</div>' +
                '<div class="adj-similar-info">' +
                '<div class="adj-similar-info-id">' +
                AdjudicationForms.escapeHtml(si.instance_id) + '</div>' +
                '<div class="adj-similar-preview">' +
                AdjudicationForms.escapeHtml(si.text_preview || '') + '</div>' +
                '</div>' +
                '<div class="adj-similar-meta">' + metaHtml + '</div>' +
                '</div>';
        });

        html += '</div>';
        panel.innerHTML = html;

        // Click handler: navigate to item in queue
        panel.querySelectorAll('.adj-similar-item').forEach(function (el) {
            el.addEventListener('click', function () {
                var targetId = el.getAttribute('data-similar-id');
                var idx = queue.findIndex(function (q) {
                    return q.instance_id === targetId;
                });
                if (idx >= 0) {
                    selectQueueItem(idx);
                }
            });
        });
    }

    /**
     * Render annotator signal badges (Phase 3)
     */
    function renderAnnotatorSignals(signalsData) {
        if (!signalsData) return;

        Object.keys(signalsData).forEach(function (userId) {
            var signals = signalsData[userId];
            if (!signals || !signals.flags || signals.flags.length === 0) return;

            // Find the annotator card(s) for this user
            var cards = document.querySelectorAll(
                '.adj-annotator-card[data-annotator="' + userId + '"]'
            );

            cards.forEach(function (card) {
                // Remove any existing signal badges
                var existing = card.querySelector('.adj-signal-flags');
                if (existing) existing.remove();

                var flagsDiv = document.createElement('div');
                flagsDiv.className = 'adj-signal-flags';

                signals.flags.forEach(function (flag) {
                    var badge = document.createElement('span');
                    badge.className = 'adj-signal-badge adj-signal-' +
                        (flag.severity || 'medium');
                    badge.title = flag.message || '';
                    badge.innerHTML = '<i class="fas fa-exclamation-triangle"></i> ' +
                        AdjudicationForms.escapeHtml(
                            (flag.type || '').replace(/_/g, ' ')
                        );
                    flagsDiv.appendChild(badge);
                });

                card.appendChild(flagsDiv);
            });
        });
    }

    /**
     * Bind filter button events
     */
    function bindFilters() {
        document.querySelectorAll('.adj-filter-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                document.querySelectorAll('.adj-filter-btn').forEach(function (b) {
                    b.classList.remove('active');
                });
                this.classList.add('active');

                currentFilter = this.dataset.filter || 'pending';
                loadQueue(currentFilter === 'all' ? null : currentFilter);
            });
        });
    }

    // Initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
