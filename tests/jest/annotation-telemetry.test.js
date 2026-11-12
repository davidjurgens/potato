/**
 * Jest tests for annotation_telemetry.js
 *
 * The client's whole job is buffering and cutting sessions on the right
 * boundary; the features are derived server-side from the stream it sends, so
 * that is what these tests assert on — the payload shape, the scoping rules,
 * and the session boundary.
 *
 * The boundary is the part worth the most care: a session that straddles two
 * instances is attributed to whichever id happened to be current at flush time,
 * which silently moves one image's work onto another.
 */

const fs = require("fs");
const path = require("path");

const SOURCE = fs.readFileSync(
  path.join(__dirname, "../../potato/static/annotation_telemetry.js"),
  "utf8"
);

/** Load the module fresh with a given config. */
function loadTracker(config) {
  window.annotationTelemetryConfig = config || { enabled: false };
  // The file ends by constructing a global instance; eval in this scope so the
  // class, the emitter and the instance all land on `window`.
  // eslint-disable-next-line no-eval
  eval(SOURCE);
  return window.annotationTelemetryTracker;
}

function emit(schema, action, detail) {
  window.recordAnnotationTelemetry(schema, action, detail);
}

/** Capture what the tracker POSTs, without a network. */
function captureFlush() {
  const sent = [];
  global.fetch = jest.fn((url, opts) => {
    sent.push({ url, body: JSON.parse(opts.body) });
    return Promise.resolve({ ok: true });
  });
  return sent;
}

describe("AnnotationTelemetryTracker", () => {
  let tracker;
  let sent;

  beforeEach(() => {
    jest.useFakeTimers();
    delete window.interactionTracker;
    sent = captureFlush();
    tracker = loadTracker({ enabled: true, fidelity: "events" });
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  // -----------------------------------------------------------------
  describe("emitter", () => {
    test("dispatches a CustomEvent the tracker receives", () => {
      emit("objects", "shape_add", { shape: "bbox", value: 4 });
      expect(tracker.sessions.objects.events).toHaveLength(1);
      expect(tracker.sessions.objects.events[0]).toMatchObject({
        action: "shape_add", shape: "bbox", value: 4,
      });
    });

    test("is safe to call when no tracker is listening", () => {
      // The whole decoupling rests on this: measurement must never be able to
      // break drawing.
      window.annotationTelemetryTracker = undefined;
      expect(() => emit("objects", "shape_add", { shape: "bbox" })).not.toThrow();
    });

    test("ignores a call with no schema or no action", () => {
      emit(null, "shape_add", {});
      emit("objects", null, {});
      expect(Object.keys(tracker.sessions)).toHaveLength(0);
    });

    test("an environment with no CustomEvent loses the measurement, not the drawing", () => {
      // Listener isolation is the DOM's guarantee, not this try/catch's — an
      // exception inside a listener is reported rather than propagated. What
      // the guard actually covers is a missing constructor.
      const real = window.CustomEvent;
      window.CustomEvent = function () { throw new Error("unsupported"); };
      try {
        expect(() => emit("objects", "undo", {})).not.toThrow();
      } finally {
        window.CustomEvent = real;
      }
    });
  });

  // -----------------------------------------------------------------
  describe("event shape", () => {
    test("value is rounded, not truncated", () => {
      // The wire format is integers. Truncating would bias every zoom level
      // down by up to a full percent.
      emit("objects", "zoom", { value: 249.7 });
      expect(tracker.sessions.objects.events[0].value).toBe(250);
    });

    test("a missing value becomes 0 rather than NaN", () => {
      emit("objects", "undo", {});
      expect(tracker.sessions.objects.events[0].value).toBe(0);
    });

    test("shape defaults to unknown", () => {
      emit("objects", "undo", {});
      expect(tracker.sessions.objects.events[0].shape).toBe("unknown");
    });

    test("meta is carried only when present", () => {
      emit("objects", "tool", { meta: { tool: "brush" } });
      emit("objects", "undo", {});
      const events = tracker.sessions.objects.events;
      expect(events[0].meta).toEqual({ tool: "brush" });
      expect(events[1].meta).toBeUndefined();
    });

    test("timestamps are relative to the session, never absolute", () => {
      // Absolute wall-clock times would say something about the annotator
      // beyond the session's own duration.
      emit("objects", "shape_add", { shape: "bbox" });
      expect(tracker.sessions.objects.events[0].t_ms).toBeLessThan(1000);
    });

    test("no event field can carry a coordinate", () => {
      emit("objects", "shape_add", { shape: "polygon", value: 12, x: 40, y: 80 });
      expect(Object.keys(tracker.sessions.objects.events[0]).sort())
        .toEqual(["action", "shape", "t_ms", "value"]);
    });
  });

  // -----------------------------------------------------------------
  describe("schema scoping", () => {
    test("exclude_schemas wins", () => {
      tracker = loadTracker({
        enabled: true, exclude_schemas: ["objects"], include_schemas: ["objects"],
      });
      emit("objects", "shape_add", { shape: "bbox" });
      expect(tracker.sessions.objects).toBeUndefined();
    });

    test("a non-empty include_schemas is a whitelist", () => {
      tracker = loadTracker({ enabled: true, include_schemas: ["objects"] });
      emit("objects", "shape_add", { shape: "bbox" });
      emit("other", "shape_add", { shape: "bbox" });
      expect(tracker.sessions.objects).toBeDefined();
      expect(tracker.sessions.other).toBeUndefined();
    });

    test("an empty include_schemas tracks everything", () => {
      emit("a", "undo", {});
      emit("b", "undo", {});
      expect(Object.keys(tracker.sessions).sort()).toEqual(["a", "b"]);
    });
  });

  // -----------------------------------------------------------------
  describe("disabled states", () => {
    test("enabled false attaches no listener", () => {
      tracker = loadTracker({ enabled: false });
      emit("objects", "shape_add", { shape: "bbox" });
      expect(Object.keys(tracker.sessions)).toHaveLength(0);
    });

    test("fidelity off attaches no listener", () => {
      tracker = loadTracker({ enabled: true, fidelity: "off" });
      emit("objects", "shape_add", { shape: "bbox" });
      expect(Object.keys(tracker.sessions)).toHaveLength(0);
    });

    test("absent config means off", () => {
      tracker = loadTracker(undefined);
      emit("objects", "shape_add", { shape: "bbox" });
      expect(Object.keys(tracker.sessions)).toHaveLength(0);
    });
  });

  // -----------------------------------------------------------------
  describe("sessions and flushing", () => {
    test("one session per schema", () => {
      emit("a", "shape_add", { shape: "bbox" });
      emit("b", "shape_add", { shape: "bbox" });
      emit("a", "undo", {});
      expect(tracker.sessions.a.events).toHaveLength(2);
      expect(tracker.sessions.b.events).toHaveLength(1);
    });

    test("flush posts ended sessions and empties the queue", () => {
      emit("objects", "shape_add", { shape: "bbox", value: 4 });
      tracker.endAllSessions("test");
      tracker.flush(false);

      expect(sent).toHaveLength(1);
      expect(sent[0].url).toBe("/api/track_annotation_telemetry");
      expect(sent[0].body.sessions[0].schema_name).toBe("objects");
      expect(sent[0].body.sessions[0].events).toHaveLength(1);

      tracker.flush(false);
      expect(sent).toHaveLength(1);
    });

    test("an open session is not sent until it ends", () => {
      emit("objects", "shape_add", { shape: "bbox" });
      tracker.flush(false);
      expect(sent).toHaveLength(0);
    });

    test("a session with no events is dropped rather than posted", () => {
      // Opening an image and moving on is not a row.
      tracker._session("objects");
      tracker.endAllSessions("test");
      tracker.flush(false);
      expect(sent).toHaveLength(0);
    });

    test("timestamps are seconds on the wire", () => {
      emit("objects", "shape_add", { shape: "bbox" });
      tracker.endAllSessions("test");
      tracker.flush(false);
      const s = sent[0].body.sessions[0];
      // Milliseconds would be ~1e12; seconds are ~1e9.
      expect(s.started_at).toBeLessThan(1e11);
      expect(s.ended_at).toBeGreaterThanOrEqual(s.started_at);
    });

    test("the periodic timer flushes without being told", () => {
      emit("objects", "shape_add", { shape: "bbox" });
      tracker.endAllSessions("test");
      jest.advanceTimersByTime(10000);
      expect(sent).toHaveLength(1);
    });

    test("the event buffer is capped and the truncation is recorded", () => {
      tracker.maxEventsPerSession = 3;
      for (let i = 0; i < 10; i++) emit("objects", "undo", {});
      expect(tracker.sessions.objects.events).toHaveLength(3);
      expect(tracker.sessions.objects.truncated).toBe(true);

      tracker.endAllSessions("test");
      tracker.flush(false);
      expect(sent[0].body.sessions[0].truncated).toBe(true);
    });
  });

  // -----------------------------------------------------------------
  describe("instance boundary", () => {
    function withInteractionTracker(initialId) {
      window.interactionTracker = {
        currentInstanceId: initialId,
        setInstanceId(id) { this.currentInstanceId = id; },
      };
      return loadTracker({ enabled: true, fidelity: "events" });
    }

    test("navigation ends the open session before the id changes", () => {
      tracker = withInteractionTracker("img_1");
      emit("objects", "shape_add", { shape: "bbox" });

      window.interactionTracker.setInstanceId("img_2");

      // The work done on img_1 must be attributed to img_1, not to img_2.
      expect(sent).toHaveLength(1);
      expect(sent[0].body.sessions[0].instance_id).toBe("img_1");
    });

    test("work after navigation is attributed to the new instance", () => {
      tracker = withInteractionTracker("img_1");
      window.interactionTracker.setInstanceId("img_2");
      emit("objects", "shape_add", { shape: "bbox" });
      tracker.endAllSessions("test");
      tracker.flush(false);

      const last = sent[sent.length - 1].body.sessions[0];
      expect(last.instance_id).toBe("img_2");
    });

    test("the instance id is captured at session start, not at flush", () => {
      tracker = withInteractionTracker("img_1");
      emit("objects", "shape_add", { shape: "bbox" });
      // Simulate an id change that bypassed the hook entirely.
      tracker.currentInstanceId = "img_9";
      tracker.endAllSessions("test");
      tracker.flush(false);
      expect(sent[0].body.sessions[0].instance_id).toBe("img_1");
    });

    test("the original setInstanceId still runs", () => {
      tracker = withInteractionTracker("img_1");
      window.interactionTracker.setInstanceId("img_2");
      expect(window.interactionTracker.currentInstanceId).toBe("img_2");
    });

    test("hooking is idempotent across reloads", () => {
      tracker = withInteractionTracker("img_1");
      const hookedOnce = window.interactionTracker.setInstanceId;
      loadTracker({ enabled: true, fidelity: "events" });
      expect(window.interactionTracker.setInstanceId).toBe(hookedOnce);
    });
  });

  // -----------------------------------------------------------------
  describe("unload", () => {
    test("a final flush closes open sessions and uses sendBeacon", () => {
      const beacon = jest.fn();
      navigator.sendBeacon = beacon;

      emit("objects", "shape_add", { shape: "bbox" });
      tracker.flush(true);

      expect(beacon).toHaveBeenCalledTimes(1);
      expect(beacon.mock.calls[0][0]).toBe("/api/track_annotation_telemetry");
      // fetch would be cancelled by the unload; the beacon is the only
      // transport that survives it.
      expect(global.fetch).not.toHaveBeenCalled();
    });

    test("destroy stops the timer and flushes", () => {
      navigator.sendBeacon = jest.fn();
      emit("objects", "shape_add", { shape: "bbox" });
      tracker.destroy();
      expect(navigator.sendBeacon).toHaveBeenCalledTimes(1);
    });
  });
});
