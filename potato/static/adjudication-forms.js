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
     * Render a text/textarea form
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
        html += '<div class="adj-text-decision-area">';
        html += '<textarea name="adj-text-' + schemaName + '" data-schema="' + schemaName + '" ' +
            'placeholder="Enter your decision or click a response above to adopt it..."></textarea>';
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
     * Render the appropriate form for a schema type
     */
    function renderForm(schema, annotations, behavioralData, config) {
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
            case 'number':
                return renderTextForm(schema, annotations, behavioralData, config);
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

        return { decisions: decisions, sources: sources };
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

        // Text response clicks (adopt text)
        document.querySelectorAll('.adj-text-response').forEach(function(resp) {
            resp.addEventListener('click', function() {
                var container = this.closest('.adj-text-responses');
                container.querySelectorAll('.adj-text-response').forEach(function(r) {
                    r.classList.remove('selected');
                });
                this.classList.add('selected');

                var body = this.querySelector('.adj-text-response-body');
                var schema = container.dataset.schema;
                var textarea = document.querySelector('textarea[data-schema="' + schema + '"]');
                if (textarea && body) {
                    textarea.value = body.textContent;
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

    // Public API
    return {
        renderForm: renderForm,
        collectDecisions: collectDecisions,
        bindFormEvents: bindFormEvents,
        resetColors: resetColors,
        getAnnotatorColor: getAnnotatorColor,
        formatTime: formatTime,
        escapeHtml: escapeHtml
    };
})();
