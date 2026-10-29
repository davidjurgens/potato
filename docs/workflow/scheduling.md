# Scheduled Sessions and Notifications

Some studies continue after the first visit: a panel with a follow-up a week
later, experience sampling with several short surveys a day, or a Delphi
panel that rates the same items over several rounds. The `schedule:` block
describes those sessions, and the `notifications:` block sends reminders by
email, SMS or Prolific message.

This page covers waves, windows, reminders, resume links, the notification
channels and how contact details are handled. Prompts are described in
[Experience Sampling](experience_sampling.md) and rounds in
[Delphi Studies](delphi.md).

## Enrolment and message flow

1. The participant goes through the regular flow (consent, instructions,
   annotation, surveys) as in any Potato study.
2. When they reach the end of it, they are **enrolled**: Potato asks for their
   time zone (filled in from the browser) and, if they agreed to be
   contacted, an email address and/or a mobile number. Participants who were
   screened out, failed training or were blocked by attention checks are not
   enrolled.
3. Their sessions are computed at that moment and stored, with every reminder
   that will go out.
4. A background loop sends each message when it is due. Each message has a
   **resume link** that signs the participant in and opens the session.
5. A participant who comes back with their study link is sent to the session
   that is open. If none is open, they see when the next one opens, in their
   own time zone.

The schedule is fixed at enrolment. Editing `waves` later changes the plan
only for participants who enrol afterwards.

## Waves and windows

```yaml
schedule:
  timezone: "Europe/London"      # used when the browser reports no time zone
  waves:
    - name: followup             # id used in the export
      title: "One-week follow-up"
      offset: 7d                 # after enrolment
      at: "09:00"                # optional: local clock time on that day
      window: 48h                # how long it stays open
      questions_file: surveys/followup.json
      reminders:
        - before_open: 12h
        - at: open
        - before_close: 12h
      completion_code: "FOLLOWUP-DONE"   # optional, shown after submitting
```

| Key | Default | Meaning |
|---|---|---|
| `name` | required | Short id (letters, digits, `_`, `-`) |
| `title` | `name` | Shown to participants and in messages |
| `offset` | `0` | Time after enrolment: `30m`, `48h`, `7d`, `2w` or seconds |
| `at` | none | Local clock time. The wave opens at this time on the day `offset` days after enrolment; `offset` must then be whole days |
| `window` | required | How long the wave stays open |
| `questions` / `questions_file` | one required | The questions (below) |
| `reminders` | `[{at: open}]` | When messages go out (below) |
| `completion_code` | none | A code shown on the thank-you page, for example for a second Prolific study |
| `intro` | none | Text above the questions |

Quote clock times (`"09:00"`). YAML 1.1 reads an unquoted `10:30` as the
number 630; Potato accepts that, but the quotes make the intent clear.

**Daylight saving.** With `at`, the wave opens at 09:00 local time even if
the clocks change in between. Without `at`, `offset: 7d` means seven days of
elapsed time, so across a change the local clock time moves by an hour.

### Questions

Session questions are written like annotation schemes, with these types:
`radio`, `likert`, `multiselect`, `slider`, `number`, `text`.

```json
[
  {"name": "changed_view", "annotation_type": "radio",
   "description": "Since last week, has your view changed?",
   "labels": ["No", "A little", "A lot"], "required": true},
  {"name": "trust_media", "annotation_type": "likert",
   "description": "How much do you trust news media today?",
   "size": 5, "min_label": "Not at all", "max_label": "Completely"},
  {"name": "energy", "annotation_type": "slider", "description": "Energy?",
   "min_value": 0, "max_value": 100, "starting_value": 50},
  {"name": "hours", "annotation_type": "number", "description": "Hours slept",
   "min_value": 0, "max_value": 24},
  {"name": "notes", "annotation_type": "text", "description": "Anything else?",
   "multiline": true, "max_length": 1000}
]
```

`required: true` (or `label_requirement: {required: true}`) makes a question
mandatory. A slider counts as answered only once the participant has moved
it. Answers outside the options or range are refused. A `questions_file` is
JSON or YAML, read relative to the config file.

Session answers are stored per session in the schedule store, not in
`user_state.json`, so the same question can be answered many times.

### Reminders

| Rule | When |
|---|---|
| `{at: open}` | When the window opens |
| `{before_open: 12h}` | 12 hours before it opens |
| `{after_open: 2h}` | 2 hours after it opens, if not yet answered |
| `{before_close: 12h}` | 12 hours before it closes, if not yet answered |

A reminder is not sent when the session is already answered, when the
session has closed, or (for `before_open`) when it has already opened.
Reminders due before the participant enrolled are not sent.

## Notifications

```yaml
notifications:
  dry_run: false
  base_url: "https://study.example.org"   # public address for links
  channels:
    - type: log
    - type: smtp
      host: smtp.example.org
      port: 587
      security: starttls          # starttls | ssl | none
      username_env: POTATO_SMTP_USER
      password_env: POTATO_SMTP_PASSWORD
      from: "Study team <study@example.org>"
    - type: twilio
      account_sid_env: TWILIO_ACCOUNT_SID
      auth_token_env: TWILIO_AUTH_TOKEN
      from_number: "+15550100"     # or messaging_service_sid_env: NAME
    - type: prolific
      token_env: PROLIFIC_API_TOKEN
      study_id: "60d0..."          # optional; else the participant's STUDY_ID
  contact:
    consent:
      question: contact_consent    # a question on a phase page
      value: "Yes"                 # the answer that allows contact
    delete_after_study: true
```

| Channel | Delivers to | Needs |
|---|---|---|
| `log` | The server log and the admin page, with the full text and links. Delivers nothing | nothing |
| `smtp` | The email address given at enrolment | an SMTP server |
| `twilio` | The mobile number given at enrolment, by SMS | a Twilio account |
| `prolific` | The participant's Prolific inbox, by Prolific participant id | a Prolific API token; participants who arrived from Prolific |

**Credentials come from environment variables only.** Each `*_env` key names
a variable; the value is read when a message is sent. Writing `password:`,
`token:`, `auth_token:`, `account_sid:`, `username:` or `api_key:` in the YAML
stops the server at startup. A missing variable is logged at startup and
each message on that channel fails with the variable's name.

`dry_run: true` renders and addresses every message on every channel and
records it as `dry_run` without delivering it. Use it to pilot a study. The
example configs use the `log` channel and `dry_run`.

`base_url` is required for any channel other than `log` unless `dry_run` is
on: messages are sent by the background loop, which has no request to take
the server's address from.

Delivery: every message is planned once per session, rule and channel, and
claimed in the database before it is sent, so a restart or a second server
process does not send it twice. A message interrupted mid-send (the server
stopped) is marked failed and not resent. Transient errors (SMTP connection
errors, Twilio or Prolific 429 and 5xx) are retried up to three times while
the session is still open; other errors fail at once.

### Message text

Defaults exist for each kind. Override them under `templates`:

```yaml
notifications:
  templates:
    open:
      subject: "{study}: {session} is open"
      body: "Please answer by {closes}: {link}\n\nStop messages: {stop_link}"
```

Kinds: `before_open`, `open`, `reminder` (`after_open` and `before_close`),
`prompt` (experience sampling), `delphi_round`. Placeholders: `{study}`,
`{session}`, `{opens}`, `{closes}` (in the participant's time zone),
`{time_left}`, `{link}`, `{stop_link}`. An unknown placeholder stops the
server at startup. SMS uses the body only.

## Resume links

A resume link (`/s/<token>`) signs the participant in and opens one session.
The token carries the participant id, the session, an expiry (the session's
close) and an HMAC-SHA256 tag, the same construction the external runtime
phase uses for signed returns. The key is `POTATO_SCHEDULE_LINK_KEY` when set,
otherwise a random key generated once in `<task_dir>/.potato/scheduling/link.key`
so links keep working after a restart. Set the variable when the server may
start on a fresh disk.

An expired link says which session closed and when. A changed or foreign
link signs nobody in. Stopping messages invalidates every link sent to that
participant before.

## Contact details and consent

Email addresses and phone numbers are participant PII.

- **Consent.** `notifications.contact.consent` must name a question on a
  phase page and the answer that allows contact. Potato refuses to start
  without it when channels are configured, and checks that the question and
  answer exist. Only participants who gave that answer are asked for an
  address; an address posted without consent is discarded. Nobody without
  consent is messaged on any channel, including `log`.
- **Storage.** Addresses are kept in `<task_dir>/.potato/scheduling/contacts.sqlite`
  (file mode 0600), outside the annotation output directory. Nothing else
  holds them: not `user_state.json`, not the schedule store, not the
  notification log (which records the channel, never the address).
- **Exports.** No exporter reads the contact store. The data archive
  (`potato deploy pull`, `/admin` archive) and off-host backups cover the
  output directory only, and deploy bundles skip `.potato`. A server test
  runs every registered exporter and the archive and checks that neither the
  address nor the number appears in any file.
- **Deletion.** Participants can stop messages from the status page or from
  the stop link in every message (the link opens a confirmation page; the
  deletion is a POST, so mail scanners that open links do not trigger it).
  Admins can delete a participant's details on `/admin/schedule`. With
  `delete_after_study: true` (the default) details are deleted once the
  participant has no sessions left.

Because the contact store is outside the backed-up directory, a host that
loses its disk on restart (some PaaS free tiers) also loses the addresses.
Participants on such hosts get no further reminders after a restart unless
they come back on their own.

## Admin page

`/admin/schedule` (admin key or an RBAC admin role) shows enrolment, each
participant's compliance (answered / expired / missed), median latency and
next session, upcoming, sent, failed and skipped messages (with the text for
`log` and `dry_run` messages), Delphi rounds and item statistics, and every
session. Wide tables scroll sideways inside their panel. Buttons: send due
messages now, delete a participant's contact details, close the open Delphi
round. `/admin/api/schedule` returns the same data as JSON, without addresses.

## The background loop

The loop starts with the server (`schedule.scheduler: true`, every
`poll_seconds`, default 30) and never at import. It sends due messages,
opens and closes Delphi rounds and deletes finished participants' contact
details. With `scheduler: false`, nothing is sent until an admin presses
*Send due messages now* or calls `POST /admin/api/schedule/tick`.

## Export

The `schedule` export writes sidecar tables rather than adding a wave
column to the main export: session answers are not item annotations, and
`user_state.json` is rewritten in full on every save, so it does not hold
them. Every table has `participant`, the same id as `user_id` in the main
export.

```bash
python -m potato.export --config config.yaml --format schedule --output out/
```

| File | Rows |
|---|---|
| `schedule_sessions.csv` | One per participant and session, plus an `enrolment` row (the regular flow). Kind, wave / day / prompt / round, window in UTC and local time, status, prompt time, opened, first answer, submitted, `latency_seconds`, `response_seconds`, one `answer.<name>` column per question |
| `schedule_compliance.csv` | Per participant and kind: closed, answered, expired, missed, compliance, median latency |
| `schedule_notifications.csv` | Every planned message: session, rule, channel, due, status, attempts, sent, detail. No address, no text |
| `delphi_ratings.csv`, `delphi_rounds.csv` | Delphi only, see [Delphi Studies](delphi.md) |

Statuses: `answered`; `expired` (opened but not submitted before it closed);
`missed` (never opened while open); `open`, `started`, `upcoming` for
sessions not yet closed.

## Example

```bash
python potato/flask_server.py start examples/advanced/two-wave-panel/config.yaml -p 8000
```

Rate five statements, enrol, and see the follow-up's opening time. Messages
appear on `/admin/schedule`.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `credentials are read from environment variables only` at startup | A password or token is in the YAML; use the `*_env` key |
| `contact.consent is required` | Channels are configured without the consent question |
| `... is not asked on any phase page` | The consent question name does not match a question on a phase page |
| Messages show `failed: environment variable X is not set` | Set the variable on the server and restart |
| Messages show `skipped: no contact consent` | The participant did not give the consent answer, or stopped messages |
| Nobody is enrolled | Participants enrol at the end of the regular flow; check they reach it |
| Times look an hour off | Check the participant's time zone on the admin page; waves without `at` use elapsed time |

## Related

- [Experience Sampling](experience_sampling.md)
- [Delphi Studies](delphi.md)
- [Longitudinal studies](../deployment/longitudinal-studies.md)
- [Prolific integration](../deployment/prolific_integration.md)
- [Experiment flow](experiment_flow.md)
