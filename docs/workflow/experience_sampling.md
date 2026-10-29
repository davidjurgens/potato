# Experience Sampling

Experience sampling (ecological momentary assessment) asks participants the
same short questions several times a day, at the moment of the prompt. Potato
supports signal-contingent prompts (random times inside a daily window) and
interval-contingent prompts (fixed times or a fixed interval). Each prompt
expires, and the export reports compliance and latency per prompt.

Prompts are sessions of the [schedule](scheduling.md): they use the same
enrolment, time zones, notification channels, resume links and admin page.

## Configuration

```yaml
schedule:
  timezone: "UTC"                # fallback when the browser reports none
  seed: "daily-mood-pilot"       # mixed into the random times
  experience_sampling:
    title: "How are you right now?"
    days: 7
    start_day: 1                 # 0 = the enrolment day, 1 = the next day
    daily_window: "09:00-21:00"
    signal:                      # signal-contingent ...
      per_day: 5
      min_gap: 90m
    # interval: {every: 3h}      # ... or interval-contingent
    # interval: {times: ["10:00", "14:00", "20:00"]}
    expires_after: 30m
    questions_file: surveys/prompt.json
    reminders:
      - at: open                 # the prompt itself
      - after_open: 15m          # a nudge if not answered yet

notifications:
  channels:
    - type: twilio
      account_sid_env: TWILIO_ACCOUNT_SID
      auth_token_env: TWILIO_AUTH_TOKEN
      from_number: "+15550100"
  base_url: "https://study.example.org"
  contact:
    consent: {question: sms_consent, value: "Yes"}
```

| Key | Default | Meaning |
|---|---|---|
| `days` | required | Number of sampling days (1 to 366) |
| `start_day` | `1` | First sampling day, counted from the enrolment day |
| `daily_window` | `"09:00-21:00"` | Local window prompts fall in |
| `signal.per_day` | required with `signal` | Prompts per day (1 to 48) |
| `signal.min_gap` | `60m` | Least time between two prompts; at least `expires_after` |
| `interval.every` | none | A prompt at the window start and every interval after it |
| `interval.times` | none | Fixed local clock times |
| `expires_after` | `30m` | How long each prompt stays open |
| `questions` / `questions_file` | one required | Same question types as [waves](scheduling.md#questions) |
| `reminders` | `[{at: open}]` | `at: open`, `after_open`, `before_close`; `before_open` is refused because it would announce a random prompt |
| `title`, `intro` | | Shown on the prompt page |

Validation refuses a plan that cannot work: `per_day` prompts `min_gap`
apart that do not fit in the window with the last one's expiry, an interval
longer than the window, or fixed times closer together than `expires_after`.

## How prompt times are drawn

For each day, the window is placed on that local date in the participant's
time zone, so it is 09:00 to 21:00 on the day the clocks change too.
Signal-contingent times are drawn by sampling `per_day` points uniformly in
the window shortened by `(per_day - 1) × min_gap` and the expiry, sorting
them, and adding `i × min_gap` to the i-th. Every arrangement that respects
the gap is equally likely, and every prompt expires inside the window. The
generator is seeded with `schedule.seed`, the participant id and the date,
so a plan can be recomputed and two participants do not share times.
Interval prompts are cut off at the window end in the same way. Prompts
whose time has passed at enrolment are left out.

The status page never shows the time of the next random prompt, only the
day's window. Fixed-time prompts are shown.

## Answering

The prompt message carries a resume link. Opening it signs the participant
in on that prompt. The first interaction with the form is recorded (a small
request from the page; without JavaScript the submit time is used), and the
answers are saved on submit. A prompt cannot be answered after it expires.

## Compliance and latency

In `schedule_sessions.csv` (the `schedule` export), each prompt row has:

| Column | Meaning |
|---|---|
| `day`, `prompt` | Sampling day (1-based) and prompt number that day |
| `status` | `answered`; `expired` (opened, not submitted in time); `missed` (never opened) |
| `prompt_at_utc` | When the prompt message went out, or the scheduled time if none was sent |
| `first_answer_at_utc` | First interaction with the form |
| `latency_seconds` | `first_answer_at - prompt_at` |
| `response_seconds` | Submit time minus first answer |
| `answer.<name>` | One column per question |

`schedule_compliance.csv` has, per participant, the number of prompts
closed, answered, expired and missed, compliance (answered / closed) and
median latency. The admin page shows the same per participant.

## Example

```bash
python potato/flask_server.py start examples/advanced/experience-sampling/config.yaml -p 8000
```

Five prompts a day for a week, 09:00 to 21:00, at least 90 minutes apart,
each open 30 minutes. Messages go to the `log` channel and a dry-run Twilio
channel; `/admin/schedule` shows each prompt with its link.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `... do not fit in the daily window` | Fewer prompts, a shorter `min_gap` or a longer window |
| No prompts on the first day | `start_day: 1` starts the next day; prompts already past at enrolment are left out |
| Latency missing | The prompt was never opened, or no message was sent and the form was never touched |

## Related

- [Scheduled Sessions and Notifications](scheduling.md)
- [Delphi Studies](delphi.md)
