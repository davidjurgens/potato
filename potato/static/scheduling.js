/* Scheduled sessions (potato/scheduling): time zone detection on the
   enrolment page, the first-answer beacon that starts the latency clock, and
   slider state. No library; works without it except for latency, which then
   falls back to the submit time. */
(function () {
    'use strict';

    function detectTimezone() {
        var select = document.getElementById('timezone');
        var hidden = document.getElementById('timezone-detected');
        if (!select || !hidden) return;
        var tz = '';
        try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (e) { tz = ''; }
        hidden.value = tz;
        // Only replace the server's default, never a choice already made.
        var untouched = select.value === select.getAttribute('data-default');
        if (tz && untouched && !document.querySelector('#timezone-error')) {
            for (var i = 0; i < select.options.length; i++) {
                if (select.options[i].value === tz) { select.value = tz; break; }
            }
        }
    }

    function firstAnswerBeacon() {
        var form = document.getElementById('schedule-session-form');
        if (!form) return;
        var url = form.getAttribute('data-started-url');
        var sent = false;
        function send() {
            if (sent || !url) return;
            sent = true;
            try {
                fetch(url, {method: 'POST', credentials: 'same-origin',
                            headers: {'Content-Type': 'application/json'}, body: '{}'})
                    .catch(function () { sent = false; });
            } catch (e) { sent = false; }
        }
        form.addEventListener('change', send);
        form.addEventListener('input', send);
    }

    function sliders() {
        var ranges = document.querySelectorAll('.sched-slider input[type=range]');
        Array.prototype.forEach.call(ranges, function (range) {
            var wrap = range.closest('.sched-slider');
            var out = wrap.querySelector('output');
            var touched = wrap.querySelector('input[type=hidden]');
            range.addEventListener('input', function () {
                range.setAttribute('data-touched', '1');
                if (touched) touched.value = '1';
                if (out) out.textContent = range.value;
            });
        });
    }

    function localHints() {
        // A participant who travelled sees the time where they are now too.
        var here = '';
        try { here = Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (e) { return; }
        var nodes = document.querySelectorAll('time[data-epoch]');
        Array.prototype.forEach.call(nodes, function (node) {
            var iso = node.getAttribute('datetime') || '';
            var epoch = parseInt(node.getAttribute('data-epoch'), 10);
            if (!epoch || !here) return;
            var offsetThere = iso.slice(19);
            var d = new Date(epoch * 1000);
            var mins = -d.getTimezoneOffset();
            var sign = mins >= 0 ? '+' : '-';
            var abs = Math.abs(mins);
            var offsetHere = sign + ('0' + Math.floor(abs / 60)).slice(-2) + ':' + ('0' + (abs % 60)).slice(-2);
            if (offsetThere && offsetThere !== offsetHere) {
                var span = document.createElement('span');
                span.className = 'sched-muted';
                span.textContent = ' (' + d.toLocaleString([], {weekday: 'short', hour: '2-digit', minute: '2-digit'}) + ' where you are now)';
                node.parentNode.insertBefore(span, node.nextSibling);
            }
        });
    }

    function init() {
        detectTimezone();
        firstAnswerBeacon();
        sliders();
        localHints();
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
