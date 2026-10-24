/*
 * Ego networks (annotation_type: ego_network): name generators, name
 * interpreters, a dyad census and a sociogram, all over one set of alters.
 *
 * The stage list comes normalized from the server (data-ego-config, see
 * potato/server_utils/schemas/ego_network.py). The whole answer lives in the
 * scheme's hidden input as JSON and is restored from it, so the server's
 * pre-filled value (data-server-set) is the only source of truth on load.
 * What is still missing is declared on the form's data-incomplete-reason,
 * which validateRequiredFields reads.
 *
 * Choice answers are buttons with role=radio / role=checkbox rather than
 * native inputs: annotation.js resets every radio, checkbox and text input on
 * the page when an item loads, and would also read native inputs as answers
 * to schemes of their own. Text and number answers are native inputs without
 * the annotation-input class, and the widget re-renders from its own state on
 * potato:instance-ready, after that reset.
 */
(function () {
    'use strict';
    if (window.PotatoEgoNetwork) { return; }

    var STATES = new WeakMap();
    var SVGNS = 'http://www.w3.org/2000/svg';
    var VIEW = 1000;          // sociogram viewBox is VIEW x VIEW
    var NODE_R = 44;

    // ------------------------------------------------------------------
    // DOM helpers (all user text goes through textContent)
    // ------------------------------------------------------------------

    function el(tag, attrs, children) {
        var node = document.createElement(tag);
        setAttrs(node, attrs);
        append(node, children);
        return node;
    }

    function svg(tag, attrs, children) {
        var node = document.createElementNS(SVGNS, tag);
        setAttrs(node, attrs);
        append(node, children);
        return node;
    }

    function setAttrs(node, attrs) {
        Object.keys(attrs || {}).forEach(function (k) {
            var v = attrs[k];
            if (v === undefined || v === null || v === false) { return; }
            if (k === 'text') { node.textContent = v; }
            else if (k === 'className') { node.setAttribute('class', v); }
            else if (k.indexOf('on') === 0) { node.addEventListener(k.slice(2), v); }
            else { node.setAttribute(k, v === true ? '' : v); }
        });
    }

    function append(node, children) {
        (children || []).forEach(function (c) {
            if (c === null || c === undefined || c === false) { return; }
            node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
        });
    }

    function plural(n, one, many) { return n + ' ' + (n === 1 ? one : many); }

    // ------------------------------------------------------------------
    // Answer model
    // ------------------------------------------------------------------

    function emptyAnswer() {
        return {alters: [], attributes: {}, ties: [], positions: {}, census: {}, tie_attributes: {}};
    }

    function readStored(hidden) {
        var a = emptyAnswer();
        if (!hidden || !hidden.value) { return a; }
        var raw;
        try { raw = JSON.parse(hidden.value); } catch (e) { return a; }
        if (!raw || !Array.isArray(raw.alters)) { return a; }
        var ids = {};
        raw.alters.forEach(function (x) {
            if (x && x.id !== undefined && x.id !== null && !ids[x.id]) {
                var alter = {id: String(x.id), name: String(x.name || ''),
                             named_in: Array.isArray(x.named_in) ? x.named_in.map(String) : []};
                if (x.roster_id !== undefined) { alter.roster_id = String(x.roster_id); }
                ids[alter.id] = true;
                a.alters.push(alter);
            }
        });
        (raw.ties || []).forEach(function (t) {
            if (Array.isArray(t) && ids[t[0]] && ids[t[1]] && t[0] !== t[1]) {
                a.ties.push(t.length > 2 && t[2] ? [t[0], t[1], String(t[2])] : [t[0], t[1]]);
            }
        });
        ['attributes', 'positions'].forEach(function (k) {
            Object.keys(raw[k] || {}).forEach(function (id) { if (ids[id]) { a[k][id] = raw[k][id]; } });
        });
        a.census = raw.census && typeof raw.census === 'object' ? raw.census : {};
        a.tie_attributes = raw.tie_attributes && typeof raw.tie_attributes === 'object' ? raw.tie_attributes : {};
        return a;
    }

    function alterById(state, id) {
        for (var i = 0; i < state.answer.alters.length; i++) {
            if (state.answer.alters[i].id === id) { return state.answer.alters[i]; }
        }
        return null;
    }

    function orderOf(state) {
        var o = {};
        state.answer.alters.forEach(function (a, i) { o[a.id] = i; });
        return o;
    }

    function pairKey(state, a, b, relation) {
        var o = orderOf(state);
        if (o[a] > o[b]) { var t = a; a = b; b = t; }
        return a + '|' + b + (relation ? '|' + relation : '');
    }

    function tieIndex(state, a, b, relation) {
        var rel = relation || '';
        for (var i = 0; i < state.answer.ties.length; i++) {
            var t = state.answer.ties[i];
            if ((t[2] || '') !== rel) { continue; }
            if ((t[0] === a && t[1] === b) || (t[0] === b && t[1] === a)) { return i; }
        }
        return -1;
    }

    function hasTie(state, a, b, relation) { return tieIndex(state, a, b, relation) >= 0; }

    function setTie(state, a, b, relation, on) {
        var i = tieIndex(state, a, b, relation);
        if (on && i < 0) {
            var o = orderOf(state);
            var pair = o[a] < o[b] ? [a, b] : [b, a];
            state.answer.ties.push(relation ? pair.concat([relation]) : pair);
        } else if (!on && i >= 0) {
            state.answer.ties.splice(i, 1);
            delete state.answer.tie_attributes[pairKey(state, a, b, relation)];
        }
        // A census of the same relation always agrees with the drawn ties.
        var hasCensus = state.cfg.stages.some(function (s) {
            return s.type === 'dyad_census' && (s.relation || '') === (relation || '');
        });
        if (hasCensus) { state.answer.census[pairKey(state, a, b, relation)] = !!on; }
    }

    function namedIn(stage, alter) { return alter.named_in.indexOf(stage.id) >= 0; }

    function namedHere(state, stage) {
        return state.answer.alters.filter(function (a) { return namedIn(stage, a); });
    }

    function nextId(state) {
        var max = 0;
        state.answer.alters.forEach(function (a) {
            var m = /^a(\d+)$/.exec(a.id);
            if (m) { max = Math.max(max, parseInt(m[1], 10)); }
        });
        return 'a' + (max + 1);
    }

    function applySets(state, stage, alter, on) {
        var sets = stage.sets || {};
        Object.keys(sets).forEach(function (k) {
            var attrs = state.answer.attributes[alter.id] || (state.answer.attributes[alter.id] = {});
            if (on) { attrs[k] = sets[k]; }
            else if (attrs[k] === sets[k]) { delete attrs[k]; }
        });
    }

    function deleteAlter(state, id) {
        var a = state.answer;
        a.alters = a.alters.filter(function (x) { return x.id !== id; });
        delete a.attributes[id];
        delete a.positions[id];
        a.ties = a.ties.filter(function (t) { return t[0] !== id && t[1] !== id; });
        [a.census, a.tie_attributes].forEach(function (map) {
            Object.keys(map).forEach(function (k) {
                var parts = k.split('|');
                if (parts[0] === id || parts[1] === id) { delete map[k]; }
            });
        });
        Object.keys(state.selected).forEach(function (s) {
            if (state.selected[s] === id) { delete state.selected[s]; }
        });
    }

    function answered(v) {
        if (v === undefined || v === null) { return false; }
        if (typeof v === 'string') { return v.trim() !== ''; }
        if (Array.isArray(v)) { return v.length > 0; }
        return true;
    }

    function pairs(state) {
        var out = [], alters = state.answer.alters;
        for (var i = 0; i < alters.length; i++) {
            for (var j = i + 1; j < alters.length; j++) { out.push([alters[i], alters[j]]); }
        }
        return out;
    }

    function censusDone(state, stage) {
        var rel = stage.relation;
        return pairs(state).filter(function (p) {
            return Object.prototype.hasOwnProperty.call(state.answer.census, pairKey(state, p[0].id, p[1].id, rel));
        }).length;
    }

    // The same rules as incomplete_reasons() in ego_network.py.
    function stageReasons(state, stage) {
        var alters = state.answer.alters, out = [];
        if (stage.type === 'name_generator') {
            var here = namedHere(state, stage).length, need = stage.min_alters || 0;
            if (here < need) {
                out.push(stage.title + ': name at least ' + plural(need, 'person', 'people') +
                         ' (' + here + ' so far)');
            }
        } else if (stage.type === 'name_interpreter') {
            stage.questions.forEach(function (q) {
                if (!q.required) { return; }
                var missing = alters.filter(function (a) {
                    return !answered((state.answer.attributes[a.id] || {})[q.name]);
                }).length;
                if (missing) {
                    out.push(stage.title + ": '" + q.description.replace(/\{name\}/g, 'this person') + "' unanswered for " +
                             plural(missing, 'person', 'people'));
                }
            });
        } else if (stage.type === 'dyad_census') {
            var total = pairs(state).length, done = censusDone(state, stage);
            if (done < total) { out.push(stage.title + ': ' + done + ' of ' + total + ' pairs answered'); }
        }
        return out;
    }

    function declare(state) {
        var reasons = [];
        state.cfg.stages.forEach(function (s) { reasons = reasons.concat(stageReasons(state, s)); });
        if (reasons.length) { state.form.setAttribute('data-incomplete-reason', reasons.join('; ')); }
        else { state.form.removeAttribute('data-incomplete-reason'); }
    }

    function save(state) {
        var h = state.hidden;
        h.value = state.answer.alters.length ? JSON.stringify(state.answer) : '';
        h.setAttribute('data-modified', 'true');
        h.dispatchEvent(new Event('change', {bubbles: true}));
        declare(state);
    }

    function announce(state, text) {
        if (state.status) {
            state.status.textContent = '';
            // A new text node so a repeated message is read again.
            window.setTimeout(function () { state.status.textContent = text; }, 30);
        }
    }

    // ------------------------------------------------------------------
    // Layout
    // ------------------------------------------------------------------

    function blockedAt(state) {
        // The first name generator still short of its minimum; later steps wait.
        for (var i = 0; i < state.cfg.stages.length; i++) {
            var s = state.cfg.stages[i];
            if (s.type === 'name_generator' && namedHere(state, s).length < (s.min_alters || 0)) { return i; }
        }
        return state.cfg.stages.length;
    }

    function stageDone(state, stage) {
        if (!state.answer.alters.length) { return false; }
        if (stage.type === 'name_generator') {
            return namedHere(state, stage).length >= Math.max(1, stage.min_alters || 0);
        }
        if (stage.type === 'sociogram') { return false; }
        return stageReasons(state, stage).length === 0;
    }

    function render(state) {
        var active = document.activeElement;
        var focusKey = active && state.root.contains(active) ? active.getAttribute('data-fk') : null;
        var body = state.body;
        body.innerHTML = '';
        var stages = state.cfg.stages;
        if (state.cfg.layout === 'stacked') {
            stages.forEach(function (s, i) {
                body.appendChild(stageSection(state, s, i, true));
            });
        } else {
            if (state.step >= stages.length) { state.step = stages.length - 1; }
            var blocked = blockedAt(state);
            var nav = el('ol', {className: 'en-steps', 'aria-label': 'Steps'});
            stages.forEach(function (s, i) {
                var done = stageDone(state, s);
                nav.appendChild(el('li', {}, [el('button', {
                    type: 'button', className: 'en-step' + (done ? ' en-step-done' : ''),
                    'data-fk': 'step-' + i, 'aria-current': i === state.step ? 'step' : null,
                    disabled: i > blocked ? true : null,
                    'aria-label': 'Step ' + (i + 1) + ' of ' + stages.length + ': ' + s.title +
                                  (done ? ' (done)' : ''),
                    onclick: function () { goTo(state, i); }
                }, [el('span', {className: 'en-step-n', 'aria-hidden': 'true', text: done ? '✓' : String(i + 1)}),
                    el('span', {className: 'en-step-t', text: s.title})])]));
            });
            body.appendChild(nav);
            body.appendChild(stageSection(state, stages[state.step], state.step, false));
            var foot = el('div', {className: 'en-foot'});
            foot.appendChild(el('button', {
                type: 'button', className: 'en-btn en-back', 'data-fk': 'back',
                disabled: state.step === 0 ? true : null,
                onclick: function () { goTo(state, state.step - 1); }
            }, ['← Back']));
            foot.appendChild(el('span', {className: 'en-step-count',
                text: 'Step ' + (state.step + 1) + ' of ' + stages.length}));
            if (state.step < stages.length - 1) {
                foot.appendChild(el('button', {
                    type: 'button', className: 'en-btn en-btn-primary en-next', 'data-fk': 'next',
                    onclick: function () { goTo(state, state.step + 1); }
                }, ['Next: ' + stages[state.step + 1].title + ' →']));
            } else {
                foot.appendChild(el('span', {className: 'en-last', text: 'Last step'}));
            }
            body.appendChild(foot);
        }
        if (focusKey) {
            var target = body.querySelector('[data-fk="' + focusKey.replace(/"/g, '\\"') + '"]');
            if (target && !target.disabled) { target.focus({preventScroll: true}); }
        }
    }

    function goTo(state, i) {
        var stages = state.cfg.stages;
        if (i < 0 || i >= stages.length) { return; }
        var blocked = blockedAt(state);
        if (i > blocked) {
            var s = stages[blocked];
            state.messages[s.id] = 'Name at least ' + plural(s.min_alters, 'person', 'people') +
                                   ' before going on.';
            state.step = blocked;
            render(state);
            return;
        }
        state.step = i;
        render(state);
        var heading = state.body.querySelector('.en-stage-title');
        if (heading) { heading.focus({preventScroll: true}); }
        var top = state.form.getBoundingClientRect().top;
        if (top < 0) { state.form.scrollIntoView({block: 'start'}); }
    }

    function stageSection(state, stage, index, stacked) {
        var section = el('section', {className: 'en-stage en-stage-' + stage.type,
                                     'data-stage': stage.id, 'aria-labelledby': state.uid + '-st-' + index});
        section.appendChild(el('h3', {
            className: 'en-stage-title', id: state.uid + '-st-' + index, tabindex: '-1',
            text: (stacked ? (index + 1) + '. ' : '') + stage.title}));
        if (stage.instructions) {
            section.appendChild(el('p', {className: 'en-instructions', text: stage.instructions}));
        }
        if (stage.type === 'name_generator') { renderGenerator(state, stage, section); }
        else if (stage.type === 'name_interpreter') { renderInterpreter(state, stage, section); }
        else if (stage.type === 'dyad_census') { renderCensus(state, stage, section); }
        else if (stage.type === 'sociogram') { renderSociogram(state, stage, section); }
        var msg = state.messages[stage.id];
        if (msg) {
            section.appendChild(el('p', {className: 'en-msg', role: 'alert', text: msg}));
            delete state.messages[stage.id];
        }
        return section;
    }

    // ------------------------------------------------------------------
    // Name generator
    // ------------------------------------------------------------------

    function rosterFor(state, stage) {
        if (stage.roster) { return stage.roster; }
        if (!stage.roster_field) { return null; }
        var script = document.getElementById('instance_data'), data = null;
        if (script) { try { data = JSON.parse(script.textContent); } catch (e) { data = null; } }
        var list = data ? data[stage.roster_field] : null;
        if (!Array.isArray(list)) { return []; }
        return list.map(function (x) {
            if (x && typeof x === 'object') { return {id: x.id !== undefined ? String(x.id) : undefined, name: String(x.name || '')}; }
            return {name: String(x)};
        }).filter(function (x) { return x.name.trim(); });
    }

    function findAlterByName(state, name) {
        var key = name.toLowerCase();
        for (var i = 0; i < state.answer.alters.length; i++) {
            if (state.answer.alters[i].name.toLowerCase() === key) { return state.answer.alters[i]; }
        }
        return null;
    }

    function atMax(state, stage) {
        return stage.max_alters && namedHere(state, stage).length >= stage.max_alters;
    }

    function addToStage(state, stage, alter) {
        if (namedIn(stage, alter)) { return; }
        alter.named_in.push(stage.id);
        applySets(state, stage, alter, true);
    }

    function addNew(state, stage, name, rosterId) {
        name = String(name || '').replace(/\s+/g, ' ').trim().slice(0, 60);
        if (!name) {
            state.messages[stage.id] = 'Type a name first.';
            return false;
        }
        if (atMax(state, stage)) {
            state.messages[stage.id] = 'This list is full (' + stage.max_alters + ' people).';
            return false;
        }
        var existing = findAlterByName(state, name);
        if (existing) {
            state.messages[stage.id] = namedIn(stage, existing)
                ? existing.name + ' is already on this list.'
                : 'You already named ' + existing.name + '. If this is the same person, add them with the button under "Named earlier". If it is someone else, add an initial (for example "' + name + ' K.").';
            return false;
        }
        var alter = {id: nextId(state), name: name, named_in: []};
        if (rosterId !== undefined) { alter.roster_id = rosterId; }
        state.answer.alters.push(alter);
        addToStage(state, stage, alter);
        announce(state, name + ' added.');
        return true;
    }

    function removeFromStage(state, stage, alter) {
        alter.named_in = alter.named_in.filter(function (s) { return s !== stage.id; });
        applySets(state, stage, alter, false);
        if (!alter.named_in.length) { deleteAlter(state, alter.id); }
        announce(state, alter.name + ' removed.');
    }

    function renderGenerator(state, stage, section) {
        section.appendChild(el('p', {className: 'en-prompt', text: stage.prompt}));
        var here = namedHere(state, stage);
        var limits = [];
        if (stage.min_alters) { limits.push('at least ' + stage.min_alters); }
        if (stage.max_alters) { limits.push('at most ' + stage.max_alters); }
        section.appendChild(el('p', {className: 'en-count', text: plural(here.length, 'person', 'people') +
            ' named' + (limits.length ? ' (' + limits.join(', ') + ')' : '')}));

        var roster = rosterFor(state, stage);
        var full = atMax(state, stage);
        if (roster && roster.length) {
            var search = el('input', {type: 'search', className: 'en-input en-roster-search',
                'data-fk': 'search-' + stage.id, placeholder: 'Search the list',
                'aria-label': 'Search the list of names', autocomplete: 'off'});
            var list = el('ul', {className: 'en-roster', 'aria-label': 'Names to choose from'});
            roster.forEach(function (entry, i) {
                var alter = entry.id !== undefined
                    ? state.answer.alters.filter(function (a) { return a.roster_id === entry.id; })[0]
                    : findAlterByName(state, entry.name);
                var on = !!(alter && namedIn(stage, alter));
                list.appendChild(el('li', {'data-name': entry.name.toLowerCase()}, [el('button', {
                    type: 'button', className: 'en-roster-item', 'aria-pressed': on ? 'true' : 'false',
                    'data-fk': 'roster-' + stage.id + '-' + i,
                    disabled: !on && full ? true : null,
                    onclick: function () {
                        if (on) { removeFromStage(state, stage, alter); }
                        else if (alter) { addToStage(state, stage, alter); announce(state, alter.name + ' added.'); }
                        else { addNew(state, stage, entry.name, entry.id); }
                        save(state); render(state);
                    }
                }, [entry.name])]));
            });
            search.addEventListener('input', function () {
                var q = search.value.trim().toLowerCase();
                list.querySelectorAll('li').forEach(function (li) {
                    li.hidden = q && li.getAttribute('data-name').indexOf(q) < 0;
                });
            });
            section.appendChild(search);
            section.appendChild(list);
        } else {
            if (roster && !roster.length) {
                section.appendChild(el('p', {className: 'en-note',
                    text: 'There is no list of names for this item, so type the names instead.'}));
            }
            var inputId = state.uid + '-name-' + stage.id;
            var input = el('input', {type: 'text', className: 'en-input en-name-input', id: inputId,
                'data-fk': 'name-' + stage.id, maxlength: '60', autocomplete: 'off',
                placeholder: stage.placeholder || 'First name or nickname', disabled: full ? true : null});
            var add = function () {
                if (addNew(state, stage, input.value)) { input.value = ''; save(state); }
                render(state);
                var again = state.body.querySelector('[data-fk="name-' + stage.id + '"]');
                if (again && !again.disabled) { again.focus(); }
            };
            input.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); add(); }
            });
            section.appendChild(el('div', {className: 'en-add'}, [
                el('label', {className: 'en-label', 'for': inputId, text: 'Name'}),
                input,
                el('button', {type: 'button', className: 'en-btn en-btn-primary en-add-btn',
                              'data-fk': 'add-' + stage.id, disabled: full ? true : null, onclick: add}, ['Add'])
            ]));
            if (full) {
                section.appendChild(el('p', {className: 'en-note', text: 'This list is full. Remove someone to add another person.'}));
            }
        }

        if (here.length) {
            var chips = el('ul', {className: 'en-chips', 'aria-label': 'People named here'});
            here.forEach(function (a) {
                chips.appendChild(el('li', {className: 'en-chip', 'data-alter': a.id}, [
                    el('span', {className: 'en-chip-name', text: a.name}),
                    el('button', {type: 'button', className: 'en-chip-remove', 'data-fk': 'rm-' + stage.id + '-' + a.id,
                        'aria-label': 'Remove ' + a.name, title: 'Remove',
                        onclick: function () { removeFromStage(state, stage, a); save(state); render(state); }}, ['×'])
                ]));
            });
            section.appendChild(chips);
        }

        var earlier = state.answer.alters.filter(function (a) { return !namedIn(stage, a); });
        if (earlier.length) {
            section.appendChild(el('p', {className: 'en-sub', text: 'Named earlier (add anyone who also belongs here):'}));
            var others = el('ul', {className: 'en-chips en-chips-earlier'});
            earlier.forEach(function (a) {
                others.appendChild(el('li', {}, [el('button', {
                    type: 'button', className: 'en-chip-add', 'data-fk': 'also-' + stage.id + '-' + a.id,
                    disabled: full ? true : null, 'aria-label': 'Add ' + a.name + ' to this list',
                    onclick: function () { addToStage(state, stage, a); announce(state, a.name + ' added.'); save(state); render(state); }
                }, ['+ ' + a.name])]));
            });
            section.appendChild(others);
        }
    }

    // ------------------------------------------------------------------
    // Name interpreter
    // ------------------------------------------------------------------

    function fill(text, alter) { return String(text).replace(/\{name\}/g, alter.name); }

    function renderInterpreter(state, stage, section) {
        section.appendChild(el('p', {className: 'en-prompt', text: stage.prompt}));
        if (!state.answer.alters.length) {
            section.appendChild(el('p', {className: 'en-empty', text: 'Name some people in an earlier step first.'}));
            return;
        }
        var cards = el('div', {className: 'en-cards'});
        state.answer.alters.forEach(function (a) {
            var attrs = state.answer.attributes[a.id] || {};
            var done = stage.questions.filter(function (q) { return answered(attrs[q.name]); }).length;
            var hid = state.uid + '-card-' + stage.id + '-' + a.id;
            var card = el('section', {className: 'en-card' + (done === stage.questions.length ? ' en-card-done' : ''),
                                      'data-alter': a.id, 'aria-labelledby': hid});
            card.appendChild(el('h4', {className: 'en-card-title', id: hid}, [
                el('span', {text: a.name}),
                el('span', {className: 'en-card-progress', text: done + ' of ' + stage.questions.length + ' answered'})]));
            stage.questions.forEach(function (q) { card.appendChild(question(state, stage, a, q)); });
            cards.appendChild(card);
        });
        section.appendChild(cards);
    }

    function setAttr(state, alter, name, value) {
        var attrs = state.answer.attributes[alter.id] || (state.answer.attributes[alter.id] = {});
        if (answered(value)) { attrs[name] = value; } else { delete attrs[name]; }
        if (!Object.keys(attrs).length) { delete state.answer.attributes[alter.id]; }
    }

    function question(state, stage, alter, q) {
        var attrs = state.answer.attributes[alter.id] || {};
        var value = attrs[q.name];
        var lid = state.uid + '-q-' + alter.id + '-' + q.name;
        var wrap = el('div', {className: 'en-q', 'data-question': q.name});
        wrap.appendChild(el('p', {className: 'en-q-label', id: lid}, [fill(q.description, alter),
            q.required ? el('span', {className: 'en-req', 'aria-hidden': 'true', text: ' *'}) : null]));
        if (q.type === 'radio' || q.type === 'multiselect') {
            var multi = q.type === 'multiselect';
            var group = el('div', {className: 'en-options', role: multi ? 'group' : 'radiogroup',
                                   'aria-labelledby': lid, 'aria-required': q.required ? 'true' : null});
            q.labels.forEach(function (l) {
                var on = multi ? (Array.isArray(value) && value.indexOf(l.name) >= 0) : value === l.name;
                group.appendChild(el('button', {
                    type: 'button', className: 'en-option', role: multi ? 'checkbox' : 'radio',
                    'aria-checked': on ? 'true' : 'false', 'data-value': l.name,
                    'data-fk': 'opt-' + alter.id + '-' + q.name + '-' + l.name,
                    onclick: function () {
                        if (multi) {
                            var cur = Array.isArray(value) ? value.slice() : [];
                            var k = cur.indexOf(l.name);
                            if (k >= 0) { cur.splice(k, 1); } else { cur.push(l.name); }
                            setAttr(state, alter, q.name, cur);
                        } else {
                            setAttr(state, alter, q.name, l.name);
                        }
                        save(state); render(state);
                    }
                }, [l.text]));
            });
            wrap.appendChild(group);
        } else {
            var input = el('input', {
                type: q.type === 'number' ? 'number' : 'text', className: 'en-input en-q-input',
                'aria-labelledby': lid, 'data-fk': 'in-' + alter.id + '-' + q.name,
                min: q.min !== undefined ? String(q.min) : null, max: q.max !== undefined ? String(q.max) : null,
                step: q.step !== undefined ? String(q.step) : (q.type === 'number' ? 'any' : null),
                placeholder: q.placeholder || null, autocomplete: 'off',
                'aria-required': q.required ? 'true' : null});
            input.value = value === undefined || value === null ? '' : String(value);
            var timer = null;
            input.addEventListener('input', function () {
                var v = input.value;
                if (q.type === 'number') { v = v === '' || isNaN(Number(v)) ? null : Number(v); }
                setAttr(state, alter, q.name, v);
                declare(state);
                // Typing does not re-render (that would move the caret); save
                // after a pause, and update this card's progress in place.
                window.clearTimeout(timer);
                timer = window.setTimeout(function () { save(state); }, 400);
                var card = wrap.closest('.en-card');
                var attrsNow = state.answer.attributes[alter.id] || {};
                var n = stage.questions.filter(function (qq) { return answered(attrsNow[qq.name]); }).length;
                card.querySelector('.en-card-progress').textContent = n + ' of ' + stage.questions.length + ' answered';
                card.classList.toggle('en-card-done', n === stage.questions.length);
            });
            input.addEventListener('change', function () { window.clearTimeout(timer); save(state); });
            input.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); }
            });
            wrap.appendChild(input);
        }
        return wrap;
    }

    // ------------------------------------------------------------------
    // Dyad census
    // ------------------------------------------------------------------

    function censusValue(state, stage, a, b) {
        var key = pairKey(state, a.id, b.id, stage.relation);
        if (!Object.prototype.hasOwnProperty.call(state.answer.census, key)) { return undefined; }
        if (!state.answer.census[key]) { return 'no'; }
        if (stage.strength_labels) {
            var ta = state.answer.tie_attributes[key] || {};
            return ta[stage.strength_variable] !== undefined ? 'yes:' + ta[stage.strength_variable] : 'yes';
        }
        return 'yes';
    }

    function answerPair(state, stage, a, b, yes, strength) {
        var key = pairKey(state, a.id, b.id, stage.relation);
        setTie(state, a.id, b.id, stage.relation, yes);
        state.answer.census[key] = !!yes;
        if (yes && stage.strength_labels) {
            var ta = state.answer.tie_attributes[key] || (state.answer.tie_attributes[key] = {});
            ta[stage.strength_variable] = strength;
        }
    }

    function promptParts(text, a, b) {
        var out = [];
        String(text).split(/(\{a\}|\{b\})/).forEach(function (part) {
            if (part === '{a}') { out.push(el('strong', {text: a.name})); }
            else if (part === '{b}') { out.push(el('strong', {text: b.name})); }
            else if (part) { out.push(part); }
        });
        return out;
    }

    function renderCensus(state, stage, section) {
        var all = pairs(state);
        if (all.length === 0) {
            section.appendChild(el('p', {className: 'en-empty', text: 'This step needs at least two people.'}));
            return;
        }
        var done = censusDone(state, stage);
        var idx = state.pairIndex[stage.id];
        if (idx === undefined || idx >= all.length) {
            idx = 0;
            for (var i = 0; i < all.length; i++) {
                if (censusValue(state, stage, all[i][0], all[i][1]) === undefined) { idx = i; break; }
            }
            state.pairIndex[stage.id] = idx;
        }
        var pair = all[idx], a = pair[0], b = pair[1];
        var current = censusValue(state, stage, a, b);
        section.appendChild(el('div', {className: 'en-census-head'}, [
            el('span', {className: 'en-pair-n', text: 'Pair ' + (idx + 1) + ' of ' + all.length}),
            el('span', {className: 'en-count', text: done + ' answered'})]));
        var bar = el('div', {className: 'en-progress', role: 'progressbar', 'aria-label': 'Pairs answered',
            'aria-valuemin': '0', 'aria-valuemax': String(all.length), 'aria-valuenow': String(done)},
            [el('span', {style: 'width:' + Math.round(100 * done / all.length) + '%'})]);
        section.appendChild(bar);
        var qid = state.uid + '-pair-' + stage.id;
        section.appendChild(el('p', {className: 'en-pair-q', id: qid}, promptParts(stage.prompt, a, b)));

        var opts = el('div', {className: 'en-options en-pair-options', role: 'radiogroup', 'aria-labelledby': qid});
        var choices = stage.strength_labels
            ? stage.strength_labels.map(function (l) { return {key: 'yes:' + l.name, text: l.text, yes: true, strength: l.name}; })
            : [{key: 'yes', text: stage.yes_label, yes: true}];
        choices.push({key: 'no', text: stage.no_label, yes: false});
        choices.forEach(function (c) {
            opts.appendChild(el('button', {
                type: 'button', className: 'en-option' + (c.yes ? '' : ' en-option-no'), role: 'radio',
                'aria-checked': current === c.key ? 'true' : 'false', 'data-answer': c.key,
                'data-fk': 'pair-' + stage.id + '-' + c.key,
                onclick: function () {
                    answerPair(state, stage, a, b, c.yes, c.strength);
                    announce(state, a.name + ' and ' + b.name + ': ' + c.text + '.');
                    // On to the next pair still unanswered, if there is one.
                    for (var k = 1; k <= all.length; k++) {
                        var j = (idx + k) % all.length;
                        if (censusValue(state, stage, all[j][0], all[j][1]) === undefined) { state.pairIndex[stage.id] = j; break; }
                    }
                    save(state); render(state);
                }
            }, [c.text]));
        });
        section.appendChild(opts);

        section.appendChild(el('div', {className: 'en-pair-nav'}, [
            el('button', {type: 'button', className: 'en-btn en-pair-prev', 'data-fk': 'pprev-' + stage.id,
                disabled: idx === 0 ? true : null,
                onclick: function () { state.pairIndex[stage.id] = idx - 1; render(state); }}, ['← Previous pair']),
            el('button', {type: 'button', className: 'en-btn en-pair-next', 'data-fk': 'pnext-' + stage.id,
                disabled: idx === all.length - 1 ? true : null,
                onclick: function () { state.pairIndex[stage.id] = idx + 1; render(state); }}, ['Next pair →'])]));

        var details = el('details', {className: 'en-pairs', open: state.openPairs[stage.id] ? true : null});
        details.addEventListener('toggle', function () { state.openPairs[stage.id] = details.open; });
        details.appendChild(el('summary', {text: 'All pairs (' + done + ' of ' + all.length + ' answered)'}));
        var list = el('ul', {className: 'en-pair-list'});
        all.forEach(function (p, k) {
            var v = censusValue(state, stage, p[0], p[1]);
            var label = v === undefined ? 'not answered' : (v === 'no' ? stage.no_label
                : (v.indexOf('yes:') === 0 ? (stage.strength_labels.filter(function (l) { return 'yes:' + l.name === v; })[0] || {text: v}).text : stage.yes_label));
            list.appendChild(el('li', {}, [el('button', {
                type: 'button', className: 'en-pair-jump' + (v === undefined ? ' en-pair-open' : (v === 'no' ? ' en-pair-no' : ' en-pair-yes')),
                'aria-current': k === idx ? 'true' : null, 'data-fk': 'pj-' + stage.id + '-' + k,
                onclick: function () { state.pairIndex[stage.id] = k; render(state); }
            }, [p[0].name + ' – ' + p[1].name + ': ', el('span', {className: 'en-pair-state', text: label})])]));
        });
        details.appendChild(list);
        section.appendChild(details);
    }

    // ------------------------------------------------------------------
    // Sociogram
    // ------------------------------------------------------------------

    function defaultPosition(i, n) {
        if (n === 1) { return [0.5, 0.5]; }
        var angle = -Math.PI / 2 + (2 * Math.PI * i) / n;
        return [0.5 + 0.34 * Math.cos(angle), 0.5 + 0.34 * Math.sin(angle)];
    }

    function positionOf(state, alter) {
        var p = state.answer.positions[alter.id];
        if (p && p.length === 2 && isFinite(p[0]) && isFinite(p[1])) { return p; }
        var alters = state.answer.alters;
        return defaultPosition(alters.indexOf(alter), alters.length);
    }

    function fixPositions(state) {
        state.answer.alters.forEach(function (a) {
            var p = positionOf(state, a);
            state.answer.positions[a.id] = [Math.round(p[0] * 10000) / 10000, Math.round(p[1] * 10000) / 10000];
        });
    }

    function clamp(v) { return Math.min(0.95, Math.max(0.05, v)); }

    function shortName(name) { return name.length > 11 ? name.slice(0, 10) + '…' : name; }

    function degree(state, stage, id) {
        var rel = stage.relation || '';
        return state.answer.ties.filter(function (t) {
            return (t[2] || '') === rel && (t[0] === id || t[1] === id);
        }).length;
    }

    function renderSociogram(state, stage, section) {
        section.appendChild(el('p', {className: 'en-prompt', text: stage.prompt}));
        var alters = state.answer.alters;
        if (!alters.length) {
            section.appendChild(el('p', {className: 'en-empty', text: 'Name some people in an earlier step first.'}));
            return;
        }
        var selected = state.selected[stage.id];
        if (selected && !alterById(state, selected)) { selected = null; delete state.selected[stage.id]; }
        var canvas = svg('svg', {className: 'en-sociogram', viewBox: '0 0 ' + VIEW + ' ' + VIEW,
            role: 'group', 'aria-label': 'Network canvas: ' + plural(alters.length, 'person', 'people')});
        canvas.appendChild(svg('rect', {className: 'en-canvas-bg', x: '0', y: '0', width: String(VIEW), height: String(VIEW), rx: '24'}));
        for (var r = stage.rings; r >= 1; r--) {
            canvas.appendChild(svg('circle', {className: 'en-ring', cx: String(VIEW / 2), cy: String(VIEW / 2),
                r: String((VIEW / 2 - 12) * r / stage.rings)}));
        }
        if (stage.rings) {
            canvas.appendChild(svg('circle', {className: 'en-ego', cx: String(VIEW / 2), cy: String(VIEW / 2), r: '10'}));
        }
        var tieLayer = svg('g', {className: 'en-ties'});
        canvas.appendChild(tieLayer);
        var nodeLayer = svg('g', {className: 'en-nodes'});
        canvas.appendChild(nodeLayer);

        function drawTies() {
            tieLayer.innerHTML = '';
            var rel = stage.relation || '';
            state.answer.ties.forEach(function (t) {
                if ((t[2] || '') !== rel) { return; }
                var A = alterById(state, t[0]), B = alterById(state, t[1]);
                if (!A || !B) { return; }
                var pa = positionOf(state, A), pb = positionOf(state, B);
                tieLayer.appendChild(svg('line', {className: 'en-tie', 'data-a': t[0], 'data-b': t[1],
                    x1: String(pa[0] * VIEW), y1: String(pa[1] * VIEW), x2: String(pb[0] * VIEW), y2: String(pb[1] * VIEW)}));
            });
        }
        drawTies();

        function tap(id) {
            var cur = state.selected[stage.id];
            var who = alterById(state, id);
            if (!stage.allow_ties) {
                if (cur === id) { delete state.selected[stage.id]; } else { state.selected[stage.id] = id; }
            } else if (!cur) {
                state.selected[stage.id] = id;
                announce(state, who.name + ' selected. Choose another person to add or remove a tie.');
            } else if (cur === id) {
                delete state.selected[stage.id];
                announce(state, who.name + ' deselected.');
            } else {
                var other = alterById(state, cur);
                var on = !hasTie(state, cur, id, stage.relation);
                setTie(state, cur, id, stage.relation, on);
                fixPositions(state);
                delete state.selected[stage.id];
                announce(state, (on ? 'Tie added between ' : 'Tie removed between ') + other.name + ' and ' + who.name + '.');
                save(state);
            }
            render(state);
        }

        alters.forEach(function (a) {
            var p = positionOf(state, a);
            var deg = degree(state, stage, a.id);
            var g = svg('g', {className: 'en-node' + (selected === a.id ? ' en-node-selected' : ''),
                'data-alter': a.id, 'data-fk': 'node-' + stage.id + '-' + a.id, tabindex: '0', role: 'button',
                'aria-pressed': selected === a.id ? 'true' : 'false',
                'aria-label': a.name + (stage.allow_ties ? ', ' + plural(deg, 'tie', 'ties') : '') +
                              '. Arrow keys move this person.',
                transform: 'translate(' + (p[0] * VIEW) + ' ' + (p[1] * VIEW) + ')'}, [
                svg('circle', {className: 'en-node-circle', r: String(NODE_R)}),
                svg('text', {className: 'en-node-label', 'text-anchor': 'middle', y: String(NODE_R + 34), text: shortName(a.name)}),
                svg('title', {text: a.name})]);
            var drag = null;
            g.addEventListener('pointerdown', function (e) {
                if (e.button !== undefined && e.button !== 0) { return; }
                e.preventDefault();
                g.focus({preventScroll: true});
                try { g.setPointerCapture(e.pointerId); } catch (err) { /* old browsers */ }
                drag = {x: e.clientX, y: e.clientY, moved: false};
            });
            g.addEventListener('pointermove', function (e) {
                if (!drag) { return; }
                if (!drag.moved && Math.abs(e.clientX - drag.x) + Math.abs(e.clientY - drag.y) < 6) { return; }
                drag.moved = true;
                var ctm = canvas.getScreenCTM();
                if (!ctm) { return; }
                var pt = canvas.createSVGPoint();
                pt.x = e.clientX; pt.y = e.clientY;
                var loc = pt.matrixTransform(ctm.inverse());
                var np = [clamp(loc.x / VIEW), clamp(loc.y / VIEW)];
                state.answer.positions[a.id] = np;
                g.setAttribute('transform', 'translate(' + (np[0] * VIEW) + ' ' + (np[1] * VIEW) + ')');
                drawTies();
            });
            var end = function (e) {
                if (!drag) { return; }
                var moved = drag.moved;
                drag = null;
                try { g.releasePointerCapture(e.pointerId); } catch (err) { /* already released */ }
                if (moved) { fixPositions(state); save(state); render(state); }
                else if (e.type === 'pointerup') { tap(a.id); }
            };
            g.addEventListener('pointerup', end);
            g.addEventListener('pointercancel', end);
            g.addEventListener('keydown', function (e) {
                var step = e.shiftKey ? 0.08 : 0.02;
                var moves = {ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step]};
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault(); e.stopPropagation(); tap(a.id);
                } else if (moves[e.key]) {
                    e.preventDefault(); e.stopPropagation();
                    var cur = positionOf(state, a);
                    state.answer.positions[a.id] = [clamp(cur[0] + moves[e.key][0]), clamp(cur[1] + moves[e.key][1])];
                    fixPositions(state); save(state); render(state);
                } else if (e.key === 'Escape' && state.selected[stage.id]) {
                    e.preventDefault(); e.stopPropagation();
                    delete state.selected[stage.id]; render(state);
                }
            });
            nodeLayer.appendChild(g);
        });
        section.appendChild(el('div', {className: 'en-canvas-wrap'}, [canvas]));

        if (!stage.allow_ties) {
            section.appendChild(el('p', {className: 'en-note', text: 'Drag people to place them, or focus a person and use the arrow keys.'}));
            return;
        }
        if (selected) {
            var who = alterById(state, selected);
            var hid = state.uid + '-ties-' + stage.id;
            var panel = el('div', {className: 'en-tie-panel', role: 'group', 'aria-labelledby': hid});
            panel.appendChild(el('p', {className: 'en-sub', id: hid, text: 'Ties for ' + who.name + ' (choose people to add or remove a tie):'}));
            var list = el('div', {className: 'en-options'});
            alters.forEach(function (o) {
                if (o.id === selected) { return; }
                var on = hasTie(state, selected, o.id, stage.relation);
                list.appendChild(el('button', {
                    type: 'button', className: 'en-option en-tie-toggle', role: 'checkbox',
                    'aria-checked': on ? 'true' : 'false', 'data-alter': o.id,
                    'data-fk': 'tt-' + stage.id + '-' + o.id,
                    onclick: function () {
                        setTie(state, selected, o.id, stage.relation, !on);
                        fixPositions(state);
                        announce(state, (on ? 'Tie removed between ' : 'Tie added between ') + who.name + ' and ' + o.name + '.');
                        save(state); render(state);
                    }
                }, [o.name]));
            });
            panel.appendChild(list);
            var finish = function () {
                delete state.selected[stage.id];
                render(state);
                // Back to the person whose ties were being edited.
                var node = state.body.querySelector('[data-fk="node-' + stage.id + '-' + who.id + '"]');
                if (node) { node.focus({preventScroll: true}); }
            };
            panel.addEventListener('keydown', function (e) {
                if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); finish(); }
            });
            panel.appendChild(el('button', {type: 'button', className: 'en-btn en-tie-done', 'data-fk': 'tdone-' + stage.id,
                onclick: finish}, ['Done with ' + who.name]));
            section.appendChild(panel);
        } else {
            section.appendChild(el('p', {className: 'en-note',
                text: 'Keyboard: Tab to a person and press Enter to list their ties; arrow keys move them.'}));
        }
    }

    // ------------------------------------------------------------------
    // Setup
    // ------------------------------------------------------------------

    var counter = 0;

    function instanceId() {
        var input = document.getElementById('instance_id');
        return input ? input.value : '';
    }

    function setup(form) {
        var prior = STATES.get(form);
        if (prior && prior.instance === instanceId()) {
            // annotation.js cleared the page's inputs when the item loaded;
            // draw again from the widget's own state.
            render(prior);
            declare(prior);
            return;
        }
        var cfg;
        try { cfg = JSON.parse(form.getAttribute('data-ego-config') || '{}'); } catch (e) { cfg = null; }
        var root = form.querySelector('.en-root');
        var hidden = form.querySelector('.ego-network-input');
        if (!cfg || !Array.isArray(cfg.stages) || !root || !hidden) { return; }
        root.innerHTML = '';
        var status = el('p', {className: 'en-status', role: 'status', 'aria-live': 'polite'});
        var body = el('div', {className: 'en-body'});
        root.appendChild(body);
        root.appendChild(status);
        // Arrow keys inside the widget belong to it, not to item navigation.
        root.addEventListener('keydown', function (e) {
            if (/^Arrow/.test(e.key)) { e.stopPropagation(); }
        });
        var state = {instance: instanceId(), cfg: cfg, form: form, root: root, body: body, status: status,
                     hidden: hidden, answer: readStored(hidden), step: 0, selected: {}, pairIndex: {},
                     openPairs: {}, messages: {}, uid: 'en' + (++counter)};
        STATES.set(form, state);
        render(state);
        declare(state);
    }

    function init() {
        document.querySelectorAll('form.ego-network').forEach(setup);
    }

    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); }
    else { init(); }
    document.addEventListener('instanceChanged', init);
    document.addEventListener('potato:instance-ready', init);

    window.PotatoEgoNetwork = {init: init};
})();
