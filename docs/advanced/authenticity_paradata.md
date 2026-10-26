# Authenticity Paradata

Potato can record **page-level, content-blind paradata**: signs that an item was
answered somewhere other than on the page, or by something other than a person. It
works on every task type, including Likert scales, radio buttons, spans, rankings and
media. [Keystroke logging](keystroke_logging.md) only covers free-text fields.

This is the same kind of measurement that survey-paradata tools such as ECSP
(Embedded Client Side Paradata, University of Göttingen) and crowdsourcing platforms'
"authenticity checks" collect. The difference is that it is built into the annotation
page and stored with the annotation.

!!! warning "Evidence for review, not proof"
    Every signal here has an ordinary explanation. People leave pages to answer the
    door, copy a phrase to look up a word, and work on small screens. A task that asks
    annotators to consult outside sources will trip the paste and away rules by design.
    Read the per-item evidence before acting on a flag, and never reject work on a
    flag alone.

## What is recorded

For each view of an item (one load of it), the browser keeps running totals and sends
them to the server about every 10 seconds, and again when the page is hidden or the
item changes. **No text is ever sent.** Copied and pasted text is compared against
the page in memory and then discarded.

The server updates its in-memory record on every post. It writes `user_state.json`
for the last post of a view (item change, page hidden), for a post that changes the
item's flags, and otherwise at most once a minute; the next annotation save also
writes it, and so does stopping the server (Ctrl-C or SIGTERM). A crash can lose up to
a minute of paradata, but no annotations.

| Signal | Fields |
|---|---|
| Left the page (tab hidden) | `hidden_events`, `hidden_ms` |
| Window lost focus while visible (another window) | `blur_events`, `blur_ms`, `max_away_ms` |
| Away in a page the task opened (codebook link) | `linked_away_events`, `linked_away_ms` (excluded from flags) |
| Copied the item text | `item_copy_events`, `item_copy_chars` |
| Selected or right-clicked the item text | `item_select_events`, `item_context_menu_events` |
| Other copies and cuts | `other_copy_events`, `cut_events` |
| Pastes | `paste_events`, `item_paste_events` (pasting the item back), `external_paste_events`, `external_paste_words`, `max_external_paste_words` |
| Copy-then-… pairing | `max_away_after_item_copy_ms`, `max_paste_words_after_item_copy`, `copy_away_pairs` (for each absence after an item copy: how soon after the copy it began, how long it lasted, and how many characters the copy held) |
| Window size | `min_window_ratio` (window width ÷ screen width), `large_screen`, `resize_events`, `zoom_changes` |
| Pointer | `pointer_moves` (sampled), `pointer_distance_px`, `mouse_clicks`, `teleport_clicks` |
| Automation | `webdriver`, `untrusted_events` (script-generated pointer/key events) |
| Device | `touch_input` |
| Time | `elapsed_ms` (client), `server_span_ms` (first to last report, measured by the server) |

A paste counts as **external** only when the text is not part of the item, not
something the annotator copied on this page, and not already in one of the page's
text fields.

## Flags

The server merges every view of an item and evaluates these rules. Thresholds live on
the server and are never sent to the page.

| Flag | Fires when (default) | Severity |
|---|---|---|
| `automation` | `navigator.webdriver` is set | suspect |
| `copy_then_paste` | Item copied, then ≥ 10 words of external text pasted | suspect |
| `copy_then_away` | ≥ 40 characters of the item copied, then away from the page ≥ 10 s, leaving within 60 s of the copy (closed-format items: copy, ask elsewhere, come back, click) | suspect |
| `external_paste` | ≥ 10 words of external text pasted, without a preceding item copy | review |
| `item_copied` | ≥ 40 characters of the item copied, with neither of the above | review |
| `away_from_task` | Left the page ≥ 3 times, or away ≥ 60 s and ≥ 50 % of the time on the item | review |
| `split_screen` | Window ≤ 60 % of the screen width on a screen ≥ 1200 px, without touch input | review |
| `pointer_teleport` | ≥ 3 mouse clicks at a new position with no movement in between | review |
| `synthetic_input` | ≥ 3 pointer/key events with `isTrusted = false`. Browser extensions (keyboard navigation, accessibility tools) can produce these | review |

The admin rollup adds **`paradata_missing`**: the annotated items that have no
authenticity record at all. This is what blocked or modified scripts look like. It is
also what every item annotated *before* the feature was switched on looks like, so
read it against the date you enabled it.

### Why these rules

- **Copying the item, then pasting outside text** was the core heuristic for LLM use
  in "A Penny for Your Prompts" (arXiv:2607.00403, 2026). A single copy or paste on
  its own was not diagnostic: 30.7 % of responses had one. That is why `item_copied`
  and `external_paste` are only `review`.
- **Tab switching** was a weak signal on its own in the same study (F1 = .545). It
  ranks low in the risk score.
- **Mouse-click counts and completion time** did not separate LLM users from others in
  that study, so neither is a flag. Pointer data is only used for the teleport check,
  because a physical mouse cannot change position without emitting movement events.
- Potato's own scripts only ever synthesize `input`, `change` and `click` events.
  Script-generated `pointerdown`, `mousedown` or `keydown` events therefore came from
  something else.

## Configuration

```yaml
authenticity:
  enabled: true                # default false
  min_away_ms: 1000            # shorter absences are not counted
  flush_interval_ms: 10000
  track_pointer: true          # false removes the pointermove listener
  disclose_to_annotators: true # show a notice on every page
  disclosure_text: null        # null = the default notice
  detection:
    enabled: true
    thresholds:                # any key from the flag table above
      away_from_task.min_events: 5
      copy_then_away.min_away_ms: 20000

# Write authenticity.<fmt> beside the annotations on export.
export_include_authenticity: true
```

Threshold keys: `copy_then_paste.min_words`, `copy_then_away.min_away_ms`,
`copy_then_away.min_copy_chars`, `copy_then_away.max_gap_ms`,
`external_paste.min_words`, `item_copied.min_chars`, `away_from_task.min_events`,
`away_from_task.min_ms`, `away_from_task.min_fraction`,
`split_screen.max_window_ratio`, `pointer_teleport.min_clicks`,
`synthetic_input.min_events`. An unknown key is a
startup error.

The default notice reads:

> This task records when you leave this page and whether you copy the item or paste
> text from elsewhere — not what you copy or paste.

The notice is rendered by the server, so it appears even if scripts are blocked.

### Recording only in some phases

By default the tracker records on every page, the consent page included. If
consent is the legal basis for the paradata, set `phases` so that the tracker
starts only after consent:

```yaml
authenticity:
  enabled: true
  phases: [annotation]           # phase types or names from phases.order
keystroke_logging:
  enabled: true
  phases: [annotation, poststudy]
interaction_tracking:
  phases: [annotation, poststudy]  # the general tracker is on by default
```

A value is a phase type (`consent`, `prestudy`, `instructions`, `training`,
`annotation`, `poststudy`) or a phase name from `phases.order`. A phase name
selects one page when a study has two pages of the same type. `null` or no
key means every page. On other pages the script is not loaded. The server also
drops a post from another phase and answers 200, because a cached page or an
old tab can still post. One exception: after annotation, a post for one of the
annotator's items still counts as annotation. This post is the final flush of
the last item, which arrives after "next" moved the annotator on. The notice
stays on every page, so the participant can read it before consent. An unknown
value is a startup error that lists the valid values. If `phases` leaves out
`annotation`, the admin panel does not count annotated items as
`paradata_missing`.

The same key exists on `keystroke_logging`, `annotation_telemetry` and
`interaction_tracking`. The general interaction tracker is on by default, so a
study that must record nothing before consent sets `phases` on it too. Outside
its phases, the tracker sends only item loads, saves, navigation and the
`activity` mark, as with `enabled: false`. The server keeps these marks for
items, so time per item stays correct, and keeps nothing for consent and
survey pages. If its `phases` leaves out `annotation`, the admin suspicion
score treats the low-interaction and no-scroll rates as unknown.

### The general interaction tracker

The older, always-on [behavioral tracker](behavioral_tracking.md) (clicks, focus,
scroll, shortcut keys) can now be switched off or announced:

```yaml
interaction_tracking:
  enabled: true                 # false: no click/focus/scroll/key stream
  disclose_to_annotators: false # true shows a notice
  disclosure_text: null
```

Switching it off stops the ambient stream on both the page and the server. AI-assistant
usage and the annotation change trail are still recorded, because they describe where
the saved answer came from rather than ambient behaviour. Item loads, saves, navigation
and an `activity` mark with no target or detail are recorded too, so time per item is
still measured.

## Where the data goes

- **user_state.json:** `instance_id_to_behavioral_data[<id>].authenticity`, holding
  `views` (each view's snapshot, with `first_seen`/`last_seen` server timestamps and
  phase/page), `summary` (the merge) and `verdict`. Survey, consent and training pages
  share the `__phase_page__` bucket, and each view is stamped with its phase and page.
  During annotation, a post for an item that is not assigned to the annotator is
  refused (403); on other pages it goes to the `__phase_page__` bucket.
- **Admin dashboard:** Behavioral tab, **Authenticity** panel. It shows per-annotator
  counts, flags, an `authenticity_risk` ranking and the per-item evidence. It is also
  available as JSON at `GET /admin/api/authenticity` and under the `authenticity` key
  of `/admin/api/behavioral_analytics`.
- **Export:** with `export_include_authenticity: true` the tabular exporters write
  `authenticity.<fmt>`, one row per (user, annotated item), with every field above plus
  `verdict_level` and `flags`.

`authenticity_risk` weights the share of a user's items that fired each flag:
automation 0.30, copy_then_paste 0.25, copy_then_away 0.20, external_paste 0.08,
pointer_teleport 0.07, synthetic_input 0.07, item_copied 0.04, away_from_task 0.03, split_screen 0.02,
paradata_missing 0.01. It tells you whom to look at first. It is not a probability.

## Limits

- Everything is measured in the annotator's browser, so a determined annotator can
  disable or rewrite the script. `paradata_missing` catches the crude version of this.
  Server-side timing (`server_span_ms`) cannot be inflated by the client.
- Using a chatbot on a second device (a phone) leaves no trace on the page at all.
  Combine these signals with [attention checks and gold
  items](../workflow/quality_control.md) and with clear instructions not to use AI. A
  plain request reduced AI use substantially in published platform tests.
- When `text_as_image` is on, the item cannot be copied, so the copy rules never fire.
  Leaving the page is still recorded.
- Pointer rules do not apply on touch devices. Those items carry a note in the verdict.

## Ethics and consent

These are behavioural measurements of identifiable people. State in your consent form
that page-leave, copy and paste *events* are recorded (not their content), keep
`disclose_to_annotators` on unless your ethics approval covers silent collection, and
treat the export like any other personal data. The guidance in [Keystroke Logging
Ethics](keystroke_logging_ethics.md) applies here too.
