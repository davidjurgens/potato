/**
 * Audio Dialogue display frontend.
 *
 * Powers the `audio_dialogue` display (potato/server_utils/displays/
 * audio_dialogue_display.py): a synced audio transport, per-turn segment
 * playback, active-turn highlight + auto-scroll, and speaker assignment for
 * undiarized transcripts.
 *
 * Persistence contract (mirrors turn-annotations.js — see
 * internal/annotation-persistence.md):
 *  - Speaker assignments live in one hidden input per field:
 *      <input class="annotation-data-input ad-speaker-input" name="{field}_speakers">
 *    saveAnnotations() picks it up as `{field}_speakers:::_data`; the server
 *    restores it with `value` + `data-server-set="true"`.
 *  - We SEED from the server-restored value BEFORE painting (never from
 *    hardcoded defaults) to avoid the IIFE-overwrite bug.
 *  - The speaker <select> is a proxy (no `annotation-input` class) so the four
 *    global persistence functions ignore it.
 *
 * Span-offset stability: assignment only mutates CSS pseudo-content (via data-*
 * attributes) and CSS alignment/color — never .text-content text nodes and
 * never DOM order — so span offsets stay stable across assignment and reload.
 * Stored value format: {"v":1,"schema_type":"speaker_assignment","turns":{"t3":{"speaker":"guest"}}}.
 */
(function () {
    'use strict';

    // assignmentsByField[fieldKey] = { turns: { tid: { speaker: "<id>" } } }
    let assignmentsByField = {};
    let saveTimer = null;

    function roots() {
        return document.querySelectorAll('.audio-dialogue');
    }

    function parseJSONAttr(el, attr, fallback) {
        try { return JSON.parse(el.getAttribute(attr) || ''); } catch (e) { return fallback; }
    }

    function speakerInputFor(fieldKey) {
        return document.querySelector(
            'input.ad-speaker-input[name="' + CSS.escape(fieldKey + '_speakers') + '"]');
    }

    // ------------------------------------------------------------------
    // Time / formatting
    // ------------------------------------------------------------------

    function fmtTime(sec) {
        if (!isFinite(sec) || sec < 0) sec = 0;
        sec = Math.floor(sec);
        var m = Math.floor(sec / 60), s = sec % 60;
        var h = Math.floor(m / 60); m = m % 60;
        if (h) return h + ':' + String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
        return m + ':' + String(s).padStart(2, '0');
    }

    // ------------------------------------------------------------------
    // Speaker assignment: click-to-assign menu, add-speaker, seed/paint/persist
    //
    // State per field: { turns: {tid: {speaker: id|null}}, roster: {id: info} }
    //   - turns[tid] is an ANNOTATOR OVERRIDE (present => wins over the
    //     server-rendered diarization; {speaker:null} = explicitly unassigned).
    //   - roster holds speakers the annotator ADDED at runtime (unlimited), so
    //     they survive reload. Config speakers live on the root's data-ad-roster.
    // ------------------------------------------------------------------

    // Palette + contrast mirror the server (multi_agent_discussion_display).
    var AD_PALETTE = ['#2563eb', '#d97706', '#059669', '#dc2626', '#7c3aed',
                      '#0891b2', '#db2777', '#65a30d', '#ea580c', '#4f46e5'];

    function adHash(s) {
        var h = 0; s = String(s);
        for (var i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
        return h;
    }
    function adColor(id) { return AD_PALETTE[adHash(id) % AD_PALETTE.length]; }
    function adOn(hex) {
        var h = String(hex).replace('#', '');
        if (h.length !== 6) return '#fff';
        function lin(c) { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); }
        var L = 0.2126 * lin(parseInt(h.slice(0, 2), 16)) +
                0.7152 * lin(parseInt(h.slice(2, 4), 16)) +
                0.0722 * lin(parseInt(h.slice(4, 6), 16));
        return (L + 0.05) / 0.05 >= 1.05 / (L + 0.05) ? '#1c1917' : '#fff';
    }

    function ensureState(fieldKey) {
        return assignmentsByField[fieldKey] ||
            (assignmentsByField[fieldKey] = { turns: {}, roster: {} });
    }
    function configRoster(root) { return parseJSONAttr(root, 'data-ad-roster', {}); }
    function unassignedColor(root) {
        return (parseJSONAttr(root, 'data-ad-config', {}) || {}).unassigned_color || '#9ca3af';
    }
    function mergedRoster(root, fieldKey) {
        return Object.assign({}, configRoster(root), ensureState(fieldKey).roster);
    }
    function turnEl(root, tid) {
        return root.querySelector('.ad-turn[data-turn-id="' + CSS.escape(tid) + '"]');
    }

    function seedAssignments() {
        assignmentsByField = {};
        roots().forEach(function (root) {
            var fieldKey = root.getAttribute('data-field-key');
            if (!fieldKey) return;
            var input = speakerInputFor(fieldKey);
            var turns = {}, roster = {};
            if (input) {
                var serverSet = input.getAttribute('data-server-set') === 'true';
                var raw = serverSet ? (input.getAttribute('value') || input.value) : input.value;
                if (raw) {
                    try {
                        var parsed = JSON.parse(raw);
                        if (parsed && typeof parsed === 'object') {
                            turns = parsed.turns || {};
                            roster = parsed.roster || {};
                        }
                    } catch (e) {
                        console.warn('[audio-dialogue] bad stored speaker value for', fieldKey, e);
                    }
                }
            }
            assignmentsByField[fieldKey] = { turns: turns, roster: roster };
        });
    }

    function paintAssignments() {
        roots().forEach(function (root) {
            var fieldKey = root.getAttribute('data-field-key');
            var state = assignmentsByField[fieldKey];
            if (!state) return;
            var merged = mergedRoster(root, fieldKey);
            var neutral = unassignedColor(root);
            root.querySelectorAll('.ad-turn').forEach(function (turn) {
                var tid = turn.getAttribute('data-turn-id');
                if (!(tid in state.turns)) return;  // no override -> leave server render
                var entry = state.turns[tid];
                if (entry && entry.speaker) {
                    var info = merged[entry.speaker] || {
                        name: entry.speaker, color: adColor(entry.speaker),
                        side: 'left', on: adOn(adColor(entry.speaker)),
                    };
                    applySpeaker(turn, entry.speaker, info);
                } else {
                    clearSpeaker(turn, neutral);
                }
            });
        });
    }

    function applySpeaker(turn, speakerId, info) {
        turn.style.setProperty('--ad-color', info.color);
        turn.style.setProperty('--ad-on', info.on || adOn(info.color));
        turn.classList.remove('ad-unassigned', 'ad-side-left', 'ad-side-right');
        turn.classList.add('ad-assigned', 'ad-side-' + (info.side === 'right' ? 'right' : 'left'));
        turn.setAttribute('data-speaker', speakerId);
        var avatar = turn.querySelector('.ad-avatar');
        var name = turn.querySelector('.ad-speaker-name');
        if (avatar) avatar.setAttribute('data-initial', (info.name || '?').slice(0, 1).toUpperCase());
        if (name) name.setAttribute('data-name', info.name || speakerId);
        updateSpeakerAria(turn, info.name || speakerId);
    }

    function clearSpeaker(turn, neutral) {
        turn.style.setProperty('--ad-color', neutral);
        turn.style.setProperty('--ad-on', '#1c1917');
        turn.classList.remove('ad-assigned', 'ad-side-right');
        turn.classList.add('ad-unassigned', 'ad-side-left');
        turn.setAttribute('data-speaker', '');
        var avatar = turn.querySelector('.ad-avatar');
        var name = turn.querySelector('.ad-speaker-name');
        if (avatar) avatar.setAttribute('data-initial', '?');
        if (name) name.setAttribute('data-name', 'Unassigned');
        updateSpeakerAria(turn, 'Unassigned');
    }

    // Keep play + speaker-button aria labels in sync (speaker/time are otherwise
    // CSS pseudo-content, invisible to screen readers).
    function updateSpeakerAria(turn, speakerName) {
        var play = turn.querySelector('.ad-play');
        var time = turn.querySelector('.ad-time');
        var t = time ? (time.getAttribute('data-time') || '') : '';
        if (play) play.setAttribute('aria-label', 'Play this turn by ' + speakerName + (t ? ', ' + t : ''));
        var btn = turn.querySelector('.ad-speaker-btn');
        if (btn) btn.setAttribute('aria-label', 'Speaker: ' + speakerName + '. Click to change.');
    }

    function persist(fieldKey) {
        var state = assignmentsByField[fieldKey];
        var input = speakerInputFor(fieldKey);
        if (!state || !input) return;
        var hasTurns = Object.keys(state.turns).length > 0;
        var payload = { v: 1, schema_type: 'speaker_assignment', turns: state.turns };
        if (Object.keys(state.roster).length) payload.roster = state.roster;
        input.value = hasTurns ? JSON.stringify(payload) : '';
        input.setAttribute('data-modified', 'true');
        clearTimeout(saveTimer);
        saveTimer = setTimeout(function () {
            if (typeof window.saveAnnotations === 'function') window.saveAnnotations();
        }, 500);
    }

    // ---- assignment actions ----

    function assignSpeaker(root, fieldKey, tid, speakerId) {
        var info = mergedRoster(root, fieldKey)[speakerId];
        if (!info) return;
        ensureState(fieldKey).turns[tid] = { speaker: speakerId };
        var turn = turnEl(root, tid);
        if (turn) applySpeaker(turn, speakerId, info);
        persist(fieldKey);
    }

    function unassignSpeaker(root, fieldKey, tid) {
        ensureState(fieldKey).turns[tid] = { speaker: null };
        var turn = turnEl(root, tid);
        if (turn) clearSpeaker(turn, unassignedColor(root));
        persist(fieldKey);
    }

    function addSpeaker(root, fieldKey, tid) {
        var name = (window.prompt('Add a speaker label:') || '').trim();
        if (!name) return;
        var merged = mergedRoster(root, fieldKey);
        if (!merged[name]) {
            var color = adColor(name);
            var side = (Object.keys(merged).length % 2 === 0) ? 'left' : 'right';
            ensureState(fieldKey).roster[name] = { name: name, color: color, side: side, on: adOn(color) };
        }
        assignSpeaker(root, fieldKey, tid, name);
    }

    // ---- popover menu ----

    function closeMenus() {
        document.querySelectorAll('.ad-speaker-menu').forEach(function (m) { m.hidden = true; });
        document.querySelectorAll('.ad-speaker-btn[aria-expanded="true"]')
            .forEach(function (b) { b.setAttribute('aria-expanded', 'false'); });
    }

    function openMenu(btn) {
        var root = btn.closest('.audio-dialogue');
        var fieldKey = root.getAttribute('data-field-key');
        var menu = document.getElementById('ad-menu-' + fieldKey);
        if (!menu) return;
        var tid = btn.getAttribute('data-turn-id');
        var turn = turnEl(root, tid);
        var current = turn ? (turn.getAttribute('data-speaker') || '') : '';
        var merged = mergedRoster(root, fieldKey);

        menu.dataset.fieldKey = fieldKey;
        menu.dataset.turnId = tid;
        var items = Object.keys(merged).map(function (sid) {
            var info = merged[sid];
            var isCur = (sid === current);
            return '<button type="button" class="ad-menu-item' + (isCur ? ' is-current' : '') +
                '" role="menuitemradio" aria-checked="' + (isCur ? 'true' : 'false') +
                '" data-speaker="' + escAttr(sid) + '">' +
                '<span class="ad-menu-dot" style="background:' + escAttr(info.color) + ';color:' +
                escAttr(info.on || adOn(info.color)) + ';">' + escHtml((info.name || sid).slice(0, 1).toUpperCase()) +
                '</span><span class="ad-menu-label">' + escHtml(info.name || sid) + '</span>' +
                (isCur ? '<span class="ad-menu-check" aria-hidden="true">✓</span>' : '') + '</button>';
        });
        items.push('<div class="ad-menu-sep" role="separator"></div>');
        items.push('<button type="button" class="ad-menu-item ad-menu-unassign" role="menuitem" data-action="unassign">Unassigned</button>');
        items.push('<button type="button" class="ad-menu-item ad-menu-add" role="menuitem" data-action="add">＋ Add speaker…</button>');
        menu.innerHTML = items.join('');

        // Position under the button (menu is position:fixed).
        menu.hidden = false;
        var r = btn.getBoundingClientRect();
        var mw = menu.offsetWidth || 200;
        var left = Math.min(r.left, window.innerWidth - mw - 8);
        menu.style.left = Math.max(8, left) + 'px';
        var top = r.bottom + 4;
        if (top + menu.offsetHeight > window.innerHeight - 8) {
            top = Math.max(8, r.top - menu.offsetHeight - 4);
        }
        menu.style.top = top + 'px';
        btn.setAttribute('aria-expanded', 'true');
        var first = menu.querySelector('.ad-menu-item');
        if (first) first.focus();
    }

    function escHtml(s) { var d = document.createElement('div'); d.textContent = (s == null ? '' : s); return d.innerHTML; }
    function escAttr(s) { return escHtml(s).replace(/"/g, '&quot;'); }

    document.addEventListener('click', function (e) {
        var btn = e.target.closest && e.target.closest('.ad-speaker-btn');
        if (btn) {
            e.preventDefault();
            var expanded = btn.getAttribute('aria-expanded') === 'true';
            closeMenus();
            if (!expanded) openMenu(btn);
            return;
        }
        var item = e.target.closest && e.target.closest('.ad-menu-item');
        if (item) {
            e.preventDefault();
            var menu = item.closest('.ad-speaker-menu');
            var fieldKey = menu.dataset.fieldKey;
            var tid = menu.dataset.turnId;
            var root = document.querySelector('.audio-dialogue[data-field-key="' + CSS.escape(fieldKey) + '"]');
            var action = item.getAttribute('data-action');
            if (action === 'unassign') unassignSpeaker(root, fieldKey, tid);
            else if (action === 'add') addSpeaker(root, fieldKey, tid);
            else assignSpeaker(root, fieldKey, tid, item.getAttribute('data-speaker'));
            closeMenus();
            return;
        }
        if (!(e.target.closest && e.target.closest('.ad-speaker-menu'))) closeMenus();
    });

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') closeMenus();
    });

    // ------------------------------------------------------------------
    // Audio transport + per-turn playback
    // ------------------------------------------------------------------

    // Per-audio boundary for "play just this turn" (null = play through).
    var segmentEndByAudio = new WeakMap();

    function audioFor(fieldKey) {
        return document.getElementById('ad-audio-' + fieldKey);
    }

    function bindTransport() {
        roots().forEach(function (root) {
            var fieldKey = root.getAttribute('data-field-key');
            var audio = audioFor(fieldKey);
            if (!audio || audio.dataset.adBound === 'true') return;
            audio.dataset.adBound = 'true';

            var scrub = root.querySelector('.ad-scrub');
            var cur = root.querySelector('.ad-cur');
            var dur = root.querySelector('.ad-dur');
            var playpause = root.querySelector('.ad-playpause');

            audio.addEventListener('loadedmetadata', function () {
                if (dur) dur.textContent = fmtTime(audio.duration);
            });
            audio.addEventListener('timeupdate', function () {
                var t = audio.currentTime;
                if (cur) cur.textContent = fmtTime(t);
                if (scrub && audio.duration) {
                    scrub.value = String(Math.round((t / audio.duration) * 1000));
                }
                var segEnd = segmentEndByAudio.get(audio);
                if (segEnd != null && t >= segEnd) {
                    audio.pause();
                    segmentEndByAudio.set(audio, null);
                }
                highlightActiveTurn(root, t);
                updatePlayGlyphs(root, audio);
            });
            audio.addEventListener('play', function () {
                if (playpause) playpause.classList.add('ad-is-playing');
                updatePlayGlyphs(root, audio);
            });
            audio.addEventListener('pause', function () {
                if (playpause) playpause.classList.remove('ad-is-playing');
                updatePlayGlyphs(root, audio);
            });
            audio.addEventListener('ended', function () {
                if (playpause) playpause.classList.remove('ad-is-playing');
                updatePlayGlyphs(root, audio);
            });
        });
    }

    function highlightActiveTurn(root, t) {
        var active = null;
        root.querySelectorAll('.ad-turn').forEach(function (turn) {
            var btn = turn.querySelector('.ad-play');
            if (!btn) return;
            var s = parseFloat(btn.getAttribute('data-start'));
            var e = parseFloat(btn.getAttribute('data-end'));
            var on = (t >= s && t < e);
            turn.classList.toggle('ad-active', on);
            if (on) active = turn;
        });
        if (active && !root.dataset.adUserScrolled) scrollTurnIntoView(root, active);
    }

    // Toggle each turn's ▶/⏸ glyph + aria to match playback state.
    function updatePlayGlyphs(root, audio) {
        var ct = audio.currentTime, playing = !audio.paused && !audio.ended;
        root.querySelectorAll('.ad-turn').forEach(function (turn) {
            var btn = turn.querySelector('.ad-play');
            if (!btn) return;
            var s = parseFloat(btn.getAttribute('data-start'));
            var e = parseFloat(btn.getAttribute('data-end'));
            var on = playing && ct >= s - 0.08 && ct < e;
            btn.classList.toggle('ad-is-playing', on);
            var nameEl = turn.querySelector('.ad-speaker-name');
            var nm = nameEl ? (nameEl.getAttribute('data-name') || 'this turn') : 'this turn';
            var timeEl = turn.querySelector('.ad-time');
            var tl = timeEl ? (timeEl.getAttribute('data-time') || '') : '';
            btn.setAttribute('aria-label', (on ? 'Pause turn by ' : 'Play turn by ') + nm + (tl ? ', ' + tl : ''));
        });
    }

    function scrollTurnIntoView(root, turn) {
        var scroll = root.querySelector('.ad-scroll');
        if (!scroll) return;
        var top = turn.offsetTop - scroll.offsetTop;
        var bottom = top + turn.offsetHeight;
        if (top < scroll.scrollTop || bottom > scroll.scrollTop + scroll.clientHeight) {
            scroll.scrollTo({ top: Math.max(0, top - 16), behavior: 'smooth' });
        }
    }

    document.addEventListener('click', function (e) {
        // Per-turn play / pause toggle
        var play = e.target.closest && e.target.closest('.ad-play');
        if (play) {
            e.preventDefault();
            var fieldKey = play.getAttribute('data-field-key');
            var audio = audioFor(fieldKey);
            if (!audio) return;
            var start = parseFloat(play.getAttribute('data-start')) || 0;
            var end = parseFloat(play.getAttribute('data-end'));
            // If this same turn is currently playing, pause it; otherwise (re)start it.
            var within = !audio.paused && audio.currentTime >= start - 0.08 &&
                         audio.currentTime < (isFinite(end) ? end : Infinity);
            if (within) {
                audio.pause();
            } else {
                segmentEndByAudio.set(audio, isFinite(end) ? end : null);
                try { audio.currentTime = start; } catch (err) { /* metadata not ready */ }
                audio.play();
            }
            return;
        }
        // Global play/pause
        var pp = e.target.closest && e.target.closest('.ad-playpause');
        if (pp) {
            e.preventDefault();
            var a = audioFor(pp.getAttribute('data-field-key'));
            if (!a) return;
            segmentEndByAudio.set(a, null);  // play through
            if (a.paused) a.play(); else a.pause();
            return;
        }
        // Stop
        var stop = e.target.closest && e.target.closest('.ad-stop');
        if (stop) {
            e.preventDefault();
            var au = audioFor(stop.getAttribute('data-field-key'));
            if (!au) return;
            segmentEndByAudio.set(au, null);
            au.pause();
            try { au.currentTime = 0; } catch (err2) { /* noop */ }
            return;
        }
    });

    document.addEventListener('input', function (e) {
        var scrub = e.target.closest && e.target.closest('.ad-scrub');
        if (!scrub) return;
        var audio = audioFor(scrub.getAttribute('data-field-key'));
        if (!audio || !audio.duration) return;
        segmentEndByAudio.set(audio, null);
        audio.currentTime = (parseInt(scrub.value, 10) / 1000) * audio.duration;
    });

    document.addEventListener('change', function (e) {
        var rate = e.target.closest && e.target.closest('.ad-rate');
        if (!rate) return;
        var audio = audioFor(rate.getAttribute('data-field-key'));
        if (audio) audio.playbackRate = parseFloat(rate.value) || 1;
    });

    // Pause auto-scroll once the annotator scrolls the pane themselves; resume
    // when they press play again.
    document.addEventListener('wheel', function (e) {
        var scroll = e.target.closest && e.target.closest('.ad-scroll');
        if (!scroll) return;
        var root = scroll.closest('.audio-dialogue');
        if (root) {
            root.dataset.adUserScrolled = 'true';
            clearTimeout(root._adScrollTimer);
            root._adScrollTimer = setTimeout(function () {
                delete root.dataset.adUserScrolled;
            }, 4000);
        }
    }, { passive: true });

    // ------------------------------------------------------------------
    // Lifecycle
    // ------------------------------------------------------------------

    function init() {
        if (!roots().length) return;
        seedAssignments();
        paintAssignments();
        bindTransport();
    }

    window.audioDialogue = {
        refresh: init,
        _assignments: function () { return assignmentsByField; }
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
    document.addEventListener('instanceChanged', init);
})();
