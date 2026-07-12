# Pocket Mode: Mobile-First Annotation (PWA)

Not every schema belongs on a phone — span surgery and bounding boxes are desktop
tasks. But the high-volume classification workhorses map beautifully to touch. Pocket
Mode is a separate mobile-first surface at **`/pocket`**: a card stack with thumb-zone
label buttons, swipe navigation, haptic feedback, **offline annotation** with automatic
sync, and home-screen installation as a PWA.

For single-radio tasks, one tap = one labeled item: tap a label, it saves and the next
card slides in.

## Supported schema types

| Touch-capable (served by /pocket) | Desktop-only (politely redirected) |
|---|---|
| radio, multiselect, likert, slider, number, text/textbox, pure_display | span, image/bbox, video, audio, multirate, and everything else |

A task mixing in a desktop-only scheme isn't degraded onto touch — `/pocket` explains
and points to `/annotate`.

## Quick start

```bash
python potato/flask_server.py start examples/advanced/pocket-mode/config.yaml -p 8000 --debug
# then open http://<your-machine>:8000/pocket on a phone (log in first on real deployments)
```

## Configuration

```yaml
pocket:
  enabled: true
  batch_size: 25   # items prefetched per batch (also the offline queue depth)
```

## Offline behavior

- The app shell (page, JS, CSS, icon) is cached by a service worker after the first
  visit, so `/pocket` loads with no connection.
- A batch of items is prefetched and mirrored to localStorage.
- Saves go into a local queue when offline (a chip shows *"Offline — N saves
  queued"*) and flush automatically on reconnect and after every successful save.
- Saves use the **same `/updateinstance` endpoint and payload as the desktop page** —
  Pocket Mode adds no new write path, so all downstream machinery (exports, IAA,
  admin dashboard, quality control) sees ordinary annotations.

Field-research note: prefetch a batch on wifi, annotate anywhere, sync when back in
coverage.

## Endpoints

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/pocket` | GET | session (redirects to login) | The mobile page |
| `/pocket/api/task` | GET | session | Task name, schema specs, capability verdict |
| `/pocket/api/batch?n=` | GET | session | Next unannotated items for the card stack |
| `/pocket/manifest.webmanifest` | GET | — | PWA manifest |
| `/pocket/sw.js` | GET | — | Service worker (served under /pocket for scope) |

## Design notes

- Gestures: swipe left = skip/next, swipe right = previous; arrow buttons cover
  non-touch use. All touch targets are 48px+; safe-area insets respected on notched
  phones; `prefers-reduced-motion` honored.
- Likert schemes with explicit `labels` render as labeled buttons; size-based likert
  renders numbered segments (values stored as `scale_<n>`).
- Multi-scheme tasks show all controls per card with an explicit **Save & next**;
  single radio/likert tasks auto-advance on tap.

## Related documentation

- [Task Assignment](task_assignment.md) — what lands in an annotator's queue
- [Crowdsourcing](../deployment/crowdsourcing.md) — mobile-heavy crowd platforms
