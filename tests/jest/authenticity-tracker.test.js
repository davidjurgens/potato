/**
 * Jest tests for authenticity_tracker.js
 *
 * The groups that matter most:
 *  - copy/paste classification: item text and in-page text are not "external",
 *    and an external paste after copying the item is recorded as such;
 *  - leaving the page: short absences and pages the task opened itself are not
 *    counted as leaving;
 *  - the payload never contains copied or pasted text.
 */

const fs = require("fs");
const path = require("path");

const SOURCE = fs.readFileSync(
  path.join(__dirname, "../../potato/static/authenticity_tracker.js"),
  "utf8"
);

const ITEM_TEXT = "The new policy will reduce emissions by thirty percent within five years.";

function setupDom() {
  document.body.innerHTML = `
    <div class="instance-area">
      <div id="instance-text"><div id="text-content" data-original-text="${ITEM_TEXT}">${ITEM_TEXT}</div></div>
    </div>
    <div id="annotation-forms"><textarea name="why"></textarea></div>
    <a id="codebook" href="/codebook" target="_blank">Codebook</a>`;
}

function loadTracker(config) {
  window.interactionTracker = {
    currentInstanceId: null,
    setInstanceId(id) { this.currentInstanceId = id; },
  };
  window.authenticityConfig = config || {};
  // eslint-disable-next-line no-eval
  eval(SOURCE);
  return window.authenticityTracker;
}

function selectItemText() {
  const sel = document.getSelection();
  sel.removeAllRanges();
  sel.selectAllChildren(document.getElementById("text-content"));
}

function paste(tracker, text) {
  tracker.onPaste({ clipboardData: { getData: () => text } });
}

let now;
beforeEach(() => {
  now = 1_000_000;
  jest.spyOn(Date, "now").mockImplementation(() => now);
  global.fetch = jest.fn(() => Promise.resolve({ ok: true }));
  navigator.sendBeacon = jest.fn(() => true);
  setupDom();
});
afterEach(() => {
  const t = window.authenticityTracker;
  if (t && t.flushTimer) clearInterval(t.flushTimer);
  jest.restoreAllMocks();
});

describe("copy and paste", () => {
  test("copying the item text is an item copy", () => {
    const t = loadTracker();
    selectItemText();
    t.onCopy({}, false);
    expect(t.s.item_copy_events).toBe(1);
    expect(t.s.item_copy_chars).toBeGreaterThan(40);
    expect(t.s.other_copy_events).toBe(0);
  });

  test("external paste after an item copy is recorded with its word count", () => {
    const t = loadTracker();
    selectItemText();
    t.onCopy({}, false);
    paste(t, "Overall I strongly agree because reducing emissions protects future generations and health");
    expect(t.s.external_paste_events).toBe(1);
    expect(t.s.max_paste_words_after_item_copy).toBe(12);
    expect(t.s.max_external_paste_words).toBe(12);
  });

  test("pasting the item text back is not external", () => {
    const t = loadTracker();
    paste(t, "reduce emissions by thirty percent");
    expect(t.s.item_paste_events).toBe(1);
    expect(t.s.external_paste_events).toBe(0);
  });

  test("pasting what was copied on the page is not external", () => {
    const t = loadTracker();
    const ta = document.querySelector("textarea");
    ta.value = "my own earlier draft sentence";
    ta.focus();
    ta.setSelectionRange(0, ta.value.length);
    t.onCopy({}, false);
    ta.value = "";
    paste(t, "my own earlier draft sentence");
    expect(t.s.external_paste_events).toBe(0);
    expect(t.s.other_copy_events).toBe(1);
  });

  test("an external paste without an item copy does not count as after-copy", () => {
    const t = loadTracker();
    paste(t, "Some text that came from somewhere else entirely");
    expect(t.s.external_paste_events).toBe(1);
    expect(t.s.max_paste_words_after_item_copy).toBe(0);
  });
});

describe("leaving the page", () => {
  function hide(t, hidden) {
    Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
    t.onVisibilityChange();
  }

  test("a tab switch is counted with its duration", () => {
    const t = loadTracker();
    hide(t, true);
    now += 15000;
    hide(t, false);
    expect(t.s.hidden_events).toBe(1);
    expect(t.s.hidden_ms).toBe(15000);
    expect(t.s.max_away_ms).toBe(15000);
  });

  test("absences shorter than min_away_ms are ignored", () => {
    const t = loadTracker({ min_away_ms: 2000 });
    hide(t, true);
    now += 500;
    hide(t, false);
    expect(t.s.hidden_events).toBe(0);
  });

  test("time away after copying the item is tracked separately", () => {
    const t = loadTracker();
    selectItemText();
    t.onCopy({}, false);
    hide(t, true);
    now += 30000;
    hide(t, false);
    expect(t.s.max_away_after_item_copy_ms).toBe(30000);
  });

  test("each absence after an item copy records gap, duration and copy size", () => {
    const t = loadTracker();
    selectItemText();
    t.onCopy({}, false);
    const chars = t.s.item_copy_chars;
    now += 4000;
    t.onWindowBlur();               // tab switch: blur first; the gap is measured from it
    now += 500;
    hide(t, true);                  // the duration, as before, from hidden
    now += 20000;
    hide(t, false);
    t.onWindowFocus();
    now += 1000;
    t.onWindowBlur();
    now += 3000;
    t.onWindowFocus();
    expect(t.s.copy_away_pairs).toEqual([[4000, 20000, chars], [25500, 3000, chars]]);
  });

  test("absences before any item copy record no pair", () => {
    const t = loadTracker();
    hide(t, true);
    now += 30000;
    hide(t, false);
    expect(t.s.copy_away_pairs).toEqual([]);
  });

  test("a page the task opened itself is linked, not away", () => {
    const t = loadTracker();
    t.onClick({ target: document.getElementById("codebook") });
    now += 500;
    hide(t, true);
    now += 60000;
    hide(t, false);
    expect(t.s.hidden_events).toBe(0);
    expect(t.s.linked_away_events).toBe(1);
    expect(t.s.linked_away_ms).toBe(60000);
  });

  test("window blur then focus is a blur absence; tab switch is not double-counted", () => {
    const t = loadTracker();
    t.onWindowBlur();
    now += 5000;
    t.onWindowFocus();
    expect(t.s.blur_events).toBe(1);

    t.onWindowBlur();
    hide(t, true);
    now += 5000;
    hide(t, false);
    t.onWindowFocus();
    expect(t.s.blur_events).toBe(1);
    expect(t.s.hidden_events).toBe(1);
  });
});

describe("pointer and automation", () => {
  const down = (x, y, type = "mouse") => ({ isTrusted: true, pointerType: type, clientX: x, clientY: y });
  const move = (x, y) => ({ isTrusted: true, pointerType: "mouse", clientX: x, clientY: y });

  test("clicks at a new position with no movement are teleports", () => {
    const t = loadTracker();
    t.onPointerDown(down(10, 10));
    t.onPointerDown(down(300, 200));
    t.onPointerDown(down(50, 400));
    expect(t.s.mouse_clicks).toBe(3);
    expect(t.s.teleport_clicks).toBe(2);
  });

  test("repeated clicks in place and moved clicks are not teleports", () => {
    const t = loadTracker();
    t.onPointerDown(down(10, 10));
    t.onPointerDown(down(11, 10));          // same spot (Next, Next, Next)
    t.onPointerMove(move(100, 100));
    t.onPointerDown(down(100, 100));
    expect(t.s.teleport_clicks).toBe(0);
    expect(t.s.pointer_distance_px).toBeGreaterThan(0);
  });

  test("returning to the page resets the teleport baseline", () => {
    const t = loadTracker();
    t.onPointerDown(down(10, 10));
    t.onWindowBlur();
    now += 3000;
    t.onWindowFocus();
    t.onPointerDown(down(400, 400));
    expect(t.s.teleport_clicks).toBe(0);
  });

  test("touch input is noted and not counted as mouse clicks", () => {
    const t = loadTracker();
    t.onPointerDown(down(10, 10, "touch"));
    expect(t.s.touch_input).toBe(true);
    expect(t.s.mouse_clicks).toBe(0);
  });

  test("script-generated keydown counts as untrusted", () => {
    const t = loadTracker();
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "a" }));
    expect(t.s.untrusted_events).toBe(1);
  });
});

describe("views and transport", () => {
  test("changing item flushes the old view and starts a new one", () => {
    const t = loadTracker();
    window.interactionTracker.setInstanceId("item_1");
    const firstView = t.viewId;
    t.bump("hidden_events");
    window.interactionTracker.setInstanceId("item_2");
    expect(t.viewId).not.toBe(firstView);
    expect(t.s.hidden_events).toBe(0);
    const bodies = global.fetch.mock.calls.map((c) => JSON.parse(c[1].body));
    const old = bodies.filter((b) => b.instance_id === "item_1" && b.view_id === firstView).pop();
    expect(old.snapshot.hidden_events).toBe(1);
  });

  test("the first instance id keeps what was counted during page load", () => {
    const t = loadTracker();
    const view = t.viewId;
    t.bump("hidden_events");
    window.interactionTracker.setInstanceId("item_1");
    expect(t.viewId).toBe(view);
    expect(t.s.hidden_events).toBe(1);
  });

  test("no post before the instance id is known", () => {
    const t = loadTracker();
    t.flush(false, true);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  test("pointer movement alone does not trigger a post", () => {
    const t = loadTracker();
    window.interactionTracker.setInstanceId("item_1");
    global.fetch.mockClear();
    t.dirty = false;
    t.lastSent = now;
    for (let i = 0; i < 20; i++) {
      now += 100;
      t.onPointerMove({ isTrusted: true, pointerType: "mouse", clientX: i * 10, clientY: 5 });
    }
    t.flush(false);
    expect(global.fetch).not.toHaveBeenCalled();
    // The totals still ride on the next post.
    t.flush(false, true);
    const body = JSON.parse(global.fetch.mock.calls[0][1].body);
    expect(body.snapshot.pointer_distance_px).toBeGreaterThan(0);
  });

  test("the outgoing view's last post and the page-hide post are final; others are not", () => {
    const t = loadTracker();
    window.interactionTracker.setInstanceId("item_1");
    const firstView = t.viewId;
    t.bump("hidden_events");
    t.flush(false);
    window.interactionTracker.setInstanceId("item_2");
    const bodies = global.fetch.mock.calls.map((c) => JSON.parse(c[1].body));
    const ordinary = bodies.filter((b) => b.view_id === firstView && !b.final);
    const last = bodies.filter((b) => b.view_id === firstView).pop();
    expect(ordinary.length).toBeGreaterThan(0);
    expect(last.final).toBe(true);
    expect(bodies.filter((b) => b.view_id === t.viewId).every((b) => b.final === false)).toBe(true);

    t.flush(true);
    const beacon = navigator.sendBeacon.mock.calls.pop();
    expect(beacon[0]).toBe("/api/track_authenticity");
  });

  test("payload never contains copied or pasted text", () => {
    const t = loadTracker();
    window.interactionTracker.setInstanceId("item_1");
    selectItemText();
    t.onCopy({}, false);
    const secret = "chatbot generated answer with many distinctive words inside it";
    paste(t, secret);
    t.flush(false, true);
    const sent = global.fetch.mock.calls.map((c) => c[1].body).join("\n");
    expect(sent).not.toContain("chatbot");
    expect(sent).not.toContain("emissions");
  });
});
