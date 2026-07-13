# Mobile Annotation (Pocket Mode)

Potato supports annotating from phones and tablets. Enable Pocket Mode and
touch devices that open your task are **automatically routed** to a
mobile-friendly interface: a card stack with thumb-zone label buttons, swipe
navigation, offline annotation with automatic sync, and home-screen
installation as a PWA. Desktop users see the normal interface; nothing
changes for them.

Not every annotation type belongs on a phone — span highlighting and bounding
boxes are desktop tasks. Potato is explicit about this: touch-capable tasks
get the mobile interface, tasks that aren't get a clear warning instead of a
degraded UI, and the admin dashboard shows who is annotating from which kind
of device either way.

## Quick start

```yaml
pocket:
  enabled: true
```

```bash
python potato/flask_server.py start examples/advanced/pocket-mode/config.yaml -p 8000
# open http://<your-machine>:8000/ on a phone and log in —
# you land in the mobile interface automatically
```

## How device routing works

When a logged-in annotator reaches the annotation page, Potato decides where
to send them:

| Device | Task touch-capable, pocket enabled | Task NOT touch-capable |
|---|---|---|
| Desktop | normal interface | normal interface |
| Phone / tablet | **redirected to the mobile interface** | normal interface + a dismissible warning that a desktop browser is recommended |

Detection happens in two layers:

1. **Server-side (User-Agent).** Phones and most tablets identify themselves
   (`iPhone`, `Android ... Mobile`, `iPad`, ...). These are redirected before
   the desktop page ever renders. API clients and unrecognized agents count
   as desktop, so scripts and integrations are never redirected.
2. **Client-side (pointer check).** Some tablets masquerade as desktops —
   iPadOS Safari reports itself as a Mac. A small script on the annotation
   page checks whether the device's *primary* pointer is coarse (a finger)
   and redirects those too. Touchscreen laptops are not affected: their
   primary pointer is the trackpad.

Routing only applies to annotators in the annotation phase. Consent,
instruction, and survey pages are unaffected.

### Letting users opt out

The mobile interface has a **Desktop site** link in its header. Choosing it
loads the desktop interface (`/annotate?desktop=1`) and the choice sticks for
the rest of the session — one quiet banner offers the way back, and there are
no further redirects. Opening `/pocket` again clears the choice.

### Turning auto-routing off

Auto-routing is on whenever Pocket Mode is enabled. To offer `/pocket` only
to users who navigate there themselves:

```yaml
pocket:
  enabled: true
  auto_redirect: false
```

## Configuration reference

```yaml
pocket:
  enabled: true        # master switch for the mobile interface (default: false)
  auto_redirect: true  # send phones/tablets to /pocket automatically (default: true)
  batch_size: 25       # items fetched per batch; also the offline queue depth (1-200)
```

## Which annotation types are mobile friendly

The mobile interface serves schema types that work well under a thumb:

| Touch-capable (served on mobile) | Desktop-only |
|---|---|
| `radio`, `multiselect`, `likert`, `slider`, `number`, `text`/`textbox`, `pure_display` | `span`, image/bounding-box, video, audio, `multirate`, and everything else |

A task is touch-capable only if **all** of its schemes are in the left
column. A task mixing in even one desktop-only scheme is not degraded onto
touch: phones are not redirected, and they see a dismissible notice that the
task isn't optimized for mobile. If you expect mobile annotators, design for
it — a single-radio task is the ideal case (one tap = one labeled item).

## The mobile interface

- **Card stack** — one item per card; the item text is the card. Swipe left =
  next, swipe right = previous; arrow buttons cover non-touch use. A subtle
  haptic tick confirms each save on devices that support it.
- **Thumb-zone controls** — label buttons sit in the bottom third of the
  screen where a thumb actually reaches; all touch targets are 48px+;
  safe-area insets respected on notched phones; `prefers-reduced-motion`
  honored.
- **Scheme rendering** — single radio/likert tasks auto-advance on tap;
  multi-scheme cards show every control plus an explicit **Save & next**.
  Likert schemes with explicit `labels` render as labeled buttons;
  size-based likert renders numbered segments (stored as `scale_<n>`).
- **Progress** — the header shows done/total and a progress bar, matching
  the desktop count.
- **Offline annotation** — the current batch is prefetched and mirrored to
  localStorage. If the connection drops, annotating continues; a chip shows
  *"Offline — N saves queued"* and the queue flushes automatically on
  reconnect and after every successful save. A service worker caches the app
  shell after the first visit, so the page loads with no connection.
  Field-research note: prefetch a batch on wifi, annotate anywhere, sync when
  back in coverage.
- **Install as an app** — the page ships a web manifest; "Add to Home
  Screen" gives a standalone app with its own icon.

Saves use the **same `/updateinstance` endpoint and payload as the desktop
page** — Pocket Mode adds no new write path, so all downstream machinery
(exports, IAA, admin dashboard, quality control) sees ordinary annotations.

## Admin: who is annotating from what

The admin dashboard has a **Devices** tab showing, per annotator: last device
seen, visit counts by device class (mobile / tablet / desktop), how many
times they used the mobile interface, and when they were last seen. Users who
have annotated from a touch device are highlighted, and a summary line gives
the headline ("3 of 12 users have visited from a phone or tablet"). The tab
also states the routing situation for this task — auto-routing active, task
capable but Pocket disabled, or task not mobile friendly.

Why this matters: if your task is *not* touch-capable and the Devices tab
shows annotators on phones anyway, those annotators saw the warning and kept
going — worth checking their output or following up. Device data also
answers "would enabling Pocket Mode help?" before you turn it on: **visits
are tracked whether or not Pocket Mode is enabled.**

Data lives in `<output_annotation_dir>/pocket/device_visits.json` — per-user
aggregates only (device class, counts, timestamps, last User-Agent string),
no per-item tracking.

## API reference

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/pocket` | GET | session (redirects to login) | The mobile page |
| `/pocket/api/task` | GET | session | Task name, schema specs, capability verdict |
| `/pocket/api/batch?n=` | GET | session | Next unannotated items for the card stack |
| `/pocket/api/routing` | GET | session | Routing facts (works even when Pocket is disabled) |
| `/pocket/api/device_hint` | POST | session | Client-side touch detection report |
| `/pocket/api/devices` | GET | admin | Per-annotator device usage for the dashboard |
| `/pocket/manifest.webmanifest` | GET | — | PWA manifest |
| `/pocket/sw.js` | GET | — | Service worker (served under /pocket for scope) |

## Troubleshooting

**A phone isn't being redirected.** Check, in order: `pocket.enabled` and
`pocket.auto_redirect` are true; the task is touch-capable (`GET
/pocket/api/routing` shows `capable: true` and lists any
`incompatible_schemes`); the user hasn't chosen "Desktop site" this session
(opening `/pocket` once resets it).

**An iPad gets the desktop page on first load.** iPadOS Safari identifies
itself as a Mac, so the server can't catch it — the client-side pointer check
redirects it as soon as the page's scripts run. If scripts are blocked, use
the `/pocket` URL directly.

**A desktop user with a touchscreen got redirected.** They shouldn't be: the
check uses the *primary* pointer, which is the trackpad/mouse on touchscreen
laptops. If it happens anyway, the "Desktop site" link opts them out for the
session; please report the device's User-Agent.

**A user is "done" on mobile but the desktop page shows remaining items.**
They may have unsynced offline saves — the sync chip on the mobile page shows
the queue; it flushes when the device comes back online.

**Testing the redirect without a phone.** Use your browser's device emulation
(a phone profile sends a mobile User-Agent), or
`curl -H "User-Agent: ...iPhone..." -i http://localhost:8000/annotate` and
look for the 302.

## Related documentation

- [Task Assignment](task_assignment.md) — what lands in an annotator's queue
  (mobile users draw from the same queue as everyone else)
- [Admin Dashboard](../administration/admin_dashboard.md) — where the Devices
  tab lives
- [Crowdsourcing](../deployment/crowdsourcing.md) — mobile-heavy crowd platforms
