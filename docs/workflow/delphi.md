# Delphi Studies

In a Delphi study a panel rates the same items over several rounds. Between
rounds each panelist sees controlled feedback: how the panel rated each item
last round and their own previous rating, with other panelists' comments and
no names. Rounds continue until ratings are stable or agree, or a maximum
number of rounds is reached.

Rounds are sessions of the [schedule](scheduling.md). They are built on it
rather than on [multiplayer rooms](../advanced/multiplayer_rooms.md) because
a Delphi panel rates on its own and anonymously over days, while rooms are
live sessions whose members see each other. The schedule already has
windows, reminders, resume links and per-session answers.

## Configuration

```yaml
schedule:
  delphi:
    title: "Guideline criteria"
    intro: "Rate how important each criterion is."
    items_file: data/criteria.json      # or items: [{id, text}, ...]
    scale: {min: 1, max: 9, min_label: "Not important", max_label: "Essential"}
    comments: true
    max_rounds: 3
    round_length: 72h
    gap: 12h                            # between a round's close and the next
    # start: "2026-11-02T09:00:00-05:00"
    min_panel: 3
    stop:
      iqr_at_most: 1
      changed_share_below: 0.15
    reminders:
      - at: open
      - before_close: 24h

notifications:
  channels:
    - type: log
  contact:
    consent: {question: contact_consent, value: "Yes"}
```

| Key | Default | Meaning |
|---|---|---|
| `items` / `items_file` | one required | `[{id, text}]`; a file may be JSON, JSONL or YAML |
| `scale` | `1` to `9` | Whole-number rating scale (at most 21 points) with end labels |
| `comments` | `true` | Optional comment per item, shown to the panel without names |
| `max_rounds` | `3` | Upper limit (1 to 10) |
| `round_length` | required | How long each round is open |
| `gap` | `0` | Time between a round closing and the next opening |
| `start` | first server start | When round 1 opens (ISO 8601 with offset). Without it, round 1 opens when the server first runs with this config, and that time is kept across restarts |
| `min_panel` | `3` | Summaries and comments for an item are shown only when at least this many panelists rated it |
| `stop` | none | Stopping criteria, below |
| `reminders` | `[{at: open}]` | As for [waves](scheduling.md#reminders) |

Rounds are panel-wide: every enrolled panelist has a session for each round
that has not closed. A panelist who enrols during round 2 joins round 2 and
sees the round-1 feedback without an own rating.

## Feedback

From round 2, each item shows, for the previous round:

- the median, and the middle half of ratings (Q1 to Q3) as a shaded band on
  the scale, with the panelist's own rating marked;
- the number of ratings;
- the other panelists' comments, in an order fixed per panelist, without
  names. A panelist's own comment is not repeated back.

When fewer than `min_panel` panelists rated an item, no summary or comments
are shown for it, so a small panel's ratings cannot be traced to one person.
The current round's rating is not pre-filled.

## Statistics and stopping

When a round closes (at the end of its window, or when an admin presses
*Close the open round now* on `/admin/schedule`), Potato computes per item:

| Statistic | Definition |
|---|---|
| `n`, `median`, `mean` | Over the round's submitted ratings |
| `q1`, `q3`, `iqr` | Linear interpolation between order statistics (R type 7, NumPy's default, Python's `statistics.quantiles(method="inclusive")`) |
| `median_change` | Absolute change in median from the previous round |
| `changed_share` | Among panelists who rated the item in both rounds, the share whose rating changed |

An item is *settled* when it meets at least one configured criterion:

- `iqr_at_most: x`: IQR at most `x` (consensus);
- `median_change_at_most: x`: median moved by at most `x` (stability, from round 2);
- `changed_share_below: x`: fewer than `x` of panelists changed their rating (stability, from round 2).

The study stops after the first round in which every item is settled, or
after `max_rounds`. With no `stop` block it runs `max_rounds` rounds. The
stop reason is shown to panelists and on the admin page.

## Export

The `schedule` export adds:

| File | Rows |
|---|---|
| `delphi_ratings.csv` | participant, round, item, rating, comment |
| `delphi_rounds.csv` | per round and item: n, median, q1, q3, iqr, mean, median_change, changed_share, settled, the round's opening and closing time, status and stop reason |

Round sessions also appear in `schedule_sessions.csv` (kind `round`) with
their status and latency, and in the compliance table.

## Example

```bash
python potato/flask_server.py start examples/advanced/delphi-study/config.yaml -p 8000
```

Eight criteria for annotation guidelines, three rounds of three days with
12 hours between rounds. To try round 2 at once, enrol three panelists,
rate, and close round 1 from `/admin/schedule` (the next round opens after
the 12-hour gap; set `gap: 0` to open it at once).

## Related

- [Scheduled Sessions and Notifications](scheduling.md)
- [Experience Sampling](experience_sampling.md)
