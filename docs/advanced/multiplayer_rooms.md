# Multiplayer Rooms

Multiplayer Rooms turn annotation from a solitary task into a live, shared
session. A group of annotators works on the *same item at the same time* —
with the social dynamics **measured**, not just enabled. No LLM, no external
services, no new dependencies.

Three room types:

| Type | What happens |
|------|--------------|
| **Norming** | Everyone votes blind → the host reveals → the group discusses → anyone may change their vote. A live agreement meter shows *blind α* vs *after-discussion α*. |
| **Huddle** | Walks the items your team currently disagrees on, with everyone's original annotations shown as context — a live adjudication session. |
| **Shadow** | Trainees join as observers and watch the host annotate in real time, including which part of the text the host highlights. |

## Why norming rooms

Annotation teams routinely run "norming" or "calibration" meetings — over
screen-share, with the results living in someone's notes. Rooms make the
session part of the tool and instrument it:

- **Blind first.** Before the reveal, members see *who* has voted but never
  *what* — enforced server-side, so first impressions are genuinely
  independent.
- **The reveal is a measurement.** Blind votes are immutable once revealed.
  Every post-reveal change is logged with what the member switched from, to,
  and what the majority was at that moment — a per-member conformity record.
- **The α meter answers "was this worth it?"** Krippendorff's α computed
  twice over revealed items: on blind votes and on current votes. The gap
  ("norming lift") is the session's value, live on screen.

## Configuration

```yaml
rooms:
  enabled: true
  who_can_create: any      # "any" logged-in user, or "admin" only
  persist_votes: true      # final votes write into members' annotation state
  poll_interval_ms: 1500   # client sync cadence (500–30000)
  max_members: 12          # per room (2–100)
  schema: sarcasm          # optional; defaults to the first radio/likert scheme
```

Rooms vote on one single-choice scheme (radio or likert). If `schema` is not
set, the first such scheme in `annotation_schemes` is used.

## Using rooms

1. Start the server and log in, then open **`/rooms`**.
2. Create a room (type + item count); it gets a six-letter code like
   `MKT4QP`. Codes avoid ambiguous glyphs so you can read them aloud.
3. Others join from the lobby list (or by opening `/rooms/<CODE>`).
4. Vote → the host reveals → discuss in the side chat → change votes if
   convinced → the host advances. After the last item the room closes with a
   session summary, and the host can download the full event log.

### Huddles

Choosing **Huddle** at creation seeds the room with every item where
annotators currently disagree on the room's schema (at most 200). The
original annotations appear above the vote panel as context. Disagreements
are computed live from annotation state — the adjudication subsystem does not
need to be enabled.

### Shadow sessions

In a shadow room, everyone except the host joins as an **observer**:
observers cannot vote, but they see the host's votes, reveals, and text
selections (the host's current selection is highlighted in amber on the
observers' screens) with ~1.5 s latency.

## Persistence and crash recovery

Every room is **event-sourced**: each mutation (join, vote, reveal, change,
message, advance, close) appends one JSON line to

```
<output_annotation_dir>/rooms/room-<CODE>.jsonl
```

Room state is a pure replay of that log, so live rooms survive a server
restart. The log doubles as the session's audit trail: blind votes,
timestamps, discussion, and every post-reveal change with its majority
context. `GET /rooms/api/<CODE>/export` (host or admin) returns the log plus
computed metrics as JSON.

While a room is open, the export is redacted the same way the room page is:
revealed items in full, unrevealed items as voter counts only, and blind
`vote_cast` events with their labels stripped. The host is a voting member, so
an unredacted live export would let one participant read everyone else's
independent judgment before casting their own, and `blind_alpha` is computed as
though that had not happened. Closing the room lifts the redaction, and the
download link only appears on the closed-session screen anyway, so nothing is
withheld from whoever is collecting the data. The payload carries
`redacted: true` while the redaction applies.

With `persist_votes: true` (the default), each member's **final** vote on a
revealed item is written into their regular annotation state when the host
advances — room work counts as real annotations and flows into every
existing export path.

## API summary

| Endpoint | Method | Who |
|----------|--------|-----|
| `/rooms` / `/rooms/<code>` | GET | logged-in (pages) |
| `/rooms/api/list`, `/rooms/api/disagreements` | GET | logged-in |
| `/rooms/api/create` | POST | per `who_can_create` |
| `/rooms/api/<code>/join`, `/leave`, `/vote`, `/message`, `/presence` | POST | members |
| `/rooms/api/<code>/state`, `/events?since=N` | GET | members |
| `/rooms/api/<code>/reveal`, `/advance`, `/close` | POST | host |
| `/rooms/api/<code>/export` | GET | host or admin |

Clients synchronize by polling `/events` with a cursor — no WebSockets, so
rooms work under the threaded dev server and any WSGI deployment alike.

## Example project

```bash
python potato/flask_server.py start examples/advanced/multiplayer-rooms/config.yaml -p 8000
```

Register two users in two browser windows, create a room as one, join as the
other. The example data is fifteen workplace messages whose sarcasm ranges
from blatant to genuinely contestable — good fuel for a discussion.

## Related

- [Adjudication](../administration/adjudication.md) — asynchronous
  disagreement resolution; huddles are its synchronous counterpart.
- [Psychometrics](psychometrics.md) — per-annotator ability and item
  difficulty estimates; rooms are where you *fix* the codebook problems it
  flags.
