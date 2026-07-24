# Prolific Integration Guide

Prolific is Potato's primary supported crowdsourcing platform. This guide covers
the complete setup: URL-direct login, completion codes, and the optional API
integration for submission monitoring and workload management.

_Verified against the Prolific platform and API, July 2026._

## Quick start

### 1. Configure Potato

```yaml
# config.yaml
login:
  type: url_direct          # or "prolific" to enable API tracking (see below)
  url_argument: PROLIFIC_PID

completion_code: "C1ABCDEF"   # the code you configure in Prolific

# Optional: automatically send participants back to Prolific when done
auto_redirect_on_completion: true
auto_redirect_delay: 5000     # milliseconds

# Recommended for crowdsourcing:
hide_navbar: true
jumping_to_id_disabled: true
assignment_strategy: random
max_annotations_per_user: 20
```

### 2. Create the study on Prolific

In the Prolific study form, set the external study URL to your Potato server with
Prolific's URL parameter placeholders:

```
https://your-server.com/?PROLIFIC_PID={{%PROLIFIC_PID%}}&STUDY_ID={{%STUDY_ID%}}&SESSION_ID={{%SESSION_ID%}}
```

Choose **"I'll use URL parameters"** for the "How do you want to record Prolific
IDs?" option, and configure a completion code. Potato's `completion_code` must
match a code configured on the study.

### 3. The participant flow

1. A participant clicks your study link; Prolific fills in the placeholders.
2. Potato reads `PROLIFIC_PID` from the URL, creates a passwordless account with
   that ID as the username, and drops the participant into your task (consent →
   instructions → annotation, per your phase configuration).
3. When they finish, Potato shows the completion code with a **Return to
   Prolific** button linking to
   `https://app.prolific.com/submissions/complete?cc=<code>`, or redirects
   automatically if `auto_redirect_on_completion` is set.

`SESSION_ID` and `STUDY_ID` are captured into the participant's session for
tracking.

## API integration (optional)

Setting `login.type: prolific` plus a `prolific:` block enables API-level
features on top of URL-direct login:

- **Submission monitoring** — Potato periodically fetches submission statuses
  (`ACTIVE`, `AWAITING REVIEW`, `APPROVED`, `REJECTED`, `RETURNED`, `TIMED-OUT`).
- **Assignment reclaim** — items assigned to participants whose submissions are
  `RETURNED`, `TIMED-OUT`, or `REJECTED` are released for reassignment
  (configurable via `instance_reclaim`).
- **Workload management** — opt-in automatic pause/resume of the study based on
  concurrent active participants.

### Setup

Get an API token from your Prolific workspace settings, then create a config
file (keep it out of version control):

```yaml
# configs/prolific_config.yaml
token: "your-prolific-api-token"
study_id: "your-study-id"
workload_checker: true           # opt in to auto pause/resume (default: off)
max_concurrent_sessions: 30
workload_checker_period: 300     # seconds between checks
```

```yaml
# config.yaml
login:
  type: prolific
  url_argument: PROLIFIC_PID

prolific:
  config_file_path: configs/prolific_config.yaml

completion_code: "C1ABCDEF"
```

The workload monitor pauses the study when active participants reach
`max_concurrent_sessions` and resumes it when the count drops below 20% of the
maximum. It only resumes studies it paused itself — if you pause the study
manually in Prolific, Potato will not restart it.

### API notes (current as of July 2026)

- Base URL: `https://api.prolific.com/api/v1/`, auth header `Authorization: Token <token>`.
- The completion redirect is `https://app.prolific.com/submissions/complete?cc=<code>`
  (the old `app.prolific.co` domain no longer serves HTTPS at all).
- Studies now use a `completion_codes` array with per-code actions (auto-approve,
  screen-out, add to participant group); configure these in the Prolific study
  form. Approvals and payments are handled on the Prolific side.
- Prolific marks a submission `ACTIVE` automatically when the participant follows
  your study URL — Potato does not need to report "started".

## Study management from the admin dashboard (Tier-3 API)

With a token and `study_id` configured, the admin dashboard's Crowdsourcing tab
gains a Prolific study panel, backed by `/admin/api/crowd/...` endpoints (all
gated on the `manage_crowdsourcing` permission; the shared admin key passes):

- **Lifecycle**: publish, pause, start, stop the study.
- **Places**: increase `total_available_places` (Prolific never lets places
  shrink), or **auto-scale** — Potato computes remaining annotation slots
  (per-item cap minus current annotators) divided by the per-worker quota and
  grows the study to match.
- **Submissions review**: approve or reject (Prolific requires a rejection
  message of at least 100 characters plus a category) individual submissions,
  or bulk-approve everything awaiting review.
- **Bonuses**: `POST /admin/api/crowd/study/<id>/bonus` with
  `{"bonuses": [["<participant_id>", 1.50], ...], "pay": true}`.
- **Paid screen-outs**: `POST /admin/api/crowd/study/<id>/screen_out` with
  submission IDs — or automatically: set
  `crowdsourcing.prolific.screen_out_on_block: true` (with `token` and
  `study_id` in the same block) and participants blocked by attention checks
  are screened out via the API when they reach the done page. The study needs
  Prolific's fixed screen-out feature with a screen-out completion code.
- **Qualification sync**: `POST /admin/api/crowd/qualification_sync` with
  `{"project_id": ..., "group_name": ..., "source": "annotated"|"blocked"}`
  materializes your local annotator sets as a Prolific participant group —
  usable as a study filter for cross-study inclusion/exclusion (e.g. keep
  wave-1 annotators out of wave 2), the Mephisto pattern.
- **Cost preview**: `GET /admin/api/crowd/cost_preview?reward=<subcurrency>&places=<n>`.
- **Test participants**: `POST /admin/api/crowd/test_participant` creates a
  no-credit test participant (the old email-support test flow is deprecated).

Study creation via `POST /admin/api/crowd/study` accepts the **current**
Prolific study model — a `completion_codes` array with per-code
`code_type`/`actor`/`actions`, and `filters`/`filter_set_id` for
prescreening. The retired `completion_code`/`failed_attention_code`/
`eligibility_requirements` fields are rejected with an explanatory error.

API oddities to know (verified against Prolific's docs): places can only
increase; most study fields are immutable after publish; there are no
EXPIRED/STOPPED submission statuses (submissions live in
RESERVED/ACTIVE/AWAITING REVIEW/APPROVED/REJECTED/RETURNED/TIMED-OUT/
SCREENED OUT); submissions auto-approve after 21 days in AWAITING REVIEW.

## Screening and attention checks

Configure Potato's [quality control](../workflow/quality_control.md) (attention
checks, gold standards, pre-study qualification via the training phase). For
participants who fail screening, Prolific supports separate screen-out completion
codes — you can create a code with a screen-out action in the Prolific study form
and direct failed participants to it.

## Testing

- Run your config locally and simulate a participant arrival:
  `http://localhost:8000/?PROLIFIC_PID=TEST123&STUDY_ID=S1&SESSION_ID=X1`
- Prolific also offers preview links and (via API) test participants that don't
  consume study places.

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| "Missing required URL parameter" error | The study URL on Prolific lacks the `PROLIFIC_PID={{%PROLIFIC_PID%}}` placeholder, or you visited the server directly. |
| No "Return to Prolific" button on the done page | `completion_code` unset, or `login.url_argument` is not `PROLIFIC_PID`. |
| Study never resumes after pausing | The monitor only resumes studies it paused itself; check `workload_checker: true` is set and the server log for API errors. |
| API features silently missing | `prolific:` block needs both `token` and `study_id`; check server startup logs for "Initialized Prolific study". |

## Related documentation

- [Crowdsourcing setup guide](crowdsourcing.md)
- [Choosing a crowdsourcing platform](crowdsourcing-platforms.md)
- [Quality control](../workflow/quality_control.md)
