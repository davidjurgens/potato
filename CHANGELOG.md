# Changelog

All notable changes to the Potato annotation platform are documented in this file.

## [Unreleased] - Threaded Conversations, and ConvoKit Both Ways

**Threaded conversation annotation.** The `dialogue` display now renders reply
structure: set `indent_replies: true` and nesting is derived from each turn's
`reply_to` — nothing has to precompute it, and turn identity is read from
`turn_id`, `step_id`, or plain `id`, so forum exports, chat logs, and mailing
lists all work unchanged. Adds per-turn timestamps (`relative`/`absolute`/`epoch`)
and metadata chips. A threaded conversation supports the full range of annotation
at once on one field: whole-thread schemes, per-comment radio/likert/select/text,
spans, and `span_link` between spans in different comments. `conversation_tree`
gains per-node widgets keyed by node id, making a two-view task possible — a
branching tree for structure and a flat thread for text — where both views refer
to the same messages.

**ConvoKit integration, both directions.** `potato convokit <corpus>` imports any
[ConvoKit](https://convokit.cornell.edu/) corpus (by name, directory, or zip) at
conversation or utterance granularity, and `--format convokit` exports annotations
back as corpus metadata — either `info.<field>.jsonl` overlays that drop into an
existing corpus or a full corpus dump. Each turn carries the real ConvoKit
utterance id, so per-comment annotations round-trip by direct lookup. Reads every
format variant in the wild, including the pre-rename `user`/`root`/`users.json`
layout. No `convokit` dependency — the format is read and written with the
standard library. Also `--emit-config` to draft a task from a corpus's own
metadata, `--dry-run`, and `--list-corpora`.

**Fixes**

- **Dialogue span offsets were wrong.** `reconstruct_dialogue_dom_text()`
  collapsed whitespace while the client deliberately did not, so every dialogue
  span was sliced at a drifting offset — a few characters further off per turn,
  which meant short conversations looked correct and long ones silently returned
  neighbouring text. Both sides now agree byte for byte, pinned by
  `tests/unit/test_dialogue_span_contract.py`.
- `.per-turn-rating` was missing from the client's span-offset skip list, so the
  legacy `per_turn_ratings` widget shifted every subsequent offset.
- Removed a stale config warning claiming turn-level widgets break span offsets
  on the same field. They do not, and the warning discouraged a combination —
  rate each comment *and* highlight text in it — that is a main reason to
  annotate conversations.
- `potato/export/cli.py` read data files line by line only, so a JSON-array data
  file exported with **zero items**, silently stripping every exporter of the
  item data it needs.
- `validate_cli` reported `FAILED — 0 error(s)` for configs that pass with
  warnings.
- `ConversationTreeDisplay` ignored its `display_options` block.

New examples under `examples/conversation/`: `threaded-forum` (no ConvoKit),
`convokit-awry`, `convokit-politeness` (legacy corpus format), `convokit-tree`.

---

## [2.7.1] - Transcripts In, Without the Reformatting

Direct support for speech that was transcribed elsewhere: **21 transcript and subtitle input formats** (up from 6) spanning ASR output (Whisper, WhisperX, whisper.cpp, Whisper TSV, AWS Transcribe, Deepgram, AssemblyAI, Rev.ai, SPoRC), subtitles and captions (SRT, WebVTT, ASS/SSA, TTML/DFXP, YouTube json3 and srv1/srv2/srv3), and forced-alignment import (CTM, Praat TextGrid, ELAN EAF — so tiered annotations now round-trip). Transcripts can live in **sidecar files** beside the media instead of being inlined into the data file, a `potato transcripts` CLI converts a directory of ASR output into a ready-to-annotate data file, and all four transcript-consuming schemas share one format vocabulary. Word-level timings and confidence are preserved. New reference and guide pages, plus a six-format example. Pure stdlib, no new dependencies, fully back-compatible. Also fixes a `user_input()` ReferenceError thrown by the instance-jump input in the base templates.

**[Full Release Notes →](docs/releasenotes/v2.7.1.md)**

---

## [2.7.0] - Seven New Ways to Annotate

The largest release yet: seven opt-in features built around the idea that an annotation tool should measure *how* judgments come to be, not just collect them — Psychometrics (live IRT, labels with error bars), Multiplayer Rooms (instrumented norming sessions), Boundary Lab (counterfactual probes), Truth Serum (surprisingly-popular scoring), Think-Aloud Mode (local voice rationales), Paper Mode (methods section from your data), and Pocket Mode (phone annotation). None requires an LLM. Plus cross-document event annotation, turn-level annotation, CoT process-reward labeling, PDF cross-page linking, a living-document codebook, RBAC roles with per-cohort schemas, localized dashboards in 10 languages, an ACL 2026 demo-track paper with `CITATION.cff`, and a much lighter core install (lazy AI SDK imports).

**[Full Release Notes →](docs/releasenotes/v2.7.0.md)**

---

## [2.6.2] - Agent-Evaluation Differentiation + Multi-Agent & Multimodal Annotation

13 new annotation schemas pushing Potato beyond parity with LangSmith/LabelBox: multi-agent team annotation (clickable `agent_interaction_graph`, `failure_attribution`, `handoff_review`, `agent_scorecard`, `tool_contention`, `emergent_behavior`) and multimodal-agent annotation (`gui_trajectory`, `voice_interaction`, `temporal_grounding`, `speech_transcript`, `multimodal_reasoning`, `tool_call_review`, `table_grid`). Plus new evaluators (`rubric_dag`, `rag_triad`, `agent_as_judge`), judge bias/robustness eval cards (verbosity, position-swap, ECE), statistical rigor (bootstrap CIs, Wilson intervals, paired significance, Dawid–Skene), an Elo/Bradley–Terry model arena with DPO export, failure-mode discovery, LLM-cheating detection, perspectivist export, and reward/active-sampling/metric-induction/prompt-optimization. Fixes to `agent_interaction_graph`, `trajectory_eval`, and `table_grid`, plus an example-integrity guard. 53 schema types total.

**[Full Release Notes →](docs/releasenotes/v2.6.2.md)**

---

## [2.6.1] - Agentic Evaluation Suite (G1–G10)

A full agent-evaluation loop on top of the annotation core: programmatic evaluators (`potato.evaluators`), versioned datasets & experiments, the `potato_trace` tracing SDK with OpenTelemetry export, an automation-rules engine, a CI pytest plugin with threshold gating, automated judge calibration with span/free-text judging, `eval_trace` span annotation, semantic curation (Catalog), and a provider-agnostic multi-model arena — capture → automate → curate → evaluate → gate → calibrate.

**[Full Release Notes →](docs/releasenotes/v2.6.1.md)**

---

## [2.6.0] - QDA Mode, LLM-as-Judge Calibration & Trajectory Editing

Interactive Qualitative Data Analysis (QDA) Mode (universal persistence, memos, FTS5 search, a living codebook with cases, in-vivo coding, and retroactive curation), an LLM-as-judge calibration/alignment workflow with a signal-based triage queue, `trajectory_edit`/`trajectory_correction` schemas for SFT/DPO data, the `eval_trace` three-pane display, relicensing to GPL-3.0-or-later, and a large robustness wave (F-022–F-051).

**[Full Release Notes →](docs/releasenotes/v2.6.0.md)**

---

## [2.5.0] - Qualitative-Coding Wave

Cohen's and Fleiss' kappa for inter-annotator agreement, `codebook` and `quotation_report` exporters, and code co-occurrence/crosstab admin analytics endpoints.

**[Full Release Notes →](docs/releasenotes/v2.5.0.md)**

---

## [2.4.5] - Validated Refinement, Config Validator & Stability

Pluggable validated-refinement framework for solo-mode guideline improvement, a config-validator CLI, a path-traversal security fix (GHSA-q9m2-fhv9-3jcf), documentation reorganization, and a broad set of navigation, Prolific, and solo-mode fixes.

**[Full Release Notes →](docs/releasenotes/v2.4.5.md)**

---

## [2.4.4] - Span Annotation Fixes & UX Improvements

Fixed span overlay misalignment (overlays rendering on wrong line of text), text-node offset pollution from overlay labels, and fragile indexOf-based positioning. Added auto-selection of single span labels on page load.

**[Full Release Notes →](docs/releasenotes/v2.4.4.md)**

---

## [2.4.3] - Coding Agent Annotation, Localization & Stability

Live coding agent mode with 3 backends and checkpoint/rollback, 15 new schema types, expanded localization with RTL support, modernized CLI, auto-export, and numerous bug fixes.

**[Full Release Notes →](docs/releasenotes/v2.4.3.md)**

---

## [2.4.1] - Bug Fixes

Fixed non-annotation pages stuck on loading screen and solo mode stability improvements.

**[Full Release Notes →](docs/releasenotes/v2.4.1.md)**

---

## [2.4.0] - Agent Evaluation, AI-Assisted Annotation & Enterprise Integration

Web agent annotation, live agent evaluation, LLM chat sidebar, advanced active learning, webhook system, HuggingFace ecosystem integration, LangChain callback handler, SSO/OAuth, and 200+ new tests.

**[Full Release Notes →](docs/releasenotes/v2.4.0.md)**

---

## [2.3.0] - Solo Mode, Agent Workflows & Security Hardening

Solo annotation mode with cascaded confidence escalation, agentic workflow evaluation with 6 trace converters, SSO/OAuth authentication, Parquet export, 12 critical security fixes, and 85 solo mode tests.

**[Full Release Notes →](docs/releasenotes/v2.3.0.md)**

---

## [2.2.0] - Comprehensive Annotation & Export Platform

9 new annotation schemas, MACE annotator competence estimation, diversity ordering, pluggable export system with 8 formats, extended remote data sources, standard survey instruments, and annotation navigation.

**[Full Release Notes →](docs/releasenotes/v2.2.0.md)**

---

## [2.1.0] - Adjudication & Multi-Modal Annotation

Complete adjudication workflow, flexible instance display system, multi-field span annotation, span linking, and visual AI support.

**[Full Release Notes →](docs/releasenotes/v2.1.0.md)**

---

## [2.0.0] - Backend Refactor

Major architectural overhaul with new state management, AI support, active learning, training phase, database backend, enhanced admin dashboard, and security enhancements.

**[Full Release Notes →](docs/releasenotes/v2.0.0.md)**

---

## Migration

See [MIGRATION.md](MIGRATION.md) for detailed instructions on upgrading from v1.x to v2.0.0.

## New Features Guide

See [docs/new_features_v2.md](docs/new_features_v2.md) for detailed documentation on new features.
