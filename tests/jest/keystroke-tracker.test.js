/**
 * Jest tests for keystroke_tracker.js
 *
 * Covers the pure classification helpers and the field-eligibility rules. The
 * two groups that matter most:
 *
 *  - `getFieldIdentity` must refuse password fields and non-annotation inputs.
 *    A tracker that attached to the wrong box would be logging typing dynamics
 *    on credentials.
 *  - `classifyKey` must never return the key itself. The whole privacy claim of
 *    this feature rests on the stream being content-blind.
 */

const fs = require("fs");
const path = require("path");

const SOURCE = fs.readFileSync(
  path.join(__dirname, "../../potato/static/keystroke_tracker.js"),
  "utf8"
);

/** Load the module fresh with a given config. */
function loadTracker(config) {
  window.keystrokeConfig = config || { enabled: false };
  // The file ends by constructing a global instance; eval in this scope so the
  // class and the instance both land on `window`.
  // eslint-disable-next-line no-eval
  eval(SOURCE);
  return window.keystrokeTracker;
}

function makeField({ tag = "textarea", type = "text", schema = "notes",
                     label = "body", name = null, attrs = {} } = {}) {
  const el = document.createElement(tag);
  if (tag === "input") el.setAttribute("type", type);
  if (schema) el.setAttribute("schema", schema);
  if (label) el.setAttribute("label_name", label);
  if (name) el.setAttribute("name", name);
  Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
  document.body.appendChild(el);
  return el;
}

describe("KeystrokeTracker", () => {
  let tracker;

  beforeEach(() => {
    document.body.innerHTML = "";
    tracker = loadTracker({ enabled: true, fidelity: "events" });
  });

  // -----------------------------------------------------------------
  describe("classifyKey", () => {
    const cases = {
      a: "letter", Z: "letter", "é": "letter", "ß": "letter",
      0: "digit", 7: "digit",
      " ": "space",
      ".": "punct", ",": "punct", "!": "punct", "-": "punct",
      Enter: "enter",
      Backspace: "bksp",
      Delete: "del",
      ArrowLeft: "nav", ArrowRight: "nav", ArrowUp: "nav", ArrowDown: "nav",
      Home: "nav", End: "nav", PageUp: "nav", PageDown: "nav",
      Shift: "mod", Control: "mod", Alt: "mod", Meta: "mod", CapsLock: "mod",
      Tab: "func", Escape: "func", F1: "func", F12: "func",
      Unidentified: "unknown",
    };

    Object.entries(cases).forEach(([key, expected]) => {
      test(`"${key}" -> ${expected}`, () => {
        expect(tracker.classifyKey(key)).toBe(expected);
      });
    });

    test("returns a class, never the key itself", () => {
      const valid = ["unknown", "letter", "digit", "punct", "space", "enter",
                     "bksp", "del", "nav", "mod", "func"];
      "abcXYZ019!?.,;:'\"\\/@#$%^&*()".split("").forEach((ch) => {
        const cls = tracker.classifyKey(ch);
        expect(valid).toContain(cls);
        expect(cls).not.toBe(ch);
      });
    });

    test("handles null and empty input", () => {
      expect(tracker.classifyKey(null)).toBe("unknown");
      expect(tracker.classifyKey("")).toBe("unknown");
      expect(tracker.classifyKey(undefined)).toBe("unknown");
    });
  });

  // -----------------------------------------------------------------
  describe("classifyInputType", () => {
    test("passes through known input types", () => {
      ["insertText", "insertFromPaste", "insertFromDrop",
       "insertCompositionText", "deleteContentBackward", "historyUndo",
       "insertReplacementText"].forEach((t) => {
        expect(tracker.classifyInputType(t)).toBe(t);
      });
    });

    test("maps unknown types to 'other' rather than dropping them", () => {
      expect(tracker.classifyInputType("insertFromTheFuture")).toBe("other");
      expect(tracker.classifyInputType(undefined)).toBe("other");
    });
  });

  // -----------------------------------------------------------------
  describe("classifyPasteSource", () => {
    beforeEach(() => { tracker.classifyPaste = true; });

    test("detects re-pasting the field's own content", () => {
      expect(tracker.classifyPasteSource(
        "the quick brown fox jumps",
        "I wrote the quick brown fox jumps over the lazy dog"
      )).toBe("self");
    });

    test("detects the passage under annotation", () => {
      const el = document.createElement("div");
      el.id = "instance-text";
      el.textContent = "A city council is debating whether to convert two lanes.";
      document.body.appendChild(el);
      expect(tracker.classifyPasteSource(
        "debating whether to convert two lanes", "")).toBe("instance_text");
    });

    test("detects AI suggestion text", () => {
      const el = document.createElement("div");
      el.className = "ai-suggestion";
      el.textContent = "The passage exhibits a marked shift in tone throughout.";
      document.body.appendChild(el);
      expect(tracker.classifyPasteSource(
        "exhibits a marked shift in tone", "")).toBe("ai_suggestion");
    });

    test("anything unattributable is external", () => {
      expect(tracker.classifyPasteSource(
        "an entirely unrelated paragraph of prose", "")).toBe("external");
    });

    test("very short pastes are not attributed either way", () => {
      expect(tracker.classifyPasteSource("hi", "")).toBe("unknown");
    });

    test("normalizes whitespace before comparing", () => {
      const el = document.createElement("div");
      el.id = "instance-text";
      el.textContent = "the   quick\n\nbrown    fox jumps over";
      document.body.appendChild(el);
      expect(tracker.classifyPasteSource(
        "the quick brown fox jumps", "")).toBe("instance_text");
    });

    test("returns 'unknown' when classification is disabled", () => {
      tracker.classifyPaste = false;
      expect(tracker.classifyPasteSource("some long pasted text here", ""))
        .toBe("unknown");
    });
  });

  // -----------------------------------------------------------------
  describe("hashText", () => {
    test("is stable within a session", () => {
      expect(tracker.hashText("secret")).toBe(tracker.hashText("secret"));
    });

    test("distinguishes different text", () => {
      expect(tracker.hashText("aaa")).not.toBe(tracker.hashText("bbb"));
    });

    test("is salted, so the same text hashes differently across sessions", () => {
      const other = loadTracker({ enabled: true });
      other.salt = "different-salt";
      expect(other.hashText("secret")).not.toBe(tracker.hashText("secret"));
    });

    test("does not contain the input text", () => {
      expect(tracker.hashText("password123")).not.toContain("password");
    });
  });

  // -----------------------------------------------------------------
  describe("getFieldIdentity", () => {
    test("identifies a schema/label-attributed textarea", () => {
      const el = makeField({ schema: "rationale", label: "rationale" });
      expect(tracker.getFieldIdentity(el)).toEqual({
        key: "rationale:::rationale", schema: "rationale", label: "rationale",
      });
    });

    test("identifies a text input", () => {
      const el = makeField({ tag: "input", schema: "notes", label: "body" });
      expect(tracker.getFieldIdentity(el).key).toBe("notes:::body");
    });

    test("falls back to splitting the name attribute", () => {
      const el = makeField({ schema: null, label: null,
                             name: "tradeoffs:::tradeoffs" });
      expect(tracker.getFieldIdentity(el)).toEqual({
        key: "tradeoffs:::tradeoffs", schema: "tradeoffs", label: "tradeoffs",
      });
    });

    test("REFUSES password fields", () => {
      const el = makeField({ tag: "input", type: "password" });
      expect(tracker.getFieldIdentity(el)).toBeNull();
    });

    test("REFUSES fields marked data-keystroke-logging=off", () => {
      const el = makeField({ attrs: { "data-keystroke-logging": "off" } });
      expect(tracker.getFieldIdentity(el)).toBeNull();
    });

    test("refuses unidentifiable inputs (search boxes, chat)", () => {
      const el = makeField({ schema: null, label: null });
      expect(tracker.getFieldIdentity(el)).toBeNull();
    });

    test("refuses non-text elements", () => {
      expect(tracker.getFieldIdentity(makeField({ tag: "input", type: "checkbox" })))
        .toBeNull();
      expect(tracker.getFieldIdentity(makeField({ tag: "div" }))).toBeNull();
      expect(tracker.getFieldIdentity(null)).toBeNull();
    });

    test("honours exclude_schemas", () => {
      tracker.excludeSchemas = ["notes"];
      expect(tracker.getFieldIdentity(makeField({ schema: "notes" }))).toBeNull();
      expect(tracker.getFieldIdentity(makeField({ schema: "other" }))).not.toBeNull();
    });

    test("honours include_schemas as an allowlist", () => {
      tracker.includeSchemas = ["rationale"];
      expect(tracker.getFieldIdentity(makeField({ schema: "notes" }))).toBeNull();
      expect(tracker.getFieldIdentity(makeField({ schema: "rationale" })))
        .not.toBeNull();
    });

    test("empty include_schemas means every field", () => {
      tracker.includeSchemas = [];
      expect(tracker.getFieldIdentity(makeField({ schema: "anything" })))
        .not.toBeNull();
    });
  });

  // -----------------------------------------------------------------
  describe("configuration gating", () => {
    test("does not initialize when disabled", () => {
      expect(loadTracker({ enabled: false }).isInitialized).toBeFalsy();
    });

    test("does not initialize at fidelity 'off'", () => {
      expect(loadTracker({ enabled: true, fidelity: "off" }).isInitialized)
        .toBeFalsy();
    });

    test("initializes when enabled", () => {
      expect(loadTracker({ enabled: true, fidelity: "events" }).isInitialized)
        .toBe(true);
    });

    test("absent config is treated as disabled", () => {
      window.keystrokeConfig = undefined;
      // eslint-disable-next-line no-eval
      eval(SOURCE);
      expect(window.keystrokeTracker.enabled).toBe(false);
    });
  });

  // -----------------------------------------------------------------
  describe("event recording", () => {
    test("records events against a session", () => {
      const session = { events: [], startedAt: Date.now(), lastActivity: 0 };
      tracker.addEvent(session, {
        input_type: "insertText", key_class: "letter", pos: 3, delta: 1 });
      expect(session.events).toHaveLength(1);
      expect(session.events[0]).toMatchObject({
        input_type: "insertText", key_class: "letter", pos: 3, delta: 1 });
      expect(typeof session.events[0].t_ms).toBe("number");
    });

    test("recorded events never carry the typed characters", () => {
      const session = { events: [], startedAt: Date.now(), lastActivity: 0 };
      tracker.addEvent(session, {
        input_type: "insertText", key_class: "letter", pos: 0, delta: 1 });
      const keys = Object.keys(session.events[0]);
      expect(keys.sort()).toEqual(
        ["delta", "input_type", "key_class", "meta", "pos", "t_ms"]);
      expect(keys).not.toContain("data");
      expect(keys).not.toContain("text");
    });

    test("caps runaway sessions and marks them truncated", () => {
      const session = { events: [], startedAt: Date.now(), lastActivity: 0 };
      tracker.maxEventsPerSession = 5;
      for (let i = 0; i < 20; i++) {
        tracker.addEvent(session, { input_type: "insertText", delta: 1 });
      }
      expect(session.events).toHaveLength(5);
      expect(session.truncated).toBe(true);
    });
  });
});
