/*
 * Incentivized elicitation widgets: price_list (multiple price list), bdm
 * (Becker-DeGroot-Marschak bid) and belief_elicitation (a probability or a
 * distribution over bins).
 *
 * Each widget keeps its answer as JSON in the scheme's hidden input and
 * restores its visual state from that input, which the server pre-fills on
 * every page load. Completeness is declared on the form's
 * data-incomplete-reason, which validateRequiredFields reads.
 *
 * Nothing here draws a lottery, a price or a prize: payment is computed on
 * the server after the participant has finished (potato/incentives.py).
 */
(function () {
    'use strict';
    if (window.PotatoIncentiveWidgets) { return; }

    function hiddenInput(form) { return form.querySelector('.incentive-input'); }

    function readStored(form) {
        var h = hiddenInput(form);
        if (h && h.value) {
            try { return JSON.parse(h.value) || {}; } catch (e) { return {}; }
        }
        return {};
    }

    function store(form, data) {
        var h = hiddenInput(form);
        if (!h) { return; }
        var next = data ? JSON.stringify(data) : '';
        if (h.value === next) { return; }
        h.value = next;
        h.setAttribute('data-modified', 'true');
        h.dispatchEvent(new Event('change', {bubbles: true}));
    }

    function declare(form, reason) {
        if (reason) { form.setAttribute('data-incomplete-reason', reason); }
        else { form.removeAttribute('data-incomplete-reason'); }
    }

    function status(form, text, tone) {
        var s = form.querySelector('.iw-status');
        if (!s) { return; }
        s.textContent = text || '';
        s.setAttribute('data-tone', tone || '');
    }

    function config(form, attr) {
        try { return JSON.parse(form.getAttribute(attr) || '{}'); } catch (e) { return {}; }
    }

    function money(amount, currency) {
        return currency + Number(amount).toFixed(2);
    }

    function listRows(rows) {
        var shown = rows.slice(0, 5).map(function (r) { return r + 1; }).join(', ');
        return rows.length > 5 ? shown + ' and ' + (rows.length - 5) + ' more' : shown;
    }

    // ------------------------------------------------------------------
    // price_list
    // ------------------------------------------------------------------

    function countSwitches(choices) {
        var answered = choices.filter(function (c) { return c === 'A' || c === 'B'; });
        var n = 0;
        for (var i = 1; i < answered.length; i++) { if (answered[i] !== answered[i - 1]) { n++; } }
        return n;
    }

    function priceList(form) {
        var cfg = config(form, 'data-price-list');
        var n = cfg.rows || 0;
        var st = form._iw;
        if (!st) {
            st = form._iw = {choices: []};
            form.addEventListener('click', function (e) {
                var b = e.target.closest('.pl-choice');
                if (!b || !form.contains(b)) { return; }
                st.choose(parseInt(b.getAttribute('data-row'), 10), b.getAttribute('data-choice'));
            });
        }
        var stored = readStored(form).choices;
        st.choices = [];
        for (var i = 0; i < n; i++) {
            var c = stored && stored[i];
            st.choices.push(c === 'A' || c === 'B' ? c : null);
        }

        function choose(row, choice) {
            var before = st.choices.slice();
            if (cfg.single_switch) {
                if (choice === 'B') { for (var i = row; i < n; i++) { st.choices[i] = 'B'; } }
                else { for (var j = 0; j <= row; j++) { st.choices[j] = 'A'; } }
            } else {
                st.choices[row] = choice;
            }
            var changed = [];
            st.choices.forEach(function (c, k) { if (k !== row && c !== before[k]) { changed.push(k); } });
            save();
            render(changed);
        }

        function save() {
            var switches = countSwitches(st.choices);
            var any = st.choices.some(function (c) { return c !== null; });
            store(form, any ? {choices: st.choices.slice(), switches: switches,
                               multiple_switching: switches > 1} : null);
        }

        function render(autoFilled) {
            form.querySelectorAll('.pl-row').forEach(function (rowEl) {
                var r = parseInt(rowEl.getAttribute('data-row'), 10);
                var chosen = st.choices[r];
                var buttons = rowEl.querySelectorAll('.pl-choice');
                buttons.forEach(function (b) {
                    var on = b.getAttribute('data-choice') === chosen;
                    b.setAttribute('aria-checked', on ? 'true' : 'false');
                    // One tab stop per row: the chosen option, or A.
                    b.tabIndex = (on || (!chosen && b.getAttribute('data-choice') === 'A')) ? 0 : -1;
                });
                rowEl.classList.toggle('pl-answered', !!chosen);
                if (autoFilled && autoFilled.indexOf(r) >= 0) {
                    rowEl.classList.remove('pl-auto');
                    void rowEl.offsetWidth;
                    rowEl.classList.add('pl-auto');
                }
            });
            var missing = [];
            st.choices.forEach(function (c, k) { if (!c) { missing.push(k); } });
            var made = n - missing.length;
            var text = made + ' of ' + n + ' decisions made.';
            if (!missing.length) {
                var firstB = st.choices.indexOf('B');
                if (firstB < 0) { text += ' You chose Option A in every row.'; }
                else if (countSwitches(st.choices) === 1 && st.choices[0] === 'A') {
                    text += ' You switch to Option B at decision ' + (firstB + 1) + '.';
                } else if (firstB === 0 && countSwitches(st.choices) === 0) {
                    text += ' You chose Option B in every row.';
                }
            }
            status(form, text, missing.length ? '' : 'done');
            declare(form, missing.length ? 'choose A or B in decision ' + listRows(missing) : null);
        }

        st.choose = choose;
        render();
    }

    function onPriceListKey(e) {
        var b = e.target.closest && e.target.closest('.pl-choice');
        if (!b) { return; }
        var form = b.closest('form.price-list');
        var st = form && form._iw;
        if (!st) { return; }
        var row = parseInt(b.getAttribute('data-row'), 10);
        var side = b.getAttribute('data-choice');
        var target = null;
        if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
            side = e.key === 'ArrowLeft' ? 'A' : 'B';
            st.choose(row, side);
            target = form.querySelector('.pl-choice[data-row="' + row + '"][data-choice="' + side + '"]');
        } else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
            target = form.querySelector('.pl-choice[data-row="' + (row + (e.key === 'ArrowUp' ? -1 : 1)) +
                                        '"][data-choice="' + side + '"]');
        } else if (e.key === ' ' || e.key === 'Enter') {
            st.choose(row, side);
            target = b;
        } else {
            return;
        }
        // Potato's own shortcuts (arrows move between items) must not also fire.
        e.preventDefault();
        e.stopPropagation();
        if (target) { target.focus(); }
    }

    // ------------------------------------------------------------------
    // bdm
    // ------------------------------------------------------------------

    function decimals(step) {
        var s = String(step);
        return s.indexOf('.') >= 0 ? s.length - s.indexOf('.') - 1 : 0;
    }

    function bdm(form) {
        var cfg = config(form, 'data-bdm');
        var numberEl = form.querySelector('.bdm-number');
        var slider = form.querySelector('.bdm-slider');
        var out = form.querySelector('.bdm-value');
        var places = Math.max(2, decimals(cfg.step));
        var range = money(cfg.min, cfg.currency) + ' to ' + money(cfg.max, cfg.currency);

        function round(v) { var f = Math.pow(10, places); return Math.round(v * f) / f; }

        function show(bid) {
            if (slider) {
                slider.classList.toggle('bdm-set', bid !== null);
                if (bid !== null) { slider.value = String(bid); }
                out.textContent = bid !== null ? money(bid, cfg.currency) : '–';
                slider.setAttribute('aria-valuetext', bid !== null ? money(bid, cfg.currency) : 'not set');
            }
            if (numberEl && bid !== null && document.activeElement !== numberEl) {
                numberEl.value = String(bid);
            }
        }

        function settle(raw, fromUser) {
            var bid = null, problem = null;
            if (raw !== '' && raw !== null && raw !== undefined) {
                var v = Number(raw);
                if (!isFinite(v)) { problem = 'Enter a number.'; }
                else if (v < cfg.min || v > cfg.max) { problem = 'Enter an amount from ' + range + '.'; }
                else { bid = round(v); }
            }
            if (numberEl) {
                numberEl.setAttribute('aria-invalid', problem ? 'true' : 'false');
            }
            if (fromUser) { store(form, bid !== null ? {bid: bid} : null); }
            show(bid);
            if (problem) { status(form, problem, 'error'); }
            else if (bid !== null) { status(form, 'Your bid: ' + money(bid, cfg.currency) + '.', 'done'); }
            else { status(form, '', ''); }
            declare(form, bid !== null ? null : (problem ? 'enter a bid from ' + range : 'enter a bid'));
        }

        if (!form._iw) {
            form._iw = {};
            if (numberEl) {
                numberEl.addEventListener('input', function () { settle(numberEl.value, true); });
                numberEl.addEventListener('change', function () {
                    var s = readStored(form);
                    if (s.bid !== undefined && s.bid !== null) { numberEl.value = String(s.bid); }
                });
            }
            if (slider) {
                slider.addEventListener('input', function () { settle(slider.value, true); });
                // A click on the thumb at its starting point fires no input
                // event; it is still an answer.
                slider.addEventListener('pointerup', function () {
                    if (!slider.classList.contains('bdm-set')) { settle(slider.value, true); }
                });
            }
        }
        var stored = readStored(form);
        var initial = (stored.bid === undefined || stored.bid === null) ? '' : stored.bid;
        if (numberEl) { numberEl.value = initial === '' ? '' : String(initial); }
        settle(initial, false);
    }

    // ------------------------------------------------------------------
    // belief_elicitation
    // ------------------------------------------------------------------

    function belief(form) {
        var cfg = config(form, 'data-belief');
        if (cfg.mode === 'bins') { return beliefBins(form, cfg); }
        var slider = form.querySelector('.be-slider');
        var out = form.querySelector('.be-value');

        function show(p) {
            slider.classList.toggle('be-set', p !== null);
            if (p !== null) { slider.value = String(p); }
            out.textContent = p !== null ? p + '%' : '–';
            slider.setAttribute('aria-valuetext', p !== null ? p + ' percent' : 'not set');
            declare(form, p !== null ? null : 'set a probability');
        }
        if (!form._iw) {
            form._iw = {};
            var pick = function () {
                var p = Number(slider.value);
                store(form, {report: p});
                show(p);
            };
            slider.addEventListener('input', pick);
            // A click on the thumb at its starting point fires no input
            // event; it is still an answer.
            slider.addEventListener('pointerup', function () {
                if (!slider.classList.contains('be-set')) { pick(); }
            });
        }
        var s = readStored(form);
        show(typeof s.report === 'number' ? s.report : null);
    }

    function beliefBins(form, cfg) {
        var inputs = Array.prototype.slice.call(form.querySelectorAll('.be-bin-input'));
        var total = cfg.total || 100;

        function values() {
            return inputs.map(function (el) {
                if (el.value === '') { return null; }
                var v = Number(el.value);
                return isFinite(v) ? Math.round(v) : NaN;
            });
        }

        function show(vals) {
            var sum = 0, bad = false;
            vals.forEach(function (v, i) {
                var invalid = (v !== null && (isNaN(v) || v < 0 || v > total));
                bad = bad || invalid;
                inputs[i].setAttribute('aria-invalid', invalid ? 'true' : 'false');
                var fill = inputs[i].parentNode.querySelector('.be-bar-fill');
                var w = (v === null || isNaN(v)) ? 0 : Math.max(0, Math.min(total, v));
                if (fill) { fill.style.width = (100 * w / total) + '%'; }
                if (!invalid && v !== null) { sum += v; }
            });
            var touched = vals.some(function (v) { return v !== null; });
            var sumEl = form.querySelector('.be-sum');
            var left = form.querySelector('.be-left');
            var box = form.querySelector('.be-total');
            sumEl.textContent = String(sum);
            var state = bad ? 'error' : (sum === total ? 'done' : (sum > total ? 'over' : 'under'));
            box.setAttribute('data-state', touched ? state : 'empty');
            if (bad) { left.textContent = '— each range takes 0 to ' + total + ' points'; }
            else if (sum === total) { left.textContent = '— complete'; }
            else if (sum > total) { left.textContent = '— ' + (sum - total) + ' too many'; }
            else { left.textContent = '— ' + (total - sum) + ' left to place'; }
            var reason = null;
            if (bad) { reason = 'each range takes 0 to ' + total + ' points'; }
            else if (sum !== total) { reason = 'allocate exactly ' + total + ' points (now ' + sum + ')'; }
            declare(form, reason);
            return {sum: sum, bad: bad, touched: touched};
        }

        if (!form._iw) {
            form._iw = {};
            inputs.forEach(function (el) {
                el.addEventListener('input', function () {
                    var vals = values();
                    var s = show(vals);
                    store(form, s.touched ? {bins: vals.map(function (v) {
                        return (v === null || isNaN(v)) ? 0 : v;
                    })} : null);
                });
                el.addEventListener('change', function () {
                    if (el.value !== '' && isFinite(Number(el.value))) {
                        el.value = String(Math.round(Number(el.value)));
                    }
                });
            });
        }
        var stored = readStored(form).bins;
        inputs.forEach(function (el, i) {
            var v = stored && stored[i];
            el.value = (typeof v === 'number' && stored) ? String(v) : '';
        });
        show(values());
    }

    // ------------------------------------------------------------------

    function init() {
        document.querySelectorAll('form.price-list').forEach(priceList);
        document.querySelectorAll('form.bdm').forEach(bdm);
        document.querySelectorAll('form.belief-elicitation').forEach(belief);
    }

    document.addEventListener('keydown', onPriceListKey, true);
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); }
    else { init(); }
    document.addEventListener('instanceChanged', init);
    document.addEventListener('potato:instance-ready', init);

    window.PotatoIncentiveWidgets = {init: init, countSwitches: countSwitches};
})();
