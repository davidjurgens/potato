# Live Collaborative Sessions

A live session lets a team annotate the same items at the same time and keep
one shared answer for each item. Everyone works on the ordinary annotation
page, so every display type and annotation scheme is available. A change one
member makes shows up on the other members' pages within about a second, and a
side panel records who changed what.

Sessions are different from [Multiplayer Rooms](multiplayer_rooms.md). A room
is a blind vote on one radio or likert scheme, followed by a reveal. A session
is joint work on the whole answer: labels, spans, boxes, free text.

## Shared answers, following and merging

- **One answer per item, owned by the team.** Each session stores its answers
  under a team user named `team-<id>` (for example `team-red`). Exports,
  agreement statistics and adjudication see the team as a single annotator.
  The session log keeps the name of the member behind each change.
- **Members keep their own place.** Each member is on their own item within the
  session. In *follow* mode, members go wherever the leader goes until they
  move on their own; a button in the session bar takes them back to the
  leader's item. In *free* mode there is no leader and everyone moves
  independently.
- **Saves are merged into the team's answer.** A page saves its whole answer for the
  item. The server compares that answer with the version the member's page was
  showing and keeps only what the member changed, laid over the team's current
  answer. Two members editing different parts of an item (a radio and a text
  box, two different spans, two checkboxes) both keep their changes.
- **Drawings merge shape by shape.** On image, audio, video, tiered and the
  other drawing schemes, each box, segment or keyframe is merged separately.
  Two members drawing on the same image at once both keep their shapes. When
  both change one shape, the merge goes field by field: one member moving a
  box and the other relabelling it keeps both changes. Records without an id
  that belong to one step, turn or frame (a rating per agent step, say) are
  matched by that step, turn or frame.
- **When two people change the same thing**, the later save wins. The member
  whose change was replaced is told, by name, and can undo the other person's
  change with one click. With `conflict_policy: reject` the teammate's value
  stays instead: only that value is refused, the rest of the save goes in,
  and the member's page shows what the teammate chose.

## Configuration

```yaml
collab:
  enabled: true
  who_can_create: any          # "any" signed-in user, or "admin" only
  max_members: 8               # per lobby session, 2-50
  default_mode: follow         # follow | free
  conflict_policy: lww         # lww: the later save wins; reject: the earlier value stays
  require_signoff: false       # an item is done when every member marked it ready
  blind_first: false           # members answer on their own before the team answer
  sync_view: true              # followers' scroll and playback follow the leader
  exclude_members_from_solo: true
  transport: poll              # poll | sse
  poll_interval_ms: 1000       # visible tab
  hidden_poll_interval_ms: 5000
  sse:
    max_streams: 3
    max_stream_seconds: 25
  max_items: 500               # per session
  teams:
    - id: red
      name: Team Red
      members: [ana, ben, chen]
      leader: ana
      items: [cs01, cs02, cs03]   # or {count: 20}, or {group: <batch group>}
      blind_first: true           # optional, per team
      require_signoff: true       # optional, per team
```

| Key | Default | What it does |
|-----|---------|--------------|
| `enabled` | `false` | Registers `/collab` and sets up the configured teams at startup. |
| `who_can_create` | `any` | Who can start a session from the lobby. |
| `max_members` | `8` | Members allowed in one lobby session. Configured teams are not capped. |
| `default_mode` | `follow` | Mode for new sessions. The leader can switch it in the session panel. |
| `conflict_policy` | `lww` | `lww`: the later of two saves that change the same thing wins, and the other member is told. `reject`: the earlier value stays; the later save's other changes still go in, and its member is shown the teammate's value. |
| `require_signoff` | `false` | An item counts as done only when every active member has marked it **Ready**. Any later change to the item clears the marks. |
| `blind_first` | `false` | Members answer each item on their own before the team's answer opens. See [Answering on your own first](#answering-on-your-own-first). |
| `sync_view` | `true` | In follow mode, followers on the leader's item also follow the leader's scroll position and audio or video playback. |
| `exclude_members_from_solo` | `true` | Keeps a team's items out of its members' own queues, so one person does not give a solo answer and a team answer for the same item. |
| `transport` | `poll` | `poll`: pages ask for new events on a timer. `sse`: the server pushes them over an open connection. |
| `poll_interval_ms` | `1000` | Poll interval for a visible tab (250-30000). |
| `hidden_poll_interval_ms` | `5000` | Poll interval for a tab in the background. |
| `sse.max_streams` | `3` | Open push connections allowed at once. Beyond this, pages fall back to polling. |
| `sse.max_stream_seconds` | `25` | How long one push connection stays open before the browser reopens it. |
| `max_items` | `500` | Most items one session can hold. |
| `teams` | `[]` | Teams the study sets up. See below. A team can set its own `blind_first` and `require_signoff`. |

### Configured teams and lobby sessions

There are two ways to form a session:

- **Configured teams** (`collab.teams`). Each entry becomes a session when the
  server starts, with the listed members and items. Its code is the team id in
  capitals (`RED` for `id: red`), and the session page is `/collab/s/RED`.
  Only listed members can join, and the session appears in the lobby for them
  alone. A username may appear in only one team.
- **Lobby sessions.** Any signed-in user (or only admins, with
  `who_can_create: admin`) can start a session at `/collab/`, choosing a name,
  the items (the first *N*, or a list of ids) and the mode. Others join from
  the lobby. The creator leads in follow mode.

`items` for a configured team takes a list of ids, `{count: N}` for the first
*N* items of the dataset, or `{group: name}` for the items of a
`batch_assignment` group. Attention-check and gold items are never part of a
session. They grade a person, and a team's saves are not graded. Naming one in
`items` is refused, and `{count: N}` or "the first N" leaves them out.

The lobby form has two more choices: answering on your own first, and
requiring everyone to mark an item ready.

The `collab` block is refused together with `text_as_image`, because
teammates' changes are shown on the page as text.

## The session page

Open **Live sessions** in the navigation bar, then **Open** (your team) or
**Join** (a lobby session). The session page is the normal annotation page with
two additions.

**The session bar**, above the item, shows:

- the session name and your position ("Item 2 of 5");
- whom you are following, or "You are leading";
- the initials of everyone else on this item;
- **Go to ana's item** when you have moved away from the leader;
- **Bring the team here** (leader, or anyone in free mode), which asks everyone
  to come to the item you are on;
- **Session panel**, which opens the side panel;
- with sign-off on, **Mark ready** and how many have marked the item;
- in a blind-first session, **I'm done with my answer** and, for the leader,
  **Reveal now**.

When a teammate is working in a scheme on your item, a small "ana is editing"
tag appears on that scheme's border.

**The session panel** has four tabs. Use the arrow keys to move between them.

| Tab | What it shows |
|-----|---------------|
| Activity | Every change to this item, newest first: who, when, and what ("stance: neutral → critical", "added span ORG 'Northwind Foods'", "added bbox person (objects)"). **Undo** puts back what that change replaced. Switch to *All items* to see the whole session. |
| Team | Members, their role, which item they are on, which scheme they are editing, and whether they are online. The leader can hand over the lead and switch between follow and free mode. Team chat is here too, and so are **Ask the team (quick poll)** and the switch for following the leader's scrolling and playback. |
| My notes | Notes about this item that only you can see. Other members, adjudicators and admins cannot open them in the interface. They are stored in the project database (`project.sqlite`) like other notes. |
| Discussion | Comments about this item that everyone on the team can see. |

**Replay this item's history**, under Activity, opens a page that steps
through every change to the item. Chat, polls and sign-offs appear in order
between the changes, alongside the team's answer at each point.

Next and Previous move within the session's items. Keyboard shortcuts work as
on any annotation page.

### Mentions

Type `@name` in chat or in a Discussion comment to mention a teammate (any
capitalisation). They get a notice with a link to the chat or the item, even
if they are on another item.

### Quick polls

**Ask the team** in the Team tab starts a poll on the item you are on. A poll
can be about a single-choice scheme (its options are the scheme's labels) or
a question of your own with up to ten options. Everyone sees the poll above
the item. Members see who has voted, but not what, until the poll closes. It
closes on the last vote, or when whoever opened it (or the leader) closes it.
For a scheme poll, **Use** sets the winning option as the team's answer, and
the change is logged like any other.

### Answering on your own first

With `blind_first: true`, each item starts in a private stage. Each member
answers on their own; nobody sees anyone else's answer, and the team's answer
stays empty. **I'm done with my answer** hands it in, and the item opens to
the team once every member has handed in. The leader can open it earlier with
**Reveal now**.

When an item opens:

- A table above the item shows each member's answer, question by question,
  marked **Agreed** or with **Ask the team** (a quick poll) where they differ.
- Questions everyone answered the same way start the team's answer. The rest
  is for the team to settle.
- Each member's own answer stays under their own name. These answers are the
  pre-discussion record, and they show up in exports as each member's own
  annotation.

The reveal records how often the members agreed before they discussed the
item, and the admin page shows how much of each member's own answer the team
kept.

### Sign-off

With `require_signoff: true`, an item is done when every active member has
marked it **Ready**. A mark is for the answer as it stood when it was given,
so any later change clears everyone's marks. **Jump to unannotated** goes to
the next item that is not signed off. The export records who signed and
whether everyone did.

### Following the leader's view

In follow mode, a follower on the leader's item also follows the leader's
scroll position and the playhead of audio and video on the page (to within
about a second). Scrolling or playing on your own pauses this for 15 seconds.
The switch in the Team tab turns it off.

### Time away and dropped connections

When you come back to a session (a new page load, or a tab that was hidden
for over a minute), a notice sums up what others did meanwhile, for example
"5 changes by ana, 2 by ben · 3 messages", with a link to the activity.

A save that fails because the network dropped is kept in the browser and sent
again when the connection returns. A banner says how many are waiting. The
save still names the revision it was made on, so the server merges it like
any late save.

Restarting the server signs everyone out. An open session page then says so
("You are signed out, so this page no longer updates or saves") with a
**Sign in again** button, and keeps any change it could not save. The change
is sent when you open the session again after signing in.

## Schemes that update without a reload

Every scheme saves to the team's answer. Most also show a teammate's change on
your page at once; the rest need a reload:

| Kind of scheme | On teammates' pages |
|----------------|---------------------|
| Radio, checkbox, likert, select, slider, text and number boxes, and the other schemes built on them | At once. |
| Ranking, hierarchical multiselect, pairwise, best-worst scaling, text edit, extractive QA, error spans, trajectory evaluation and editing | At once. A teammate clearing one of these shows after a reload. |
| Text spans, span links, coreference chains, events | At once: the span, link and event layers reload. |
| Image, audio, video (segments, keyframes, tracks), tiered (ELAN-style), spectrogram boxes, interval labels | At once: the teammate's shapes, segments or tiers are redrawn. |
| Point clouds, CT/MRI volumes, microscopy, maps, PDF and document boxes | At once. |
| Agent traces and evaluation: scorecards, tool-call review, GUI trajectories, handoffs, process reward, code review, interaction graphs, consensus, failure attribution, emergent behaviour, multimodal reasoning, speech and voice transcripts, table grids, temporal grounding, tool contention, episodes, rollouts, grounding, region captions, per-turn ratings | At once. |
| Survey and elicitation schemes (price lists, BDM, belief elicitation, free lists, triads, listening tests), interlinear glosses, conversation trees, ego networks, chemical structures, spectrum peaks, viewer selections, multi-document events, triage | At once. |
| Card sorting, audio-dialogue speaker overrides, and schemes not listed here | A banner says a teammate changed something, with **Reload this item**. The page reloads by itself after about 8 seconds without input. Until then, your page does not undo the teammate's change: the merge compares your save with the version your page still shows. |

Changes you have not saved yet are never overwritten. A teammate's change is
put on your page after your own pending save has gone through. A shape you are
in the middle of drawing or dragging when a teammate's change arrives is
dropped; the shape you had selected stays selected if it still exists.

### Adding live updates to a custom scheme

If a scheme's widget keeps its own copy of the answer, register a function
that shows a teammate's answer in it:

```javascript
window.potatoCollabWidgets = window.potatoCollabWidgets || {};
window.potatoCollabWidgets['my_scheme_type'] = {
    apply(ctx) {
        // ctx.schema, ctx.form, ctx.value (the `_data` JSON or null),
        // ctx.labels (the scheme's whole answer, or null). The hidden inputs
        // already hold the new answer. Replace what the widget shows, without
        // saving; return true once it is on screen.
        return true;
    },
};
```

Without one, the scheme gets the reload banner. Give each new element an id
(`id`, `_id` or `uid`) that no other page will make, such as a random part
plus a counter, so the server can merge two members' additions. Elements
without ids are matched by their step, turn or frame if they have one, and
otherwise by content.

## Data, exports and the session log

- The team user (`team-red`) is the annotator of record. In the CSV/TSV export
  its rows carry `_collab_session` and `_collab`, a JSON record of the session
  and how many changes each member made to that item. JSON exports carry the
  same record as `_collab`.
- Members have no annotations of their own for team items, except their own
  answers in a blind-first session (see above). With
  `exclude_members_from_solo: true`, team items never appear in their own
  queues.
- A team holds its items for its own members only. Annotators outside the
  team can still be given the same items by ordinary assignment and answer
  them on their own. That is how a study compares a team's answer with
  individual ones. To keep team items to the team, keep them out of the solo
  pool, for example in a `batch_assignment` group no one else is given.
- With sign-off or blind-first on, the `_collab` record in the export also
  carries `signed_off_by`, `consensus` and the pre-discussion `blind`
  agreement.
- The session log is `<output_annotation_dir>/collab/session-<CODE>.jsonl`: one
  JSON event per line (joins, moves, chat, and every edit with its before and
  after values). Sessions are rebuilt from it when the server restarts.
- Quality-control checks (attention checks, gold items) do not grade team
  saves: they measure a person, and a team answer is not one person's.
- Personal notes (My notes) are hidden from other members, adjudicators and
  admins in the interface, but the admin data archive includes them.

## Limits

- **One server process.** Sessions live in the server's memory, like the rest
  of Potato's state. Run a single worker (the Docker image does this unless
  `POTATO_ALLOW_MULTIWORKER=1` is set).
- **Server push holds a thread.** With `transport: sse`, every open connection
  occupies one of the server's threads (eight by default under gunicorn).
  Polling does not, which is why it is the default.
- **Off on session pages:** AI suggestions, the chat assistant, the agent
  proxy, Boundary Lab, Truth Serum, Think-Aloud and timed trials. Each keeps
  per-person state that does not yet know about team answers.
- **Shapes merge by id.** Shapes, segments, keyframes, tracks, regions, map
  features, phases and marks made on a session page get an id with a random
  part, so two members' new shapes never share one. An image shape saved
  before ids existed gets an id from its content when a page loads it, the
  same on every page; the first save after that is logged as "shape ids
  added, nothing moved".
- **Elements without ids** (painted point-cloud segments, records saved by
  older pages) are matched by their step, turn or frame, or else by content.
  A content-matched element that moves reads as one removed and one added.
  That merges correctly unless two members change the same element at once,
  in which case both versions remain. Two members painting the same label's
  brush mask are editing one element, and the later save wins.
- **One trajectory scheme per page.** Trajectory evaluation and trajectory
  editing update live only when a page has one scheme of that type.
- **Pre-filled spectrogram boxes after a clear.** A spectrogram scheme that
  pre-fills boxes on unanswered items shows them again when a teammate clears
  the answer, but only on pages that opened the item unanswered. A page that
  opened it already answered never had the pre-filled boxes, so it shows the
  item empty until you reload.
- **Signing in again after a restart.** Logins are held in memory, so a server
  restart signs everyone out. Sessions, answers and history survive.

## Watching sessions (admins)

`/collab/admin` lists every session with progress, conflicts, agreement before
discussion, and per member: edits, how often they replaced a teammate's value
or had theirs replaced, undos, messages, ready marks, how much of their own
blind answer the team kept, and time on items. **Watch** joins a session as a
read-only observer, configured teams included: you see the pages and panel
as members do, cannot change anything, and are listed as an observer.
**Replay** opens the history page.

## Troubleshooting

**"Finish the study's opening pages"** when answering on your own. Your own
answers are stored like any annotation, and Potato files them under an item
only once you are past consent and instructions. Open `/annotate` once, then
return to the session.

**"Not saved: ana changed this first"** or **"Partly saved: ..."** with
`conflict_policy: reject`. A teammate saved a different value for the same
thing after your page loaded. Your page now shows their value, and anything
else you changed in that save was kept. Change the value again if you still
disagree: the page now counts it as your own change, and it goes in.

**"This item belongs to your team's live session"** when saving. A save for a
team item arrived without the session, usually from a page opened at
`/annotate?instance_id=...`. Open the item from the session page
(`/collab/s/<CODE>`).

**A member's page keeps showing the reload banner.** Their page holds a
scheme that cannot update live (card sorting, audio-dialogue speaker
overrides, or a custom scheme without a live update; see the table above).
Click **Reload this item**, or stop interacting for a few seconds.

**The lobby does not list my team.** Configured teams are listed only to their
members. Check the spelling of the username in `collab.teams[].members`.

**`/collab` returns 404.** `collab.enabled` is not `true`, or the block failed
validation; `potato validate config.yaml` names the problem.

## Example

`examples/advanced/collaborative-sessions/` has a news-framing task with a
radio, a multiselect, spans and a text box, and a configured team "red" (ana,
ben, chen, led by ana). Sign-in needs only a username.

```bash
python potato/flask_server.py start examples/advanced/collaborative-sessions/config.yaml -p 8000
```

Sign in as `ana` in one browser and as `ben` in another (or in a private
window), then open **Live sessions**.

## Related

- [Multiplayer Rooms](multiplayer_rooms.md): blind-vote norming, adjudication
  huddles, shadowing
- [Memos](memos.md): the notes store behind My notes and Discussion
- [Adjudication](../administration/adjudication.md)
- [Task assignment](task_assignment.md)
