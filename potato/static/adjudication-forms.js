/**
 * Adjudication Forms Module
 *
 * Custom compact decision forms for each annotation schema type.
 * These forms show annotator choices inline and let the adjudicator
 * pick from existing annotations or create their own.
 */

window.AdjudicationForms = (function () {
    'use strict';

    // Color classes for annotator chips
    const CHIP_COLORS = [
        'adj-color-0', 'adj-color-1', 'adj-color-2', 'adj-color-3',
        'adj-color-4', 'adj-color-5', 'adj-color-6', 'adj-color-7'
    ];

    // Map annotator names to consistent colors
    let annotatorColorMap = {};
    let colorIndex = 0;

    function getAnnotatorColor(annotatorId) {
        if (!(annotatorId in annotatorColorMap)) {
            annotatorColorMap[annotatorId] = CHIP_COLORS[colorIndex % CHIP_COLORS.length];
            colorIndex++;
        }
        return annotatorColorMap[annotatorId];
    }

    function resetColors() {
        annotatorColorMap = {};
        colorIndex = 0;
    }

    /**
     * Format milliseconds as human-readable time
     */
    function formatTime(ms) {
        if (!ms || ms <= 0) return '';
        var seconds = Math.round(ms / 1000);
        if (seconds < 60) return seconds + 's';
        var minutes = Math.floor(seconds / 60);
        var secs = seconds % 60;
        return minutes + 'm' + (secs > 0 ? secs + 's' : '');
    }

    /**
     * Create annotator chip HTML
     */
    function createChip(annotatorId, timing, showName, fastWarningMs) {
        var colorClass = getAnnotatorColor(annotatorId);
        var name = showName ? annotatorId : 'Annotator';
        var timeStr = formatTime(timing);
        var isWarning = fastWarningMs > 0 && timing > 0 && timing < fastWarningMs;

        var timingHtml = '';
        if (timeStr) {
            var cls = isWarning ? 'adj-chip-timing adj-timing-warning' : 'adj-chip-timing';
            timingHtml = '<span class="' + cls + '">' +
                (isWarning ? '<i class="fas fa-exclamation-triangle"></i> ' : '') +
                timeStr + '</span>';
        }

        return '<span class="adj-annotator-chip ' + colorClass + '" ' +
            'data-annotator="' + annotatorId + '" title="' + annotatorId + '">' +
            name + timingHtml + '</span>';
    }

    /**
     * Get timing data for an annotator on this item
     */
    function getTimingMs(behavioralData, annotatorId) {
        if (!behavioralData || !behavioralData[annotatorId]) return 0;
        var bd = behavioralData[annotatorId];
        return bd.total_time_ms || bd.totalTimeMs || 0;
    }

    /**
     * Render a radio/single-choice schema form
     */
    function renderRadioForm(schema, annotations, behavioralData, config) {
        var labels = schema.labels || [];
        var schemaName = schema.name || '';

        // Build label -> annotators mapping
        var labelToAnnotators = {};
        labels.forEach(function(l) {
            var labelName = typeof l === 'string' ? l : l.name || l;
            labelToAnnotators[labelName] = [];
        });

        Object.keys(annotations).forEach(function(userId) {
            var userAnn = annotations[userId];
            if (!userAnn[schemaName]) return;

            var val = userAnn[schemaName];
            // Handle different annotation formats
            if (typeof val === 'object' && val !== null) {
                Object.keys(val).forEach(function(k) {
                    if (val[k] === true || val[k] === 'true' || val[k] === 1) {
                        if (!labelToAnnotators[k]) labelToAnnotators[k] = [];
                        labelToAnnotators[k].push(userId);
                    }
                });
            } else {
                var strVal = String(val);
                if (!labelToAnnotators[strVal]) labelToAnnotators[strVal] = [];
                labelToAnnotators[strVal].push(userId);
            }
        });

        var html = '<div class="adj-radio-options" data-schema="' + schemaName + '">';
        labels.forEach(function(l) {
            var labelName = typeof l === 'string' ? l : l.name || l;
            var annotators = labelToAnnotators[labelName] || [];

            var chipsHtml = '';
            annotators.forEach(function(uid) {
                var timing = getTimingMs(behavioralData, uid);
                chipsHtml += createChip(uid, timing, config.show_annotator_names, config.fast_decision_warning_ms);
            });

            html += '<label class="adj-radio-option" data-value="' + labelName + '">' +
                '<input type="radio" name="adj-radio-' + schemaName + '" value="' + labelName + '">' +
                '<span class="adj-radio-label">' + labelName + '</span>' +
                '<span class="adj-annotator-chips">' + chipsHtml + '</span>' +
                '</label>';
        });
        html += '</div>';

        return html;
    }

    /**
     * Render a multiselect/checkbox schema form
     */
    function renderMultiselectForm(schema, annotations, behavioralData, config) {
        var labels = schema.labels || [];
        var schemaName = schema.name || '';

        // Build label -> annotators mapping
        var labelToAnnotators = {};
        labels.forEach(function(l) {
            var labelName = typeof l === 'string' ? l : l.name || l;
            labelToAnnotators[labelName] = [];
        });

        Object.keys(annotations).forEach(function(userId) {
            var userAnn = annotations[userId];
            if (!userAnn[schemaName]) return;

            var val = userAnn[schemaName];
            if (typeof val === 'object' && val !== null) {
                Object.keys(val).forEach(function(k) {
                    if (val[k] === true || val[k] === 'true' || val[k] === 1) {
                        if (!labelToAnnotators[k]) labelToAnnotators[k] = [];
                        labelToAnnotators[k].push(userId);
                    }
                });
            }
        });

        var html = '<div class="adj-checkbox-options" data-schema="' + schemaName + '">';
        labels.forEach(function(l) {
            var labelName = typeof l === 'string' ? l : l.name || l;
            var annotators = labelToAnnotators[labelName] || [];

            var chipsHtml = '';
            annotators.forEach(function(uid) {
                var timing = getTimingMs(behavioralData, uid);
                chipsHtml += createChip(uid, timing, config.show_annotator_names, config.fast_decision_warning_ms);
            });

            html += '<label class="adj-checkbox-option" data-value="' + labelName + '">' +
                '<input type="checkbox" name="adj-check-' + schemaName + '" value="' + labelName + '">' +
                '<span class="adj-radio-label">' + labelName + '</span>' +
                '<span class="adj-annotator-chips">' + chipsHtml + '</span>' +
                '</label>';
        });
        html += '</div>';

        return html;
    }

    /**
     * Render a likert scale form
     */
    function renderLikertForm(schema, annotations, behavioralData, config) {
        var schemaName = schema.name || '';
        var minVal = schema.min_value || 1;
        var maxVal = schema.max_value || 5;
        var size = schema.size || maxVal;

        // Collect annotator values
        var annotatorValues = {};
        Object.keys(annotations).forEach(function(userId) {
            var userAnn = annotations[userId];
            if (!userAnn[schemaName]) return;

            var val = userAnn[schemaName];
            if (typeof val === 'object' && val !== null) {
                // Find the selected value in the dict
                Object.keys(val).forEach(function(k) {
                    if (val[k] === true || val[k] === 'true' || val[k] === 1) {
                        annotatorValues[userId] = parseInt(k);
                    }
                });
            } else {
                annotatorValues[userId] = parseInt(val) || 0;
            }
        });

        var range = maxVal - minVal;
        var html = '<div class="adj-likert-track" data-schema="' + schemaName + '">';
        html += '<div class="adj-likert-line"></div>';

        // Render annotator dots
        Object.keys(annotatorValues).forEach(function(uid) {
            var val = annotatorValues[uid];
            var pct = range > 0 ? ((val - minVal) / range * 100) : 50;
            var colorClass = getAnnotatorColor(uid);
            var bgStyle = '';
            // Extract background color from class
            var tempDiv = document.createElement('div');
            tempDiv.className = colorClass;

            html += '<div class="adj-likert-dot" style="left:' + pct + '%; background: #6366f1;" ' +
                'data-annotator="' + uid + '" data-value="' + val + '" ' +
                'title="' + uid + ': ' + val + '">' +
                '</div>';
            html += '<div class="adj-likert-dot-label" style="left:' + pct + '%">' + uid + ': ' + val + '</div>';
        });

        html += '</div>';
        html += '<div style="display: flex; align-items: center; gap: 8px; margin-top: 8px;">';
        html += '<label style="font-size: 0.85rem; font-weight: 500;">Your rating:</label>';
        html += '<input type="range" class="adj-likert-input form-range" ' +
            'name="adj-likert-' + schemaName + '" ' +
            'min="' + minVal + '" max="' + maxVal + '" step="1" ' +
            'data-schema="' + schemaName + '">';
        html += '<span class="adj-likert-value" id="adj-likert-val-' + schemaName + '">-</span>';
        html += '</div>';

        return html;
    }

    /**
     * Render a text/textarea form with merge support
     */
    function renderTextForm(schema, annotations, behavioralData, config) {
        var schemaName = schema.name || '';

        var html = '<div class="adj-text-responses" data-schema="' + schemaName + '">';

        Object.keys(annotations).forEach(function(userId) {
            var userAnn = annotations[userId];
            if (!userAnn[schemaName]) return;

            var val = userAnn[schemaName];
            var text = '';
            if (typeof val === 'object' && val !== null) {
                text = Object.values(val).join('; ');
            } else {
                text = String(val);
            }

            var timing = getTimingMs(behavioralData, userId);
            var timeStr = formatTime(timing);

            html += '<div class="adj-text-response" data-annotator="' + userId + '">';
            html += '<div class="adj-text-response-header">';
            html += '<label class="adj-text-select-label">' +
                '<input type="checkbox" class="adj-text-select-cb" data-annotator="' + userId + '" data-schema="' + schemaName + '">' +
                '</label>';
            html += '<span class="adj-annotator-name">' +
                (config.show_annotator_names ? userId : 'Annotator') + '</span>';
            if (timeStr) {
                html += '<span class="adj-annotator-timing"><i class="fas fa-clock"></i> ' + timeStr + '</span>';
            }
            html += '</div>';
            html += '<div class="adj-text-response-body">' + escapeHtml(text) + '</div>';
            html += '</div>';
        });

        html += '</div>';
        html += '<div class="adj-text-merge-bar" data-schema="' + schemaName + '">';
        html += '<button type="button" class="adj-text-merge-btn" data-action="select" data-schema="' + schemaName + '">' +
            '<i class="fas fa-check"></i> Use Selected</button>';
        html += '<button type="button" class="adj-text-merge-btn" data-action="merge" data-schema="' + schemaName + '">' +
            '<i class="fas fa-code-merge"></i> Merge Selected</button>';
        html += '</div>';
        html += '<div class="adj-text-decision-area">';
        html += '<textarea name="adj-text-' + schemaName + '" data-schema="' + schemaName + '" ' +
            'placeholder="Enter your decision, select a response above, or use the merge button..."></textarea>';
        html += '</div>';

        return html;
    }

    /**
     * Render a slider form
     */
    function renderSliderForm(schema, annotations, behavioralData, config) {
        // Reuse likert rendering - sliders are visually similar
        return renderLikertForm(schema, annotations, behavioralData, config);
    }

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * Render a span annotation adjudication form.
     * Shows each annotator's spans as a list with adopt buttons.
     * The actual dashed overlays are rendered by adjudication.js on the text container.
     */
    function renderSpanForm(schema, spanAnnotations, behavioralData, config) {
        var schemaName = schema.name || '';

        var html = '<div class="adj-span-form" data-schema="' + schemaName + '">';
        html += '<div class="adj-span-instructions">' +
            '<i class="fas fa-info-circle"></i> ' +
            'Annotator spans are shown as dashed highlights on the text above. ' +
            'Click "Adopt" to accept a span, or select text to create your own.' +
            '</div>';

        // List each annotator's spans
        Object.keys(spanAnnotations).forEach(function(userId) {
            var spans = spanAnnotations[userId];
            if (!spans || spans.length === 0) return;

            var schemaSpans = spans.filter(function(s) {
                return s.schema === schemaName || !s.schema;
            });
            if (schemaSpans.length === 0) return;

            var colorClass = getAnnotatorColor(userId);
            var timing = getTimingMs(behavioralData, userId);
            var timeStr = formatTime(timing);

            html += '<div class="adj-span-annotator-group">';
            html += '<div class="adj-span-annotator-header">';
            html += '<span class="adj-annotator-chip ' + colorClass + '">' +
                (config.show_annotator_names ? userId : 'Annotator') +
                (timeStr ? ' <span class="adj-chip-timing">' + timeStr + '</span>' : '') +
                '</span>';
            html += '<button type="button" class="adj-span-adopt-all-btn" data-annotator="' + userId +
                '" data-schema="' + schemaName + '"><i class="fas fa-check-double"></i> Adopt All</button>';
            html += '</div>';

            schemaSpans.forEach(function(span, idx) {
                var spanTitle = span.title || span.name || '';
                var spanText = spanTitle || ('chars ' + span.start + '-' + span.end);
                html += '<div class="adj-span-item" data-span-idx="' + idx + '" data-annotator="' + userId + '">';
                html += '<span class="adj-span-label-badge ' + colorClass + '">' +
                    escapeHtml(span.name || 'span') + '</span>';
                html += '<span class="adj-span-text">' + escapeHtml(spanText) + '</span>';
                html += '<button type="button" class="adj-span-adopt-btn" ' +
                    'data-annotator="' + userId + '" data-span-idx="' + idx +
                    '" data-schema="' + schemaName + '">' +
                    '<i class="fas fa-check"></i> Adopt</button>';
                html += '</div>';
            });
            html += '</div>';
        });

        // Adopted spans list
        html += '<div class="adj-adopted-spans" data-schema="' + schemaName + '">';
        html += '<div class="adj-adopted-header"><strong>Your Decision Spans:</strong></div>';
        html += '<div class="adj-adopted-list" id="adj-adopted-list-' + schemaName + '">';
        html += '<span class="text-muted" style="font-size:0.8rem;">No spans adopted yet</span>';
        html += '</div>';
        html += '</div>';
        html += '</div>';

        return html;
    }

    /**
     * Render an image annotation adjudication form.
     * Shows side-by-side comparison of each annotator's bounding boxes.
     */
    function renderImageForm(schema, annotations, behavioralData, config) {
        var schemaName = schema.name || '';

        var html = '<div class="adj-image-form" data-schema="' + schemaName + '">';
        html += '<div class="adj-complex-instructions">' +
            '<i class="fas fa-info-circle"></i> ' +
            'Each annotator\'s bounding boxes are listed below. Select annotations to include in your decision.' +
            '</div>';

        Object.keys(annotations).forEach(function(userId) {
            var userAnn = annotations[userId];
            if (!userAnn[schemaName]) return;

            var val = userAnn[schemaName];
            var boxes = [];
            try {
                if (typeof val === 'string') boxes = JSON.parse(val);
                else if (Array.isArray(val)) boxes = val;
                else if (typeof val === 'object') boxes = [val];
            } catch(e) { /* ignore */ }

            if (boxes.length === 0) return;

            var colorClass = getAnnotatorColor(userId);
            var timing = getTimingMs(behavioralData, userId);
            var timeStr = formatTime(timing);

            html += '<div class="adj-complex-annotator-group">';
            html += '<div class="adj-complex-annotator-header">';
            html += '<span class="adj-annotator-chip ' + colorClass + '">' +
                (config.show_annotator_names ? userId : 'Annotator') +
                (timeStr ? ' <span class="adj-chip-timing">' + timeStr + '</span>' : '') +
                '</span>';
            html += '<button type="button" class="adj-complex-adopt-all-btn" data-annotator="' + userId +
                '" data-schema="' + schemaName + '" data-type="image">' +
                '<i class="fas fa-check-double"></i> Adopt All</button>';
            html += '</div>';

            boxes.forEach(function(box, idx) {
                var label = box.label || box.type || 'annotation';
                var coords = box.coordinates || {};
                var detail = '';
                if (coords.x !== undefined) {
                    detail = 'x:' + Math.round(coords.x * 100) + '% y:' + Math.round(coords.y * 100) +
                        '% w:' + Math.round((coords.width || 0) * 100) + '% h:' + Math.round((coords.height || 0) * 100) + '%';
                }
                html += '<div class="adj-complex-item">';
                html += '<label><input type="checkbox" class="adj-complex-adopt-cb" data-annotator="' + userId +
                    '" data-idx="' + idx + '" data-schema="' + schemaName + '" data-type="image">';
                html += ' <span class="adj-span-label-badge ' + colorClass + '">' + escapeHtml(label) + '</span>';
                if (detail) html += ' <span class="adj-complex-detail">' + detail + '</span>';
                html += '</label></div>';
            });
            html += '</div>';
        });

        html += '</div>';
        return html;
    }

    /**
     * Render an audio/video segment adjudication form.
     * Shows segment timelines from each annotator for comparison.
     */
    function renderMediaForm(schema, annotations, behavioralData, config, mediaType) {
        var schemaName = schema.name || '';

        var html = '<div class="adj-media-form" data-schema="' + schemaName + '" data-media-type="' + mediaType + '">';
        html += '<div class="adj-complex-instructions">' +
            '<i class="fas fa-info-circle"></i> ' +
            'Each annotator\'s ' + mediaType + ' segments are listed below. Select segments to include in your decision.' +
            '</div>';

        Object.keys(annotations).forEach(function(userId) {
            var userAnn = annotations[userId];
            if (!userAnn[schemaName]) return;

            var val = userAnn[schemaName];
            var data = {};
            try {
                if (typeof val === 'string') data = JSON.parse(val);
                else if (typeof val === 'object') data = val;
            } catch(e) { /* ignore */ }

            var segments = data.segments || [];
            if (segments.length === 0 && !data.id) return;

            var colorClass = getAnnotatorColor(userId);
            var timing = getTimingMs(behavioralData, userId);
            var timeStr = formatTime(timing);

            html += '<div class="adj-complex-annotator-group">';
            html += '<div class="adj-complex-annotator-header">';
            html += '<span class="adj-annotator-chip ' + colorClass + '">' +
                (config.show_annotator_names ? userId : 'Annotator') +
                (timeStr ? ' <span class="adj-chip-timing">' + timeStr + '</span>' : '') +
                '</span>';
            html += '<button type="button" class="adj-complex-adopt-all-btn" data-annotator="' + userId +
                '" data-schema="' + schemaName + '" data-type="' + mediaType + '">' +
                '<i class="fas fa-check-double"></i> Adopt All</button>';
            html += '</div>';

            segments.forEach(function(seg, idx) {
                var label = seg.label || seg.labelText || 'segment';
                var startT = formatMediaTime(seg.start_time || seg.startTime || 0);
                var endT = formatMediaTime(seg.end_time || seg.endTime || 0);
                html += '<div class="adj-complex-item">';
                html += '<label><input type="checkbox" class="adj-complex-adopt-cb" data-annotator="' + userId +
                    '" data-idx="' + idx + '" data-schema="' + schemaName + '" data-type="' + mediaType + '">';
                html += ' <span class="adj-span-label-badge ' + colorClass + '">' + escapeHtml(label) + '</span>';
                html += ' <span class="adj-complex-detail">' + startT + ' - ' + endT + '</span>';
                html += '</label></div>';
            });

            // Show keyframes if video
            if (mediaType === 'video' && data.keyframes) {
                var keyframes = data.keyframes;
                if (keyframes.length > 0) {
                    html += '<div class="adj-complex-sub-section">Keyframes:</div>';
                    keyframes.forEach(function(kf, idx) {
                        var kfLabel = kf.label || 'keyframe';
                        var kfTime = formatMediaTime(kf.time || 0);
                        html += '<div class="adj-complex-item">';
                        html += '<label><input type="checkbox" class="adj-complex-adopt-cb" data-annotator="' + userId +
                            '" data-idx="kf-' + idx + '" data-schema="' + schemaName + '" data-type="keyframe">';
                        html += ' <span class="adj-span-label-badge ' + colorClass + '">' + escapeHtml(kfLabel) + '</span>';
                        html += ' <span class="adj-complex-detail">@ ' + kfTime + '</span>';
                        html += '</label></div>';
                    });
                }
            }
            html += '</div>';
        });

        html += '</div>';
        return html;
    }

    /**
     * Format seconds as MM:SS
     */
    function formatMediaTime(seconds) {
        if (!seconds && seconds !== 0) return '0:00';
        var mins = Math.floor(seconds / 60);
        var secs = Math.round(seconds % 60);
        return mins + ':' + (secs < 10 ? '0' : '') + secs;
    }

    /**
     * Render the appropriate form for a schema type
     */
    function renderForm(schema, annotations, behavioralData, config, spanAnnotations) {
        var type = schema.annotation_type || '';

        switch (type) {
            case 'radio':
            case 'select':
                return renderRadioForm(schema, annotations, behavioralData, config);
            case 'multiselect':
                return renderMultiselectForm(schema, annotations, behavioralData, config);
            case 'likert':
                return renderLikertForm(schema, annotations, behavioralData, config);
            case 'slider':
                return renderSliderForm(schema, annotations, behavioralData, config);
            case 'text':
            case 'textbox':
            case 'number':
                return renderTextForm(schema, annotations, behavioralData, config);
            case 'span':
                return renderSpanForm(schema, spanAnnotations || {}, behavioralData, config);
            case 'image_annotation':
                return renderImageForm(schema, annotations, behavioralData, config);
            case 'audio_annotation':
                return renderMediaForm(schema, annotations, behavioralData, config, 'audio');
            case 'video_annotation':
                return renderMediaForm(schema, annotations, behavioralData, config, 'video');
            default:
                return '<p class="text-muted">Form not available for type: ' + type + '</p>';
        }
    }

    /**
     * Collect decision values from all forms
     */
    function collectDecisions() {
        var decisions = {};
        var sources = {};
        var spanDecisions = [];

        // Radio forms
        document.querySelectorAll('.adj-radio-options').forEach(function(container) {
            var schema = container.dataset.schema;
            var checked = container.querySelector('input[type="radio"]:checked');
            if (checked) {
                decisions[schema] = checked.value;
                sources[schema] = 'adjudicator';
            }
        });

        // Checkbox forms
        document.querySelectorAll('.adj-checkbox-options').forEach(function(container) {
            var schema = container.dataset.schema;
            var checked = container.querySelectorAll('input[type="checkbox"]:checked');
            if (checked.length > 0) {
                var selected = {};
                checked.forEach(function(cb) {
                    selected[cb.value] = true;
                });
                decisions[schema] = selected;
                sources[schema] = 'adjudicator';
            }
        });

        // Likert/slider forms
        document.querySelectorAll('.adj-likert-input').forEach(function(input) {
            var schema = input.dataset.schema;
            if (input.value) {
                decisions[schema] = parseInt(input.value);
                sources[schema] = 'adjudicator';
            }
        });

        // Text forms
        document.querySelectorAll('.adj-text-decision-area textarea').forEach(function(textarea) {
            var schema = textarea.dataset.schema;
            if (textarea.value.trim()) {
                decisions[schema] = textarea.value.trim();
                sources[schema] = 'adjudicator';
            }
        });

        // Span decisions (collected from adopted spans store)
        if (window._adjAdoptedSpans) {
            Object.keys(window._adjAdoptedSpans).forEach(function(schema) {
                var spans = window._adjAdoptedSpans[schema];
                if (spans && spans.length > 0) {
                    spanDecisions = spanDecisions.concat(spans);
                    sources[schema] = 'adjudicator';
                }
            });
        }

        // Image/audio/video complex decisions (from checkboxes)
        document.querySelectorAll('.adj-image-form, .adj-media-form').forEach(function(form) {
            var schema = form.dataset.schema;
            var checked = form.querySelectorAll('.adj-complex-adopt-cb:checked');
            if (checked.length > 0) {
                var adopted = [];
                checked.forEach(function(cb) {
                    adopted.push({
                        annotator: cb.dataset.annotator,
                        idx: cb.dataset.idx,
                        type: cb.dataset.type
                    });
                });
                decisions[schema] = { adopted_annotations: adopted };
                sources[schema] = 'adjudicator';
            }
        });

        return { decisions: decisions, sources: sources, spanDecisions: spanDecisions };
    }

    /**
     * Bind interactive behaviors to forms
     */
    function bindFormEvents() {
        // Radio option styling
        document.querySelectorAll('.adj-radio-option').forEach(function(option) {
            option.addEventListener('click', function() {
                var container = this.closest('.adj-radio-options');
                container.querySelectorAll('.adj-radio-option').forEach(function(o) {
                    o.classList.remove('selected');
                });
                this.classList.add('selected');
                this.querySelector('input[type="radio"]').checked = true;
            });
        });

        // Checkbox option styling
        document.querySelectorAll('.adj-checkbox-option').forEach(function(option) {
            option.addEventListener('click', function(e) {
                if (e.target.type === 'checkbox') return;
                var cb = this.querySelector('input[type="checkbox"]');
                cb.checked = !cb.checked;
                this.classList.toggle('selected', cb.checked);
            });

            option.querySelector('input[type="checkbox"]').addEventListener('change', function() {
                option.classList.toggle('selected', this.checked);
            });
        });

        // Annotator chip clicks (auto-select that option)
        document.querySelectorAll('.adj-annotator-chip').forEach(function(chip) {
            chip.addEventListener('click', function(e) {
                e.stopPropagation();
                var option = this.closest('.adj-radio-option, .adj-checkbox-option');
                if (option) {
                    option.click();
                }
            });
        });

        // Likert dot clicks
        document.querySelectorAll('.adj-likert-dot').forEach(function(dot) {
            dot.addEventListener('click', function() {
                var val = this.dataset.value;
                var container = this.closest('.adj-likert-track');
                var schema = container.dataset.schema;
                var slider = document.querySelector('.adj-likert-input[data-schema="' + schema + '"]');
                if (slider) {
                    slider.value = val;
                    var valDisplay = document.getElementById('adj-likert-val-' + schema);
                    if (valDisplay) valDisplay.textContent = val;
                }
            });
        });

        // Likert slider value display
        document.querySelectorAll('.adj-likert-input').forEach(function(slider) {
            slider.addEventListener('input', function() {
                var schema = this.dataset.schema;
                var valDisplay = document.getElementById('adj-likert-val-' + schema);
                if (valDisplay) valDisplay.textContent = this.value;
            });
        });

        // Text response checkbox toggle styling
        document.querySelectorAll('.adj-text-response').forEach(function(resp) {
            resp.addEventListener('click', function(e) {
                // Don't toggle if clicking the checkbox itself
                if (e.target.type === 'checkbox') {
                    this.classList.toggle('selected', e.target.checked);
                    return;
                }
                var cb = this.querySelector('.adj-text-select-cb');
                if (cb) {
                    cb.checked = !cb.checked;
                    this.classList.toggle('selected', cb.checked);
                }
            });
        });

        // Text merge buttons
        document.querySelectorAll('.adj-text-merge-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var action = this.dataset.action;
                var schema = this.dataset.schema;
                var container = document.querySelector('.adj-text-responses[data-schema="' + schema + '"]');
                var textarea = document.querySelector('textarea[data-schema="' + schema + '"]');
                if (!container || !textarea) return;

                var selected = container.querySelectorAll('.adj-text-select-cb:checked');
                if (selected.length === 0) {
                    alert('Please select at least one response.');
                    return;
                }

                var texts = [];
                selected.forEach(function(cb) {
                    var resp = cb.closest('.adj-text-response');
                    var body = resp ? resp.querySelector('.adj-text-response-body') : null;
                    if (body) texts.push(body.textContent);
                });

                if (action === 'select') {
                    textarea.value = texts[0] || '';
                } else if (action === 'merge') {
                    textarea.value = texts.join('\n\n---\n\n');
                }
            });
        });

        // Error taxonomy toggles
        document.querySelectorAll('.adj-error-tag').forEach(function(tag) {
            tag.addEventListener('click', function(e) {
                if (e.target.type === 'checkbox') {
                    this.classList.toggle('selected', e.target.checked);
                    return;
                }
                var cb = this.querySelector('input[type="checkbox"]');
                cb.checked = !cb.checked;
                this.classList.toggle('selected', cb.checked);
            });
        });

        // Span adopt buttons
        document.querySelectorAll('.adj-span-adopt-btn').forEach(function(btn) {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                var annotator = this.dataset.annotator;
                var spanIdx = parseInt(this.dataset.spanIdx);
                var schema = this.dataset.schema;
                adoptSpan(schema, annotator, spanIdx);
            });
        });

        // Span adopt all buttons
        document.querySelectorAll('.adj-span-adopt-all-btn').forEach(function(btn) {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                var annotator = this.dataset.annotator;
                var schema = this.dataset.schema;
                adoptAllSpans(schema, annotator);
            });
        });

        // Complex type adopt all buttons
        document.querySelectorAll('.adj-complex-adopt-all-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var annotator = this.dataset.annotator;
                var schema = this.dataset.schema;
                var group = this.closest('.adj-complex-annotator-group');
                if (group) {
                    group.querySelectorAll('.adj-complex-adopt-cb').forEach(function(cb) {
                        if (cb.dataset.annotator === annotator) cb.checked = true;
                    });
                }
            });
        });

        // Guideline flag toggle
        var guidelineFlag = document.getElementById('adj-guideline-flag');
        if (guidelineFlag) {
            guidelineFlag.addEventListener('change', function() {
                var notes = document.getElementById('adj-guideline-notes');
                if (notes) {
                    notes.classList.toggle('visible', this.checked);
                }
            });
        }
    }

    /**
     * Adopt a single span from an annotator's list
     */
    function adoptSpan(schema, annotator, spanIdx) {
        if (!window._adjSpanData) return;
        var annotatorSpans = (window._adjSpanData[annotator] || []).filter(function(s) {
            return s.schema === schema || !s.schema;
        });
        if (spanIdx >= annotatorSpans.length) return;

        var span = JSON.parse(JSON.stringify(annotatorSpans[spanIdx]));
        span._source = annotator;

        if (!window._adjAdoptedSpans) window._adjAdoptedSpans = {};
        if (!window._adjAdoptedSpans[schema]) window._adjAdoptedSpans[schema] = [];

        // Avoid duplicates
        var isDupe = window._adjAdoptedSpans[schema].some(function(s) {
            return s.start === span.start && s.end === span.end && s.name === span.name;
        });
        if (!isDupe) {
            window._adjAdoptedSpans[schema].push(span);
        }

        renderAdoptedSpansList(schema);
    }

    /**
     * Adopt all spans from an annotator
     */
    function adoptAllSpans(schema, annotator) {
        if (!window._adjSpanData) return;
        var annotatorSpans = (window._adjSpanData[annotator] || []).filter(function(s) {
            return s.schema === schema || !s.schema;
        });
        annotatorSpans.forEach(function(span, idx) {
            adoptSpan(schema, annotator, idx);
        });
    }

    /**
     * Remove an adopted span
     */
    function removeAdoptedSpan(schema, idx) {
        if (!window._adjAdoptedSpans || !window._adjAdoptedSpans[schema]) return;
        window._adjAdoptedSpans[schema].splice(idx, 1);
        renderAdoptedSpansList(schema);
    }

    /**
     * Render the list of adopted spans for a schema
     */
    function renderAdoptedSpansList(schema) {
        var listEl = document.getElementById('adj-adopted-list-' + schema);
        if (!listEl) return;

        var spans = (window._adjAdoptedSpans && window._adjAdoptedSpans[schema]) || [];
        if (spans.length === 0) {
            listEl.innerHTML = '<span class="text-muted" style="font-size:0.8rem;">No spans adopted yet</span>';
            return;
        }

        var html = '';
        spans.forEach(function(span, idx) {
            var source = span._source || 'unknown';
            html += '<div class="adj-adopted-span-item">';
            html += '<span class="adj-span-label-badge" style="background:#dbeafe;color:#1d4ed8;">' +
                escapeHtml(span.name || 'span') + '</span>';
            html += '<span class="adj-span-text">' + escapeHtml(span.title || ('chars ' + span.start + '-' + span.end)) + '</span>';
            html += '<span class="text-muted" style="font-size:0.7rem;">from ' + escapeHtml(source) + '</span>';
            html += '<button type="button" class="adj-span-remove-btn" onclick="AdjudicationForms.removeAdoptedSpan(\'' +
                schema + '\', ' + idx + ')"><i class="fas fa-times"></i></button>';
            html += '</div>';
        });
        listEl.innerHTML = html;
    }

    // Public API
    return {
        renderForm: renderForm,
        collectDecisions: collectDecisions,
        bindFormEvents: bindFormEvents,
        resetColors: resetColors,
        getAnnotatorColor: getAnnotatorColor,
        formatTime: formatTime,
        escapeHtml: escapeHtml,
        adoptSpan: adoptSpan,
        adoptAllSpans: adoptAllSpans,
        removeAdoptedSpan: removeAdoptedSpan,
        renderAdoptedSpansList: renderAdoptedSpansList,
        CHIP_COLORS: CHIP_COLORS
    };
})();
