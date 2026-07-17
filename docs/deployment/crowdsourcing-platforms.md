# Choosing a Crowdsourcing Platform

Amazon Mechanical Turk **closed to new requesters on July 30, 2026**. Existing MTurk
requester accounts continue to work (see the [MTurk guide](mturk_integration.md)), but
new projects need a different recruitment platform. This page surveys the platforms
that work with Potato's deployment model and how to connect them.

_Survey last verified: July 2026._

## How Potato connects to a platform

Potato uses the **external study URL** pattern that most research platforms support:

1. You create a study/task on the platform and point it at your Potato server,
   with the platform's participant-ID placeholder in the URL
   (e.g. `https://your-server.com/?PROLIFIC_PID={{%PROLIFIC_PID%}}`).
2. The participant clicks the link; Potato logs them in automatically from the URL
   parameter (`login.type: url_direct`) and serves the annotation task.
3. When they finish, Potato shows a completion code and/or redirects them back to
   the platform so they get paid.

Any platform that passes an ID in the URL and accepts a completion code or return
redirect can be used with Potato today via `url_direct` login. Platforms with deeper
support (Prolific) also get API-level features (submission monitoring, auto
pause/resume, assignment reclaim for returned participants).

## Recommended platforms

### Prolific (recommended, fully integrated)

- **Population:** ~300k vetted research participants, strongest in UK/US.
- **Model:** external study URL with `{{%PROLIFIC_PID%}}` / `{{%STUDY_ID%}}` /
  `{{%SESSION_ID%}}` placeholders; completion via
  `https://app.prolific.com/submissions/complete?cc=CODE`.
- **API:** full REST API (`api.prolific.com`) with token auth — studies,
  submissions, approvals, bonuses, filters, webhooks.
- **Potato support:** first-class. See the [Prolific integration guide](prolific_integration.md).

### CloudResearch Connect

- **Population:** vetted, quality-screened participants (US-centric). This is the
  platform CloudResearch is migrating MTurk Toolkit users to — the most direct
  MTurk replacement for research use.
- **Model:** "Project Link" external URL; passes `participantId` (plus optional
  `assignmentId`, `projectId`); completion via fixed code or completion redirect.
- **API:** REST API at `connect-api.cloudresearch.com` (API key).
- **Potato support:** works today via `url_direct` login with
  `url_argument: participantId` and a `completion_code`. Deeper integration is planned.

### SONA Systems (university subject pools)

- **Population:** your institution's participant pool (students, usually for course
  credit). Licensed by most psychology departments.
- **Model:** put `%SURVEY_CODE%` in the study URL (SONA substitutes a unique
  per-participant code); grant credit via a client-side completion URL or a
  server-side `WebstudyCredit` API call.
- **Potato support:** works today via `url_direct` login with
  `url_argument: <your param name>`; automatic server-side credit granting is planned.

### Besample

- **Population:** participants in ~40 non-Western countries — complements
  Prolific's UK/US skew for cross-cultural work.
- **Model:** external survey link with a `response_id` parameter; participants
  return a completion code. No public API.
- **Potato support:** `url_direct` login with `url_argument: response_id` +
  `completion_code`.

### Other panels that work the same way

| Platform | Population | URL parameter | Completion |
|----------|------------|---------------|-----------|
| Positly | brokered general panels | participant ID + demographic params | completion link |
| Testable Minds | vetted general pool | (see their setup docs) | code |
| User Interviews | UX-research pool (US-heavy) | `iid=TRACKINGID` | status redirect URLs |
| Cint (Lucid Exchange) | very large programmatic survey panel | `PID` + session vars | status-coded redirects; contract onboarding |

All of these follow the same pattern: set `login.type: url_direct`, set
`login.url_argument` to the platform's ID parameter, and configure a
`completion_code` (plus `auto_redirect_on_completion` where the platform supports
return URLs).

## Volume crowds (MTurk-style, use with strong quality controls)

- **Microworkers** — large international micro-task crowd; external campaigns with
  a VCODE completion-verification code; public API v2 (campaigns, bonuses, worker
  ratings). Quality is MTurk-like: pair with Potato's
  [attention checks and gold standards](../workflow/quality_control.md).
  Potato support: `crowdsourcing.provider: microworkers` generates deterministic
  per-worker VCODEs (HMAC over worker + campaign IDs) that you can re-verify.
- **Clickworker** — large crowd, strong EU coverage; markets its external-form
  product explicitly as an MTurk alternative; self-serve external-survey orders
  or a marketplace API with a completion postback that triggers payment.
  Potato support: `crowdsourcing.provider: clickworker` (completion code; the
  payment postback ships experimental until the API contract is verified).

## Platforms that do NOT fit Potato's model

These either shut down their open crowd, have no self-serve access, or run tasks
only inside their own tools:

- **Amazon SageMaker Ground Truth** — its "public workforce" *is* MTurk, so it dies
  with MTurk for new customers; remaining workforces are private/vendor and tasks
  run in Ground Truth's own templates.
- **Toloka** — exited the open-crowd business (contributors moved to its Mindrift
  expert platform); no self-serve task posting.
- **Appen/CrowdGen, Scale AI/Outlier, Surge AI, iMerit** — enterprise, sales-led
  managed labeling; no external-URL model.
- **Labelbox / SuperAnnotate workforce marketplaces** — work happens inside their
  annotation tools.
- **Expert platforms (Mercor, micro1, Handshake AI, Pareto.AI, Invisible, Centaur)** —
  managed expert engagements for AI-lab data work; no self-serve posting or
  participant-redirect protocol.

For hiring experts on **Upwork, Fiverr, Toptal, or direct contracts**, use
Potato's [expert invite links](expert_annotators.md): per-expert tokenized
URLs pasted into the contract chat, with admin work reports for invoicing.

## Migration checklist from MTurk

1. Pick a platform above (Prolific or Connect for vetted general populations;
   SONA for university pools; Besample for non-Western populations).
2. Change `login.url_argument` from `workerId` to the new platform's parameter.
3. Replace the MTurk External Question HIT with the platform's study/project
   pointing at your server URL.
4. Set `completion_code` (and `auto_redirect_on_completion` if the platform uses
   return URLs).
5. Keep your quality controls: attention checks, gold standards, and per-user
   quotas work identically on every platform.

## Related documentation

- [Crowdsourcing setup guide](crowdsourcing.md)
- [Prolific integration](prolific_integration.md)
- [MTurk integration (frozen)](mturk_integration.md)
- [Quality control](../workflow/quality_control.md)
