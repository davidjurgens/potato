/**
 * Think-Aloud Mode — voice rationales with rule-based spoken labels.
 *
 * A bottom-center pill starts/stops local recording. Audio is captured in
 * complete, independently-decodable chunks (MediaRecorder is restarted every
 * chunk_seconds — continuation fragments of one long recording are NOT
 * decodable on their own) and posted to /thinkaloud/api/chunk, where a local
 * STT backend transcribes it and a rule-based parser looks for a label
 * phrase ("I label this Polite"). On detection, the matching radio input is
 * clicked so the ordinary save pipeline (and any other widgets) fire.
 *
 * If require_spoken_label is on and the annotator hits Next without a
 * committed label, the pill nudges once with the expected phrasing; a second
 * Next passes through. Everything degrades gracefully: mic errors or server
 * failures leave normal click-annotation untouched.
 */
(function () {
    'use strict';

    var cfg = window.thinkAloudConfig;
    if (!cfg || !cfg.schema) return;

    var state = {
        recording: false,
        stream: null,
        recorder: null,
        cycleTimer: null,
        seq: 0,
        lastText: '',
        detected: null,   // {label, ...}
        nudged: false,
        pill: null
    };

    function esc(s) {
        var d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    }

    function instanceId() {
        var el = document.getElementById('instance_id');
        return el ? el.value : null;
    }

    function schemaLabelInput(label) {
        return document.querySelector(
            'input.annotation-input[schema="' + cfg.schema + '"][label_name="' + label + '"]');
    }

    function schemaHasSelection() {
        return !!document.querySelector(
            'input.annotation-input[schema="' + cfg.schema + '"]:checked');
    }

    // ----------------------------------------------------------------- ui --
    function ensurePill() {
        if (state.pill) return state.pill;
        var pill = document.createElement('div');
        pill.id = 'thinkaloud-pill';
        pill.className = 'ta-pill';
        pill.setAttribute('role', 'region');
        pill.setAttribute('aria-label', 'Think-aloud recording');
        pill.setAttribute('aria-live', 'polite');
        document.body.appendChild(pill);
        state.pill = pill;
        return pill;
    }

    function renderIdle(message) {
        var pill = ensurePill();
        pill.innerHTML =
            '<button type="button" class="ta-start">' +
            '  <span class="ta-mic" aria-hidden="true">&#127908;</span> Think aloud' +
            '</button>' +
            (message ? '<span class="ta-note">' + esc(message) + '</span>' : '');
        pill.querySelector('.ta-start').addEventListener('click', startRecording);
    }

    function renderRecording() {
        var pill = ensurePill();
        var status;
        if (state.detected) {
            status = '<span class="ta-heard">Heard: <strong>' +
                esc(state.detected.label) + '</strong> <span class="ta-check">&#10003;</span></span>';
        } else {
            status = '<span class="ta-hint">Say <em>&ldquo;I label this &hellip;&rdquo;</em> to commit a label</span>';
        }
        pill.innerHTML =
            '<span class="ta-dot" aria-hidden="true"></span>' +
            '<span class="ta-status">' + status +
            (state.lastText ? '<span class="ta-snippet">&ldquo;' + esc(trimSnippet(state.lastText)) + '&rdquo;</span>' : '') +
            '</span>' +
            '<button type="button" class="ta-stop">Stop</button>';
        pill.querySelector('.ta-stop').addEventListener('click', stopRecording);
    }

    function renderNudge() {
        var pill = ensurePill();
        pill.classList.add('ta-nudge-state');
        pill.innerHTML =
            '<span class="ta-nudge">No label heard yet &mdash; say ' +
            '<em>&ldquo;I label this &hellip;&rdquo;</em> (or tap a label), then Next.</span>' +
            '<button type="button" class="ta-stop">Stop recording</button>';
        pill.querySelector('.ta-stop').addEventListener('click', stopRecording);
        setTimeout(function () { pill.classList.remove('ta-nudge-state'); }, 3200);
    }

    function trimSnippet(text) {
        return text.length > 90 ? '…' + text.slice(-88) : text;
    }

    // ------------------------------------------------------------ recording --
    function pickMimeType() {
        var candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'];
        for (var i = 0; i < candidates.length; i++) {
            if (window.MediaRecorder && MediaRecorder.isTypeSupported(candidates[i])) {
                return candidates[i];
            }
        }
        return '';
    }

    function startRecording() {
        if (state.recording) return;
        if (!navigator.mediaDevices || !window.MediaRecorder) {
            renderIdle('Recording unsupported in this browser.');
            return;
        }
        navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
            state.stream = stream;
            state.recording = true;
            state.detected = null;
            state.lastText = '';
            renderRecording();
            recordCycle();
        }).catch(function () {
            renderIdle('Microphone unavailable or permission denied.');
        });
    }

    /** Record one complete chunk, upload it, then start the next cycle. */
    function recordCycle() {
        if (!state.recording || !state.stream) return;
        var mime = pickMimeType();
        var recorder = new MediaRecorder(state.stream, mime ? { mimeType: mime } : {});
        var parts = [];
        recorder.ondataavailable = function (e) {
            if (e.data && e.data.size) parts.push(e.data);
        };
        recorder.onstop = function () {
            if (parts.length) uploadChunk(new Blob(parts, { type: mime || 'audio/webm' }));
            recordCycle(); // next complete chunk
        };
        state.recorder = recorder;
        recorder.start();
        state.cycleTimer = setTimeout(function () {
            if (recorder.state !== 'inactive') recorder.stop();
        }, (cfg.chunk_seconds || 6) * 1000);
    }

    function stopRecording() {
        state.recording = false;
        clearTimeout(state.cycleTimer);
        if (state.recorder && state.recorder.state !== 'inactive') {
            try { state.recorder.stop(); } catch (e) { /* already stopped */ }
        }
        if (state.stream) {
            state.stream.getTracks().forEach(function (t) { t.stop(); });
            state.stream = null;
        }
        renderIdle(state.detected
            ? 'Committed "' + state.detected.label + '" by voice.'
            : null);
    }

    // -------------------------------------------------------------- upload --
    function uploadChunk(blob) {
        var id = instanceId();
        if (!id) return;
        var form = new FormData();
        form.append('audio', blob, 'chunk.webm');
        form.append('instance_id', id);
        form.append('seq', String(state.seq++));
        fetch('/thinkaloud/api/chunk', { method: 'POST', body: form })
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(handleResponse)
            .catch(function (err) {
                console.warn('Think-Aloud: chunk upload failed', err);
            });
    }

    function handleResponse(data) {
        if (!data) return;
        if (data.text) state.lastText = data.transcript || data.text;
        if (data.detection && data.detection.label) {
            var isNew = !state.detected ||
                state.detected.label !== data.detection.label;
            state.detected = data.detection;
            if (isNew) {
                var input = schemaLabelInput(data.detection.label);
                if (input && !input.checked) input.click();
            }
        }
        if (state.recording) renderRecording();
    }

    // ------------------------------------------------------- next-btn nudge --
    document.addEventListener('click', function (e) {
        if (!cfg.require_spoken_label || !state.recording || state.nudged) return;
        var next = e.target.closest && e.target.closest('#next-btn');
        if (!next) return;
        if (state.detected || schemaHasSelection()) return;
        e.preventDefault();
        e.stopPropagation();
        state.nudged = true;
        renderNudge();
    }, true);

    window.addEventListener('beforeunload', function () {
        if (state.stream) {
            state.stream.getTracks().forEach(function (t) { t.stop(); });
        }
    });

    // Expose for tests and degraded (text) input paths.
    window.thinkAloud = { handleResponse: handleResponse, state: state };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { renderIdle(); });
    } else {
        renderIdle();
    }
})();
