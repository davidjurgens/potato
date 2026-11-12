/**
 * Jest tests for interaction_tracker.js with `interaction_tracking.enabled: false`.
 *
 * Off means no ambient stream (clicks, focus, keys), but time per item must
 * survive: BehavioralData.active_time_ms() is built from the gaps between
 * events, and the throughput, adjudication and dashboard timings read it.
 * So item loads, saves, navigation and a throttled, content-free `activity`
 * mark are still posted.
 */

const fs = require("fs");
const path = require("path");

const SOURCE = fs.readFileSync(
  path.join(__dirname, "../../potato/static/interaction_tracker.js"),
  "utf8"
);

function loadTracker(config) {
  window.interactionTrackingConfig = config;
  // eslint-disable-next-line no-eval
  eval(SOURCE);
  return window.interactionTracker;
}

function postedEvents() {
  return global.fetch.mock.calls
    .filter((c) => c[0] === "/api/track_interactions")
    .flatMap((c) => JSON.parse(c[1].body).events);
}

let now;
beforeEach(() => {
  now = 1_000_000;
  jest.spyOn(Date, "now").mockImplementation(() => now);
  global.fetch = jest.fn(() => Promise.resolve({ ok: true }));
  navigator.sendBeacon = jest.fn(() => true);
  document.body.innerHTML = `<button id="b">Next</button><textarea id="t"></textarea>`;
});
afterEach(() => {
  const t = window.interactionTracker;
  if (t && t.flushTimer) clearInterval(t.flushTimer);
  jest.restoreAllMocks();
});

describe("interaction tracking off", () => {
  test("clicks and keys are not recorded; item load and save are", async () => {
    const t = loadTracker({ enabled: false });
    t.setInstanceId("item_1");
    t.addEvent("click", "nav:next", { x: 1, y: 2 });
    t.trackKeypress(new KeyboardEvent("keydown", { key: "1" }));
    t.trackSave("item_1");
    await t.flush(false);
    const types = postedEvents().map((e) => e.event_type);
    expect(types).toContain("navigation");
    expect(types).toContain("save");
    expect(types).not.toContain("click");
    expect(types).not.toContain("keypress");
  });

  test("input leaves a throttled activity mark with no target or detail", async () => {
    const t = loadTracker({ enabled: false });
    t.setInstanceId("item_1");
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "x" }));
    now += 1000;
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "y" }));
    now += 15000;
    document.getElementById("b").dispatchEvent(new Event("pointerdown", { bubbles: true }));
    await t.flush(false);
    const activity = postedEvents().filter((e) => e.event_type === "activity");
    expect(activity).toHaveLength(2);
    for (const e of activity) {
      expect(e.target).toBe("");
      expect(e.metadata).toEqual({});
    }
    expect(JSON.stringify(postedEvents())).not.toContain('"x"');
  });

  test("tracking on records clicks and no activity marks", async () => {
    const t = loadTracker({ enabled: true });
    t.setInstanceId("item_1");
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "x" }));
    t.addEvent("click", "nav:next", { x: 1, y: 2 });
    await t.flush(false);
    const types = postedEvents().map((e) => e.event_type);
    expect(types).toContain("click");
    expect(types).not.toContain("activity");
  });
});
