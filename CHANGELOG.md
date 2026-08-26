# Changelog

All notable changes to the Potato annotation platform are documented in this file.

## [2.8.1] - Security Fixes

Closes five security issues: three reported privately against 2.8.0, and two
found while fixing those. **Upgrade if you run Potato anywhere other than
localhost.**

**Unauthenticated SSRF** through `/api/audio/proxy` and the two waveform
endpoints, which fetched any URL a caller supplied and, for the proxy, returned
the body, reaching cloud metadata services, internal APIs and anything else on
the host's network. All four now require a login and share one URL guard that
blocks private and metadata addresses, pins the resolved address against DNS
rebinding, and re-checks redirects.

**Unauthenticated remote code execution** through the live coding agent, whose
routes had no login check at all and whose replay endpoint executed
caller-supplied tool calls with `shell=True` on the host. The sandbox meant to
contain this did not: `sandbox_mode: docker` was never implemented and silently
fell back to no isolation, and the default `worktree` is a git worktree on the
same host as the same user. Rebuilt as a ladder that never falls back and checks at startup:
`container` (Docker or Podman, no network, read-only root, unprivileged,
optionally gVisor or Kata), `bubblewrap`, or `trusted` with an explicit
acknowledgement.

**Admin config readable without the admin key**: the endpoint authorized its
write branch and not its read branch. Found because the test harness had been
exercising the debug bypass rather than the real check.

**Trace-ingestion webhook accepted everyone** when no `api_key` was configured,
so enabling the feature disabled its authentication. Now fails closed.

**Debug mode on a reachable interface** no longer grants admin, no longer puts
the admin key in the rendered HTML, and no longer hands Flask's interactive
debugger to a non-loopback bind.

**Breaking:** `sandbox_mode` defaults to `container`, and `worktree`/`direct`
map to `trusted` and require `acknowledge_untrusted_code_execution: true`.
Existing live-coding-agent configs will not start until they choose a rung.
`output_annotation_format` is deprecated in favour of `export_annotation_format`
and folds automatically.

Also: server-side sidebar gating, quality-control items no longer eating an
annotator's quota, a required-but-hidden scheme no longer blocking saving,
sixteen schema types landing in their configured `layout.groups` group, an MCP
server and browser-backed `potato preview --screenshot`, and
`potato deploy local` / `potato deploy share`.

**[Full Release Notes →](docs/releasenotes/v2.8.1.md)**

---

## [2.8.0] - Vision, and the Statistics to Check It

Potato's image, video, 3D, embodied and world-model surfaces were rebuilt from a
thin layer over the text machinery into the main body of the tool, and the
agreement statistics were extended to cover them. **Chance-corrected agreement
over geometry and over time** — detection, localization, classification, a
geometry scale reported as σ and a KS test, STAPLE for latent mask consensus, and
temporal boundary agreement reported as a tolerance sweep rather than at one
threshold. This also fixed adjudication, which compared annotation *keys* and so
scored every image pair at 1.0: two annotators who agreed on nothing looked
unanimous and no image was ever routed for review.

Everything under it: five new geometry primitives (`polyline`, `keypoint_set`,
`ellipse`, `cuboid_2d`, `tubelet`) plus instance-keyed masks; **interactive
segmentation in the browser** with vendored ONNX Runtime Web, so a default
install segments with no GPU and no network; **text prompting** via Grounding
DINO and **SAM 2 video mask propagation** (measured at 0.974–0.979 IoU per frame
with no decay), behind a single model zoo; **deep zoom** with masks at the
source's full resolution; 15 importers and 29 exporters with a format matrix a
test keeps honest; media ingest for TIFF, HEIC, RAW, HEVC and ProRes; **point
clouds** with octree LOD, calibration and 2D projection, **depth maps**, and
orthographic slab views; **embodied episodes** (LeRobot v2, RLDS, HDF5, ROS
bags); **world-model rollout evaluation** with break-point agreement; and **VLM
grounding, pointing and region captioning**.

Also: threaded conversation rendering and ConvoKit import/export both ways;
opt-in keystroke logging with composed/transcribed/pasted detection; live
database ingestion ([#166](https://github.com/davidjurgens/potato/issues/166));
machine-checkable config and OpenAPI specs generated from the registries, with CI
failing on drift; the admin Instances tab de-quadratified (15.1 s → 23 ms at
2,000 items) with two columns that had never worked; every frontend asset
vendored, closing an offline break and a per-page-load IP leak to Google; and the
packaging fix from [#164](https://github.com/davidjurgens/potato/pull/164) —
**wheels from 2.7.1 and earlier were missing every template in a subdirectory**,
breaking solo mode, the admin pages, judge calibration and the corpus map for
anyone who installed from PyPI.

Single-select schemas no longer persist every value clicked
([#167](https://github.com/davidjurgens/potato/issues/167)), with
`potato repair-annotations` for already-corrupted state.

**Breaking:** image annotation keyboard shortcuts now follow V7 conventions by
default. Set `keybinding_profile: legacy` to keep the old table.

**[Full Release Notes →](docs/releasenotes/v2.8.0.md)**

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

See the [v2.0.0 release notes](docs/releasenotes/v2.0.0.md) for detailed documentation on new features.
