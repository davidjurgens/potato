# Potato Documentation

**Potato** is a **free, open-source, self-hosted annotation and agent-evaluation
platform** for NLP, agentic, and GenAI research. You configure tasks entirely in
YAML — no coding — to annotate text, audio, video, images, documents, and AI agent
traces, and to run a full agent-evaluation loop (programmatic evaluators, versioned
datasets/experiments, automation, CI gating, LLM-as-judge calibration, and a
multi-model arena) as a free alternative to LangSmith, LabelBox, and Braintrust.

**New here?** Start with the [FAQ](faq.md), the [Glossary](glossary.md), or the
[Quick Start](quick-start.md).

!!! tip "Looking for guides and tutorials?"
    This Read the Docs site is the **complete, version-matched technical reference** —
    every config option, the full HTTP API, and internals. For guided walkthroughs,
    use-cases, and higher-level docs, visit **[potatoannotator.com/docs](https://www.potatoannotator.com/docs)**.

---

## Guides

Role-based guides that walk you through Potato for your specific use case:

- [Getting Started Guide](guides/getting-started.md) - First-time setup and your first annotation project
- [Administrator Guide](guides/admin-guide.md) - Managing annotators, quality control, and monitoring
- [Developer Guide](guides/developer-guide.md) - Extending Potato, API integration, and custom schemas
- [Crowdsourcing Guide](guides/crowdsourcing-guide.md) - Running tasks on Prolific and MTurk
- [Agent Evaluation Guide](guides/agent-evaluation-guide.md) - Evaluating AI agents, coding agents, and web agents
- [AI-Assisted Annotation Guide](guides/ai-assisted-annotation-guide.md) - Using LLMs, active learning, and Solo Mode

## Getting Started

- [Quick Start](quick-start.md) - Get running in 5 minutes
- [Installation & Usage](deployment/usage.md) - Detailed setup guide
- [Reverse Proxy / URL Prefix](deployment/reverse-proxy.md) - Run behind a path-prefix proxy (`/app1/`)
- [Configuration Reference](configuration/configuration.md) - Complete config options
- [Comparison with Other Tools](comparison.md) - How Potato compares to alternatives

## Annotation Schemas

- **[Choosing the Right Annotation Type](annotation-types/choosing_annotation_types.md)** - Decision guide for selecting the best schema for your task
- [Schema Gallery](annotation-types/schemas_and_templates.md) - All annotation types with examples
- [Instance Display](annotation-types/instance_display.md) - Display images, video, audio, and text separately from annotation collection
- [Conditional Logic](configuration/conditional_logic.md) - Show/hide questions based on prior answers
- [Image Annotation](annotation-types/multimedia/image_annotation.md) - Bounding boxes, polygons, and landmarks
- [Audio Annotation](annotation-types/multimedia/audio_annotation.md) - Audio segmentation with waveform visualization
- [Audio Dialogue](annotation-types/multimedia/audio_dialogue.md) - Podcast/interview turn annotation: speaker bubbles, per-turn audio playback, ratings, spans, and cross-turn linking
- [Video Annotation](annotation-types/multimedia/video_annotation.md) - Frame-by-frame video labeling
- [Tiered Annotation](annotation-types/multimedia/tiered_annotation.md) - ELAN-style hierarchical multi-tier annotation
- [Triage](annotation-types/triage.md) - Rapid accept/reject/skip data curation interface
- [Entity Linking](annotation-types/text/entity_linking.md) - Link spans to external knowledge bases (Wikidata, UMLS)
- [Coreference Annotation](annotation-types/text/coreference_annotation.md) - Group mentions of the same entity
- [Conversation Tree Annotation](annotation-types/structured/conversation_tree_annotation.md) - Annotate hierarchical conversation structures
- [Format Support](annotation-types/format_support.md) - PDF, Word, code, and spreadsheet annotation
- [Span Linking](annotation-types/text/span_linking.md) - Relationship linking between text spans
- [Soft Label](annotation-types/measurement/soft_label.md) - Probability distribution across labels via constrained sliders
- [Confidence Annotation](annotation-types/measurement/confidence_annotation.md) - Pair any annotation with an explicit confidence rating
- [Constant Sum](annotation-types/measurement/constant_sum.md) - Allocate a fixed budget of points across categories
- [Semantic Differential](annotation-types/measurement/semantic_differential.md) - Bipolar adjective scales measuring connotative meaning
- [Ranking](annotation-types/comparison/ranking.md) - Drag-and-drop ordering of items by preference
- [Range Slider](annotation-types/measurement/range_slider.md) - Dual-thumb slider for selecting an acceptable min-max range
- [Hierarchical Multi-Label Selection](annotation-types/structured/hierarchical_multiselect.md) - Select labels from an expandable tree taxonomy
- [Visual Analog Scale (VAS)](annotation-types/measurement/vas.md) - Continuous analog scale for fine-grained magnitude estimation
- [Extractive QA](annotation-types/text/extractive_qa.md) - SQuAD-style answer span highlighting
- [Rubric Evaluation](annotation-types/measurement/rubric_eval.md) - Multi-criteria rubric grid for LLM evaluation
- [Text Edit / Post-Edit](annotation-types/text/text_edit.md) - Inline text editing with diff tracking
- [Error Span (MQM)](annotation-types/text/error_span.md) - Error annotation with typed severity and quality scoring
- [Card Sorting](annotation-types/structured/card_sort.md) - Drag-and-drop grouping of items into categories
- [Conjoint Analysis](annotation-types/comparison/conjoint.md) - Discrete choice between multi-attribute profiles
- [Pairwise Comparison](annotation-types/comparison/pairwise_annotation.md) - Binary or scale-based A/B comparisons
- [Multi-Dimensional Pairwise](annotation-types/comparison/multi_dimensional_pairwise.md) - Compare items on multiple axes simultaneously
- [Best-Worst Scaling](annotation-types/comparison/bws.md) - Select best and worst from tuples
- [Dialogue Annotation](annotation-types/structured/dialogue_annotation.md) - Multi-turn conversation annotation
- [Text Annotation](annotation-types/text/text_annotation.md) - Free-text input and rationale annotation
- [Event Annotation](annotation-types/text/event_annotation.md) - N-ary event structures with triggers and arguments
- [Trajectory Evaluation](agent-evaluation/trajectory_eval.md) - Per-step error annotation for agent traces

## Workflow & Quality

- [Annotation Navigation](workflow/annotation_navigation.md) - Navigation tools and status indicators
- [Task Assignment](advanced/task_assignment.md) - Assignment strategies and configuration
- [Per-Cohort Schemas](advanced/per_cohort_schemas.md) - Show different annotation schemes to different annotator cohorts
- [Heterogeneous Coverage](advanced/heterogeneous_coverage.md) - Single-annotator default with a multi-annotator overlap sample, adaptive boost, per-annotator quotas, and full IAA reporting
- [Diversity Ordering](workflow/diversity_ordering.md) - Embedding-based clustering for diverse item presentation
- [Multi-Document Event Annotation](advanced/multi_document_events.md) - Cross-document events with a 2D corpus map, cluster browser, KNN, and evidence-cited template slots
- [Training Phase](workflow/training_phase.md) - Annotator training and qualification
- [Quality Control](workflow/quality_control.md) - Attention checks and gold standards
- **[Boundary Lab](advanced/boundary_lab.md)** - Counterfactual boundary probing: collect contrast sets during ordinary annotation, capture boundary rationales, and get paraphrase-invariance quality control
- **[Truth Serum](advanced/truth_serum.md)** - Surprisingly-popular scoring: gold-free item verdicts that beat majority vote, plus annotator calibration
- **[Paper Mode](advanced/paper_mode.md)** - One command generates a cut-paste LaTeX dataset report: description, distributions, annotator table, IAA, limitations
- **[Think-Aloud Mode](advanced/think_aloud.md)** - Voice rationales with fully-local STT and rule-based spoken-label commitment; verbatim reasoning streams, no LLM
- **[Pocket Mode](advanced/pocket_mode.md)** - Mobile-first card-stack annotation PWA: thumb-zone labels, swipe navigation, offline queue with auto-sync
- **[Psychometrics](advanced/psychometrics.md)** - Labels with error bars: live IRT (ability + difficulty, no gold, no LLM), information-gain adaptive routing, codebook-bug detection, and pre-study power analysis
- **[Multiplayer Rooms](advanced/multiplayer_rooms.md)** - Live group annotation: blind-vote norming sessions with a real-time agreement meter and conformity logging, adjudication huddles, and expert shadowing
- [Adjudication](administration/adjudication.md) - Multi-annotator disagreement resolution
- [MACE](advanced/mace.md) - Multi-Annotator Competence Estimation via variational inference
- [Iterative BWS](annotation-types/comparison/iterative_bws.md) - Adaptive Best-Worst Scaling for fine-grained ordinal rankings
- [Category Assignment](advanced/category_assignment.md) - Category-based item assignment
- [Surveyflow](workflow/surveyflow.md) - Pre/post annotation surveys
- [Annotation Filtering](workflow/annotation_filtering.md) - Filter data based on prior annotations
- [Survey Instruments](advanced/survey_instruments.md) - 55 pre-built validated psychological instruments
- **[QDA Mode](advanced/qda.md)** - Qualitative data analysis workspace: composes codebook + memos + cases + search with single-coder defaults
- [Memos](advanced/memos.md) - Universal annotator notes (instance/span-anchored, private/shared)
- [Search](advanced/search.md) - Universal FTS5 search; admin search + guarded annotator search-and-claim
- [Codebook](advanced/codebook.md) - Universal mutable code set (nested, opt-in per scheme, on-the-fly add)
- [Cases](advanced/cases.md) - Group instances into units of analysis; QDA auto-detect; crosstab integration

## Agent Evaluation

- **[Coding Agent Annotation](agent-evaluation/coding_agent_annotation.md)** - Evaluate agentic coding systems (Claude Code, SWE-Agent, Aider) with diff rendering, PRM annotation, and code review
- **[CoT Process Reward (LLM pre-label + verify)](agent-evaluation/process_reward_cot.md)** - Segment a long chain-of-thought into steps, have an LLM pre-label each step's reward, and have a human verify — fast PRM data collection
- [Agent Traces](agent-evaluation/agent_traces.md) - Evaluate AI agent traces and trajectories
- [Turn-Level Annotation](agent-evaluation/turn_level_annotation.md) - Bind any rating/tagging/comment schema per-turn with declarative filters (by speaker, agent, step type, tool)
- [Multi-Agent Discussion](agent-evaluation/multi_agent_discussion.md) - Annotate agent-to-agent discussions/debates with agent identity, addressees, reply threading, and consensus tracking
- [Agent Task Recipes](agent-evaluation/agent_task_recipes.md) - Ready-to-run configs: debate judging, plan review, negotiation, safety escalation, context-use annotation
- [Session-Level Scoring](agent-evaluation/session_level_scoring.md) - Group traces by session_id/thread_id and score whole sessions on a dedicated queue page
- [Sub-Agent Run Tree](agent-evaluation/run_tree.md) - Interactive run-hierarchy sidebar for orchestrator traces; bind per-turn schemes to specific sub-agent runs
- [Reviewer Routing + Kanban](agent-evaluation/review_workflow.md) - Route instances to reviewers with first-match rules; track review states on a kanban board with adjudication handoff
- [Three-Pane Trace Eval](agent-evaluation/eval_trace.md) - Reasoning | function calls | final answer side-by-side, for continuous evaluation
- [Trajectory Correction](agent-evaluation/trajectory_correction.md) - Edit traces into SFT/DPO training data
- [Datasets & Experiments](agent-evaluation/datasets_and_experiments.md) - Versioned eval datasets + experiment runs that score outputs over time
- [Programmatic Evaluators](agent-evaluation/evaluators.md) - Trajectory match, tool-use, LLM-judge & heuristic evaluators (Flask-free library)
- [Automation Rules](agent-evaluation/automation_rules.md) - filter→sample→action rules that route incoming items to queues/datasets/evaluators (production→eval loop)
- [CI Evaluation](agent-evaluation/ci_evaluation.md) - pytest plugin to run evals in your suite and gate the build on score-threshold regressions
- [Semantic Curation](agent-evaluation/semantic_curation.md) - embedding search + dynamic slices to find traces by similarity and curate them into datasets
- [LLM-Judge ↔ Human Alignment](agent-evaluation/judge_alignment.md) - Measure & calibrate an LLM judge against human gold (Cohen's κ)
- [Signal-Based Triage Queue](agent-evaluation/triage_queue.md) - Prioritize the queue by a quality signal (errors / low score first)
- [Hotkey Review Mode](guides/hotkey_review_mode.md) - Keyboard-driven review queue with auto-advance on completion
- [Live Agent Interaction](agent-evaluation/live_agent.md) - Observe and interact with a live AI agent in real time
- [Model Arena](agent-evaluation/model_arena.md) - Compare N models side by side on one prompt; pick the best, build a win-rate leaderboard (provider-agnostic)
- [Web Agent Annotation](agent-evaluation/web_agent_annotation.md) - Review and create web agent browsing traces

## Solo Mode

- [Solo Mode](solo-mode/solo_mode.md) - Human-LLM collaborative annotation workflow
- [Solo Mode Advanced Features](solo-mode/solo_mode_advanced.md) - Edge case rules, labeling functions, confidence routing
- [Solo Mode Developer Guide](solo-mode/solo_mode_developer_guide.md) - Architecture and extension points

## AI & Intelligence

- [AI Support](ai-intelligence/ai_support.md) - AI-powered label suggestions
- [Using HuggingFace Models](ai-intelligence/huggingface_models.md) - Point AI hints, solo mode, and judge calibration at any HF model
- [Judge Calibration](ai-intelligence/judge_calibration.md) - Auto-label with LLM judges + blind human calibration (accuracy, IAA, ECE)
- [Active Learning](ai-intelligence/active_learning_guide.md) - ML-based prioritization
- [Active Learning Strategies](ai-intelligence/active_learning_strategies.md) - Query strategies reference (BADGE, BALD, hybrid, cold-start)
- [ICL Labeling](ai-intelligence/icl_labeling.md) - In-context learning for labeling
- [Visual AI Support](ai-intelligence/visual_ai_support.md) - YOLO and vision LLM support for image/video annotation
- [Chat Support](ai-intelligence/chat_support.md) - LLM-powered sidebar for annotator assistance
- [Option Highlighting](ai-intelligence/option_highlighting.md) - AI-assisted highlighting of likely annotation options
- [Embedding Visualization](advanced/embedding_visualization.md) - UMAP-based instance similarity dashboard

## Authentication & User Management

- [Users & Collaboration](auth-users/user_and_collaboration.md) - User registration, access control, and collaboration
- [Roles & Permissions (RBAC)](auth-users/roles_and_permissions.md) - Role-based access control: role→permission mapping, per-user and SSO role assignment
- [Password Management](auth-users/password_management.md) - Password security, reset flows, database backend, and shared credentials
- [Passwordless Login](auth-users/passwordless_login.md) - Authentication without passwords
- [SSO & OAuth Authentication](auth-users/sso_authentication.md) - Google, GitHub, and institutional SSO login

## Crowdsourcing

- [Crowdsourcing Guide](deployment/crowdsourcing.md) - Prolific and MTurk integration
- [MTurk Integration](deployment/mturk_integration.md) - Detailed Amazon MTurk setup guide

## Administration

- [Scaling & Large Datasets](deployment/scaling.md) - How Potato handles big datasets, indexing, memory, and bulk exports
- [Admin Dashboard](administration/admin_dashboard.md) - Monitoring and management
- [Annotator Progress Dashboard](administration/annotator_dashboard.md) - Opt-in, read-only progress view for annotators
- [Behavioral Tracking](advanced/behavioral_tracking.md) - User behavior analytics
- [Annotation History](administration/annotation_history.md) - Tracking annotation changes

## Data & Output

- [Data Format](configuration/data_format.md) - Input and output data formats
- [Export Formats](data-export/export_formats.md) - Export to COCO, YOLO, CoNLL, and more
- [HuggingFace Hub Export](data-export/huggingface_export.md) - Push annotations to HuggingFace Hub
- [HuggingFace Datasets Integration](data-export/datasets_integration.md) - Load annotations as DatasetDict or DataFrame
- [Remote Data Sources](configuration/remote_data_sources.md) - Load data from S3, Google Drive, Dropbox, URLs, and databases
- [Data Directory](configuration/data_directory.md) - Load data from a directory with optional live watching

## UI & Customization

- [UI Configuration](configuration/ui_configuration.md) - Interface customization
- [Layout Customization](configuration/layout_customization.md) - Custom CSS layouts and styling
- [Form Layout](configuration/form_layout.md) - Grid layout, column spanning, styling, and alignment
- [Multilingual](configuration/multilingual.md) - Localization and RTL support

## Integrations

- [Webhooks](integrations/webhooks.md) - Outgoing webhook notifications for annotation events
- [HuggingFace Spaces](data-export/huggingface_spaces.md) - Deploy Potato on HuggingFace Spaces
- [LangChain Integration](integrations/langchain_integration.md) - Send LangChain agent traces to Potato
- [Tracing SDK (`potato_trace`)](integrations/tracing_sdk.md) - Instrument any agent with `@traceable` to capture runs into Potato (OpenTelemetry interop)

## Tools & Utilities

- [Preview CLI](tools/preview_cli.md) - Preview configs without running server
- [Migration CLI](tools/migration_cli.md) - Upgrade v1 configs to v2
- [Debugging Guide](tools/debugging_guide.md) - Debug flags and troubleshooting
- [Simulator](tools/simulator.md) - Annotation simulation tool
- [API Reference](api-reference/api_reference.md) - REST API endpoints documentation

## Productivity Features

- [Productivity](administration/productivity.md) - Tooltips, shortcuts, and highlights

## Release Notes

- [v2.7.0](releasenotes/v2.7.0.md) - Seven New Ways to Annotate (Psychometrics, Multiplayer Rooms, Boundary Lab, Truth Serum, Think-Aloud, Paper Mode, Pocket Mode)
- [v2.6.1](releasenotes/v2.6.1.md) - Agentic Evaluation Suite (evaluators, datasets/experiments, automation, CI gating, tracing SDK, curation, arena)
- [v2.6.0](releasenotes/v2.6.0.md) - QDA Mode, LLM-as-Judge Calibration & Trajectory Editing
- [v2.4.4](releasenotes/v2.4.4.md) - Span Annotation Fixes & UX Improvements
- [v2.4.3](releasenotes/v2.4.3.md) - Coding Agent Annotation, Localization & Stability
- [v2.4.1](releasenotes/v2.4.1.md) - Bug Fixes
- [v2.4.0](releasenotes/v2.4.0.md) - Agent Evaluation, AI-Assisted Annotation & Enterprise Integration
- [v2.3.0](releasenotes/v2.3.0.md) - Solo Mode, Agent Workflows & Security Hardening
- [v2.2.0](releasenotes/v2.2.0.md) - Comprehensive Annotation & Export Platform
- [v2.1.0](releasenotes/v2.1.0.md) - Adjudication & Multi-Modal Annotation
- [v2.0.0](releasenotes/v2.0.0.md) - Backend Refactor

## Contributing

- [Contributing Guide](deployment/open-sourcing.md) - How to contribute to Potato

---

## Quick Links

| Task | Documentation |
|------|---------------|
| Set up a basic annotation task | [Quick Start](quick-start.md) |
| Choose an annotation type | [Schema Gallery](annotation-types/schemas_and_templates.md) |
| Display images/video with radio buttons | [Instance Display](annotation-types/instance_display.md) |
| Show/hide questions based on answers | [Conditional Logic](configuration/conditional_logic.md) |
| Annotate PDFs, Word docs, or code | [Format Support](annotation-types/format_support.md) |
| Set up SSO/OAuth login | [SSO Authentication](auth-users/sso_authentication.md) |
| Reset a user's password | [Password Management](auth-users/password_management.md) |
| Use a database for user storage | [Password Management](auth-users/password_management.md#database-authentication-backend) |
| Configure for MTurk | [MTurk Integration](deployment/mturk_integration.md) |
| Configure for Prolific | [Crowdsourcing Guide](deployment/crowdsourcing.md#prolific-integration) |
| Monitor annotation progress | [Admin Dashboard](administration/admin_dashboard.md) |
| Add AI suggestions | [AI Support](ai-intelligence/ai_support.md) |
| Set up quality control | [Quality Control](workflow/quality_control.md) |
| Present items diversely | [Diversity Ordering](workflow/diversity_ordering.md) |
| Debug configuration issues | [Debugging Guide](tools/debugging_guide.md) |
| Create custom visual layouts | [Layout Customization](configuration/layout_customization.md) |
| Rapidly filter/triage data | [Triage](annotation-types/triage.md) |
| Link entities to knowledge bases | [Entity Linking](annotation-types/text/entity_linking.md) |
| Annotate coreference chains | [Coreference Annotation](annotation-types/text/coreference_annotation.md) |
| Annotate conversation trees | [Conversation Tree Annotation](annotation-types/structured/conversation_tree_annotation.md) |
| Navigate efficiently through items | [Annotation Navigation](workflow/annotation_navigation.md) |
| Evaluate AI agent traces | [Agent Traces](agent-evaluation/agent_traces.md) |
| See reasoning, tool calls & answer side-by-side | [Three-Pane Trace Eval](agent-evaluation/eval_trace.md) |
| Edit agent traces into SFT/DPO training data | [Trajectory Correction](agent-evaluation/trajectory_correction.md) |
| Build versioned eval sets & track scores over time | [Datasets & Experiments](agent-evaluation/datasets_and_experiments.md) |
| Score agent outputs programmatically | [Programmatic Evaluators](agent-evaluation/evaluators.md) |
| Capture agent runs from your own code | [Tracing SDK](integrations/tracing_sdk.md) |
| Auto-route incoming traces to queues/datasets/evals | [Automation Rules](agent-evaluation/automation_rules.md) |
| Gate CI on eval-score regressions | [CI Evaluation](agent-evaluation/ci_evaluation.md) |
| Find traces by similarity / curate slices | [Semantic Curation](agent-evaluation/semantic_curation.md) |
| Compare models side by side on a prompt | [Model Arena](agent-evaluation/model_arena.md) |
| Align/calibrate an LLM judge to human labels | [Judge Alignment](agent-evaluation/judge_alignment.md) |
| Auto-label with LLM judges + calibrate blind | [Judge Calibration](ai-intelligence/judge_calibration.md) |
| Use Solo Mode for collaborative annotation | [Solo Mode](solo-mode/solo_mode.md) |
| Export annotations to Parquet | [Export Formats](data-export/export_formats.md#parquet) |
| Export to COCO/YOLO/CoNLL | [Export Formats](data-export/export_formats.md) |
| Push annotations to HuggingFace Hub | [HuggingFace Export](data-export/huggingface_export.md) |
| Deploy on HuggingFace Spaces | [HuggingFace Spaces](data-export/huggingface_spaces.md) |
| Run behind a `/app1/` reverse proxy | [Reverse Proxy / URL Prefix](deployment/reverse-proxy.md) |
| Set up webhook notifications | [Webhooks](integrations/webhooks.md) |
| Use LLM chat assistant for annotators | [Chat Support](ai-intelligence/chat_support.md) |
| Evaluate coding agents | [Coding Agent Annotation](agent-evaluation/coding_agent_annotation.md) |
| Review web agent traces | [Web Agent Annotation](agent-evaluation/web_agent_annotation.md) |
| Load data from S3/GDrive/Dropbox | [Remote Data Sources](configuration/remote_data_sources.md) |
| Use pre-built survey instruments | [Survey Instruments](advanced/survey_instruments.md) |
| Set up multilingual interface | [Multilingual](configuration/multilingual.md) |
| Resolve annotator disagreements | [Adjudication](administration/adjudication.md) |
| Browse the REST API | [API Reference](api-reference/api_reference.md) |

---

## Example Projects

Ready-to-use example configurations are available in the `examples/` directory:

```bash
# Run a simple radio button example
python potato/flask_server.py start examples/classification/single-choice/config.yaml -p 8000

# Run a sophisticated layout example (content moderation, dialogue QA, medical review)
python potato/flask_server.py start examples/custom-layouts/content-moderation/config.yaml -p 8000
```

See the [examples](https://github.com/davidjurgens/potato/tree/main/examples) directory for more examples, including:

- `classification/` - Classification annotation examples (radio, checkbox, likert, etc.)
- `span/` - Span annotation examples (NER, linking, coreference, etc.)
- `image/` - Image annotation examples
- `video/` - Video annotation examples
- `audio/` - Audio annotation examples
- `advanced/` - Advanced features (conditional logic, quality control, etc.)
- `agent-traces/` - Agent trace evaluation examples (RAG, GUI agents, comparisons)
- `custom-layouts/` - Sophisticated custom layout examples

---

## Citation

If you use Potato in your research, please cite the **Potato 2.0** paper
([ACL 2026 System Demonstrations](https://aclanthology.org/2026.acl-demo.37/)):

```bibtex
@inproceedings{jurgens-etal-2026-potato,
    title = "Potato 2.0: A Comprehensive Annotation Platform with {AI}-in-the-Loop Support",
    author = "Jurgens, David  and Chen, Michael  and Iyer, Lina",
    booktitle = "Proceedings of the 64th Annual Meeting of the Association for Computational Linguistics (Volume 3: System Demonstrations)",
    month = jul,
    year = "2026",
    address = "San Diego, California, United States",
    publisher = "Association for Computational Linguistics",
    url = "https://aclanthology.org/2026.acl-demo.37/",
    pages = "374--386",
}
```

The original Potato release is described in the **Potato 1.0** paper
([EMNLP 2022 System Demonstrations](https://aclanthology.org/2022.emnlp-demos.33/),
Pei et al., 2022). See the [README](https://github.com/davidjurgens/potato#citation)
for both BibTeX entries.
