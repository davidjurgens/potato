# Changelog

All notable changes to the Potato annotation platform are documented in this file.

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
