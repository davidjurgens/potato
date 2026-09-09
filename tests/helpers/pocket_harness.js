/**
 * Run potato/static/pocket.js under node against a stub DOM, so its queue
 * behaviour can be asserted rather than grepped for.
 *
 * Source-string assertions pass a rename and fail a refactor, which is
 * backwards. This gives the module a localStorage, a fetch and enough of a
 * document to boot, then drives it and reports what it did.
 *
 * Usage: node pocket_harness.js <scenario>   -> one JSON object on stdout
 */
const fs = require('fs');
const path = require('path');

const SCENARIO = process.argv[2];
const SRC = path.join(__dirname, '..', '..', 'potato', 'static', 'pocket.js');

// ---------------------------------------------------------------- stub DOM --
function makeEl(tag) {
  const el = {
    tagName: (tag || 'div').toUpperCase(),
    children: [], attrs: {}, classes: new Set(),
    _html: '', _text: '', hidden: false, style: {}, type: '', disabled: false,
    listeners: {},
    set className(v) { this.classes = new Set(String(v).split(/\s+/).filter(Boolean)); },
    get className() { return [...this.classes].join(' '); },
    classList: null,   // installed below; needs `this`
    // Real innerHTML replaces the text too; keeping a stale _text made the
    // stub report the previous message. It also has to build children, or
    // `card.querySelector('.pk-controls')` -- which pocket.js relies on --
    // returns null. Flat tags only: that is all this markup has.
    set innerHTML(v) {
      this._html = String(v);
      this._text = '';
      this.children = parseFlat(String(v));
    },
    get innerHTML() { return this._html; },
    set textContent(v) { this._text = String(v); this._html = String(v); },
    get textContent() { return this._text || stripTags(this._html); },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
    appendChild(c) { this.children.push(c); return c; },
    addEventListener(ev, fn) { (this.listeners[ev] = this.listeners[ev] || []).push(fn); },
    removeEventListener() {},
    click() { (this.listeners.click || []).forEach((f) => f({ preventDefault() {} })); },
    querySelector(sel) { return this.querySelectorAll(sel)[0] || null; },
    querySelectorAll(sel) {
      const want = sel.replace(/^\./, '');
      const out = [];
      const walk = (n) => {
        n.children.forEach((c) => {
          if (c.classes.has(want)) out.push(c);
          walk(c);
        });
      };
      walk(this);
      out.forEach = Array.prototype.forEach.bind(out);
      return out;
    },
    focus() {},
    closest() { return null; },
  };
  el.classList = {
    add: (c) => el.classes.add(c),
    remove: (c) => el.classes.delete(c),
    contains: (c) => el.classes.has(c),
    toggle: (c, on) => {
      const want = on === undefined ? !el.classes.has(c) : !!on;
      if (want) el.classes.add(c); else el.classes.delete(c);
      return want;
    },
  };
  return el;
}

function stripTags(s) { return String(s).replace(/<[^>]*>/g, ''); }

/**
 * Build child elements from a flat HTML string, enough for pocket.js's
 * `querySelector` calls. Only opening tags and their class/id attributes
 * matter here; nesting is not modelled because this markup has none that the
 * module looks through.
 */
function parseFlat(html) {
  const out = [];
  const re = /<(\w+)([^>]*)>/g;
  let m;
  while ((m = re.exec(html)) !== null) {
    const el = makeEl(m[1]);
    const cls = /class="([^"]*)"/.exec(m[2]);
    if (cls) el.className = cls[1];
    const id = /id="([^"]*)"/.exec(m[2]);
    if (id) { el.attrs.id = id[1]; byId[id[1]] = el; }
    if (/disabled/.test(m[2])) el.disabled = true;
    out.push(el);
  }
  return out;
}

const byId = {};
['pk-main', 'pk-sync', 'pk-progress', 'pk-count'].forEach((id) => {
  byId[id] = makeEl('div');
});

const documentListeners = {};
global.document = {
  visibilityState: 'visible',
  getElementById: (id) => byId[id] || null,
  createElement: makeEl,
  querySelector: (sel) => {
    if (sel === '.pk-progress') return makeEl('div');
    return byId['pk-main'].querySelector(sel);
  },
  querySelectorAll: (sel) => byId['pk-main'].querySelectorAll(sel),
  addEventListener(ev, fn) { (documentListeners[ev] = documentListeners[ev] || []).push(fn); },
  body: makeEl('body'),
};

const store = {};
global.localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: (k) => { delete store[k]; },
};

const windowListeners = {};
global.window = {
  addEventListener(ev, fn) { (windowListeners[ev] = windowListeners[ev] || []).push(fn); },
  location: { href: '/pocket' },
  matchMedia: () => ({ matches: true }),
};
global.matchMedia = global.window.matchMedia;
// node >= 21 ships a read-only `navigator`, so it has to be replaced rather
// than assigned.
Object.defineProperty(globalThis, 'navigator', {
  value: { onLine: true, vibrate: () => {} },
  configurable: true, writable: true,
});
global.setTimeout = ((fn) => { fn(); return 0; });
const intervals = [];
global.setInterval = ((fn, ms) => { intervals.push({ fn, ms }); return intervals.length; });

// ------------------------------------------------------------------- fetch --
let SAVE_STATUS = 200;
const posted = [];
global.fetch = (url, opts) => {
  if (String(url).indexOf('/updateinstance') === 0) {
    posted.push(JSON.parse(opts.body));
    const ok = SAVE_STATUS >= 200 && SAVE_STATUS < 300;
    return Promise.resolve({
      ok, status: SAVE_STATUS,
      json: () => Promise.resolve(ok ? { status: 'ok' } : { status: 'error' }),
    });
  }
  if (String(url).indexOf('/pocket/api/task') === 0) {
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve({
        capable: true, incompatible_schemes: [], batch_size: 25,
        schemas: [{ name: 'confidence_scale', annotation_type: 'likert',
                    description: 'How sure are you?', size: 5, labels: [],
                    min_label: 'Not at all', max_label: 'Certain' }],
      }),
    });
  }
  // /pocket/api/batch: an annotator who has reached the end of their batch,
  // which is exactly when there is no next save to piggyback a flush on.
  return Promise.resolve({
    ok: true, status: 200,
    json: () => Promise.resolve(
      SCENARIO === 'likert'
        ? { items: [{ instance_id: 'q1', text: 'well that went great',
                      annotations: {} }], total: 6, done: 0 }
        : { items: [], total: 6, done: 4 }),
  });
};

// -------------------------------------------------------------------- run --
const source = fs.readFileSync(SRC, 'utf8');
// The module reads these two constants from the page; give it the shape it
// expects rather than editing the source under test.
const QUEUE_KEY = 'pocket_save_queue_v1';

function chipText() {
  const c = byId['pk-sync'];
  return { text: stripTags(c.textContent || c.innerHTML),
           html: c.innerHTML,
           blocked: c.classes.has('pk-blocked'),
           hidden: c.hidden };
}

function mainText() { return stripTags(byId['pk-main'].innerHTML); }

const RECORD = (n) => ({
  instance_id: 'p' + n,
  annotations: { 'sarcasm:Sarcastic': 'on' },
  ts: 1000 + n,
  response_time_seconds: 4.25,
});

// Seed the queue BEFORE the module boots: this is a phone coming back to a
// page with unsent work, which is the situation under test.
if (SCENARIO !== 'done_empty' && SCENARIO !== 'likert') {
  global.localStorage.setItem(QUEUE_KEY, JSON.stringify([RECORD(2), RECORD(3)]));
} else {
  global.localStorage.setItem(QUEUE_KEY, JSON.stringify([]));
}
if (SCENARIO === 'refused' || SCENARIO === 'done_with_queue') SAVE_STATUS = 401;

// eslint-disable-next-line no-eval
eval(source);

/** Fire a real listener the module registered, the way the browser would. */
function fire(target, name) {
  const table = target === 'window' ? windowListeners : documentListeners;
  (table[name] || []).forEach((fn) => fn({}));
  return (table[name] || []).length;
}

const result = { scenario: SCENARIO };

// Boot is async (fetchTask -> fetchBatch). Let the promise chain drain, then
// drive the gesture, then let it drain again.
function drain(n) {
  let p = Promise.resolve();
  for (let i = 0; i < n; i += 1) p = p.then(() => {});
  return p;
}

drain(12).then(() => {
  if (SCENARIO === 'likert') {
    // Everything the annotator can see about the scale, and then a real click
    // on point 3 so we can read what gets stored.
    const buttons = byId['pk-main'].querySelectorAll('pk-opt');
    result.button_labels = buttons.map((b) => b.textContent);
    result.aria_labels = buttons.map((b) => b.getAttribute('aria-label'));
    const legend = byId['pk-main'].querySelector('pk-likert-legend');
    result.legend = legend ? stripTags(legend.innerHTML) : null;
    if (buttons.length >= 3) buttons[2].click();
    return drain(12);
  }
  if (SCENARIO === 'triggers') {
    result.window_events = Object.keys(windowListeners);
    result.document_events = Object.keys(documentListeners);
    result.interval_count = intervals.length;
    result.interval_ms = intervals.length ? intervals[0].ms : null;
    return null;
  }
  if (SCENARIO === 'flush_succeeds') SAVE_STATUS = 200;
  // Coming back to the tab: the module should try to drain the queue.
  result.visibility_listeners = fire('document', 'visibilitychange');
  return drain(12);
}).then(() => {
  if (SCENARIO === 'triggers') return;
  result.chip = chipText();
  result.main = mainText();
  result.queue_length = JSON.parse(global.localStorage.getItem(QUEUE_KEY)).length;
  result.attempts = posted.length;
  result.sent_response_time = posted.length ? posted[0].response_time_seconds : null;
  result.sent_keys = posted.length ? Object.keys(posted[0]).sort() : [];
  result.sent_annotations = posted.length
    ? posted[posted.length - 1].annotations : null;
}).then(() => {
  console.log(JSON.stringify(result));
}).catch((e) => {
  console.log(JSON.stringify({ error: String(e && e.stack || e) }));
});
