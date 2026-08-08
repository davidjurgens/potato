# Keystroke Logging: Ethics, Consent and IRB

[Keystroke logging](keystroke_logging.md) records how your annotators write.
That is behavioural data about identifiable people, and it carries obligations
that the technical documentation does not cover.

This page is written for the researcher deploying the feature. It is not legal
advice, and it does not substitute for your own institution's review.

---

## What you are actually collecting

Potato's streams are **content-blind**: they record that a character was
inserted, when, where in the field, and what class of key produced it — never
which character. You cannot reconstruct the text from a stream.

That is a meaningful privacy protection, and it is **not** the same as the data
being non-identifying.

### Timing patterns are a biometric

Keystroke dynamics — the distribution of inter-key intervals, dwell times and
digraph latencies — are a well-established behavioural biometric. They can be
used to identify individuals and to link accounts across contexts. Potato does
not do this and provides no tooling for it, but the underlying data supports it.

Treat a keystroke stream the way you would treat any other behavioural
biometric: as identifiable, as needing a retention limit, and as requiring
consent.

### What can be inferred beyond authorship

Timing data has been used in research to infer typing skill, language
proficiency and second-language status, cognitive load and fatigue, and in some
literatures, motor and neurological conditions. Potato computes none of these,
but the data you retain would support such analysis, and your participants are
unlikely to anticipate that when they agree to "an annotation task".

Say what you collect. Do not rely on a general-purpose "we collect usage data"
clause to cover it.

---

## Disclosure

Disclosure happens in two places, and they do different jobs.

**1. Your consent phase — this is the one that matters.** Potato cannot write
your consent form. The sample language below goes in your consent survey, before
the annotator types anything.

**2. The standing notice — a reminder, not consent.** With
`disclose_to_annotators` on (the default), Potato renders a quiet bar under the
navigation header on every page that can hold a free-text field:

> ✎ This task records the timing and rhythm of your typing in text boxes (when
> you pause, revise, or paste) — not the individual keys you press.

It is server-rendered, so it survives a JavaScript failure, and it is not
dismissible. Override the wording with `disclosure_text` if your approval
specifies particular phrasing. The notice states the *limit* of the collection
as well as its existence, deliberately: an annotator told only "your typing is
recorded" will reasonably assume the keys themselves are stored.

A banner an annotator sees mid-task is not informed consent. It is a reminder
that the consent they already gave is still in force.

**Turning disclosure off** logs a warning at startup:

```yaml
keystroke_logging:
  disclose_to_annotators: false   # logs a warning; make sure your IRB covers this
```

There are legitimate reasons for undisclosed collection — some study designs are
invalidated by telling participants what is being measured — but that is an
ethics-board decision, not a configuration convenience. If you disable
disclosure, you should be able to point to the approval that permits it.

### Sample consent language

Adapt to your protocol; this is a starting point, not boilerplate to paste
unread.

> **How you write is recorded, along with what you write.**
>
> While you type your responses, this study records the *timing* of your typing:
> when you start and stop, how long you pause, when you go back and revise, and
> when you paste text in from somewhere else. It records **the timing and
> structure of your typing, not the individual keys you press** — the recording
> cannot be used to recover anything you typed other than the answers you
> submit.
>
> This is used to understand how people work through the task and to check the
> quality of the collected data.
>
> [If applicable:] These measurements may be used to identify responses that were
> copied or generated elsewhere rather than written by you.
>
> [If applicable:] The recordings will be shared as part of an anonymised
> research dataset.
>
> You may ask us to delete your data at any time by contacting [ ].

The bracketed clauses matter. If you intend to use flags for payment or
exclusion decisions, say so before people start work — not after you have
flagged them.

---

## Using flags fairly

[Writing-process detection](writing_process_detection.md) produces flags with
evidence. How you use them is your responsibility.

**Do:**

- Treat a flag as a prompt to look, not a finding.
- Read the per-session evidence, not just the verdict label.
- Give the annotator a chance to explain before acting.
- Account for the [known false positives](writing_process_detection.md#false-positives) —
  mobile keyboards, IME users, dictation, assistive technology, fast typists.
- Document your decision rule in advance, in your protocol.

**Do not:**

- Wire flags to automatic rejection, payment withholding, or bans.
- Treat the calibrated tail as wrongdoing. A percentile threshold flags a fixed
  share of *any* population, including an entirely honest one.
- Publish per-annotator risk scores in a way that identifies individuals.
- Use flags to make claims about a person beyond authorship of a response —
  the data does not support inferences about their competence, effort, or
  character.

### The base-rate problem

If 5% of your responses are LLM-pasted and your rule flags 5% of sessions, most
of what you flag can still be honest work, depending on how well the rule
separates the two. On a platform where genuine misconduct is rare, a rule with
even a small false-positive rate produces more false accusations than true
catches. Estimate your base rate before you set a policy on top of the flags.

---

## Participant rights

**Deletion.** Remove one participant's streams and summaries:

```python
from potato import typing_store
typing_store.delete_for_user(task_dir, project, user_id)
```

This clears `typing_sessions`. Summaries mirrored into
`<output_annotation_dir>/<user>/user_state.json` under `typing_summaries` must be
removed separately if you are honouring a full deletion request.

**Minimisation.** Collect the least that answers your question:

```yaml
keystroke_logging:
  fidelity: summary          # features only, no raw streams retained
  include_schemas: [rationale]   # instrument one field, not every box
  classify_paste_source: false   # skip clipboard comparison entirely
```

**Retention.** Potato does not expire data. If your protocol commits to a
retention window, delete the streams yourself when it elapses — `fidelity:
summary` after the analysis period is a reasonable middle ground, keeping the
aggregate features and dropping the biometric detail.

---

## Sharing and publication

If you release keystroke data as part of a dataset:

- Replace user ids with study-specific pseudonyms that do not map back to
  platform ids (Prolific/MTurk worker ids are identifiers, not pseudonyms).
- Consider whether session-level timing is needed, or whether summary features
  suffice. Summaries are far less re-identifiable than streams.
- Check that your consent covered redistribution, not only collection.
- The paste hashes are salted per session and cannot be reversed, but they do
  reveal that the same text was pasted twice — decide whether that linkage is
  acceptable in a public release.

Note that Potato's exports are opt-in for exactly this reason:
`export_include_typing_dynamics` and the `keystrokes` exporter are both off by
default, so behavioural data is never included in a dataset release by accident.

---

## Jurisdictional notes

Not legal advice; flagging what tends to be relevant.

- **GDPR / UK GDPR.** Timing patterns capable of identifying a person are
  personal data. If you use them to single out individuals, consider whether
  Article 22 (automated decision-making) applies — particularly if a flag
  affects payment. Consent must be specific and informed; a general terms
  acceptance is unlikely to suffice.
- **US institutional review.** Typically human-subjects research. Some IRBs
  treat keystroke dynamics as a biometric identifier, which can change the
  review category.
- **Crowdsourcing platforms.** Prolific, MTurk and similar have their own rules
  about monitoring participants and about rejecting work. Check the platform's
  policy before you reject anyone on the basis of a flag — several require you
  to be able to justify a rejection to the worker.

---

## Related documentation

- [Keystroke Logging](keystroke_logging.md) — what is captured and how
- [Writing-Process Detection](writing_process_detection.md) — the rules and their false positives
- [Crowdsourcing](../deployment/crowdsourcing.md) — working with paid annotators
