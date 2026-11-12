/*
 * A link-out page (type: external): the participant follows a link to a task
 * on another server, which sends them back to the return address in the
 * link. Nothing is posted from this page; the return route records the run.
 */
(function () {
    'use strict';
    var rt = window.potatoRuntime;
    if (!rt) { return; }
    var opts = rt.config.runtime || {};
    rt.onStart(function () {
        var target = document.getElementById('runtime-target');
        var box = document.createElement('div');
        box.className = 'hc-box';
        if (opts.description) {
            var p = document.createElement('p');
            p.textContent = opts.description;
            box.appendChild(p);
        }
        var a = document.createElement('a');
        a.className = 'hc-btn hc-primary';
        a.id = 'external-start';
        a.href = opts.link;
        a.textContent = opts.button_text || 'Continue to the task';
        if (opts.new_tab) { a.target = '_blank'; a.rel = 'noopener'; }
        box.appendChild(a);
        var note = document.createElement('p');
        note.textContent = 'When you finish there, you will come back here to continue.';
        box.appendChild(note);
        target.appendChild(box);
        a.focus();
    });
})();
