# Potato Annotation Examples

Ready-to-use annotation templates organized by type. Each example is self-contained with its own `config.yaml` and `data/` directory.

## Running an Example

From the repository root:

```bash
python potato/flask_server.py start examples/classification/check-box/config.yaml -p 8000
```

Then open [http://localhost:8000](http://localhost:8000).

For quick debugging (skip login/consent screens):

```bash
python potato/flask_server.py start examples/classification/check-box/config.yaml -p 8000 --debug --debug-phase annotation
```

## Categories

### [classification/](classification/) - Label Selection & Rating

| Example | Description |
|---------|-------------|
| `check-box/` | Multi-label checkbox selection |
| `check-box-dynamic-labels/` | Checkboxes with dynamic label generation |
| `check-box-with-free-response/` | Checkboxes with free text option |
| `single-choice/` | Single-choice radio buttons |
| `likert/` | Likert scale ratings |
| `slider/` | Numeric slider input |
| `two-sliders/` | Multiple slider inputs |
| `multirate/` | Rating matrix (multiple items x scales) |
| `text-box/` | Free text input |
| `best-worst-scaling/` | Best-worst scaling comparison |
| `pairwise-comparison/` | Side-by-side pairwise comparison |
| `pairwise-scale/` | Pairwise comparison with scale rating |
| `llm-preference/` | LLM output preference comparison |
| `dialogue-classification/` | Dialogue-level classification |
| `survey-demo/` | Multi-question survey instrument |

### [span/](span/) - Text Span Annotation

| Example | Description |
|---------|-------------|
| `span-labeling/` | Basic text span highlighting and labeling |
| `span-labeling-with-abbreviations/` | Span labeling with abbreviation expansion |
| `span-required-labeling/` | Required span annotation |
| `multi-span/` | Multiple span types in one task |
| `span-linking/` | Annotate relationships between spans |
| `coreference/` | Coreference chain annotation |
| `entity-linking/` | Entity linking to knowledge base |
| `segmentation/` | Text segmentation |
| `dependency-tree/` | Dependency tree annotation |
| `conversation-tree/` | Conversation tree structure |
| `event-annotation/` | N-ary event annotation |

### [conversation/](conversation/) - Threaded Conversations & ConvoKit

Branching discussions — forum threads, talk pages, mailing lists — where a reply
answers a specific message rather than the one above it. Nesting is derived from
each turn's `reply_to`, so any threaded source works.

| Example | Description |
|---------|-------------|
| `threaded-forum/` | Reply-threaded discussion with whole-thread, per-comment, span, and cross-comment link annotation |
| `convokit-awry/` | [ConvoKit](https://convokit.cornell.edu/) Conversations Gone Awry: thread derailment plus per-comment labels |
| `convokit-politeness/` | ConvoKit Wikipedia Politeness: utterance-level items in the legacy corpus format |
| `convokit-tree/` | One conversation in two views — a branching tree and a flat thread |

The `convokit-*` examples download their corpus on first run (`./setup_data.sh`);
nothing large is committed. See [ConvoKit integration](../docs/integrations/convokit.md).

### [audio/](audio/) - Audio Annotation

| Example | Description |
|---------|-------------|
| `audio-annotation/` | Audio segmentation with waveforms |
| `audio-classification/` | Audio file classification |
| `audio-with-context/` | Audio annotation with text context |
| `tiered-annotation/` | Multi-tier audio annotation |

### [video/](video/) - Video Annotation

| Example | Description |
|---------|-------------|
| `video-annotation/` | Video segment annotation |
| `video-classification/` | Video file classification |
| `video-frame-annotation/` | Frame-by-frame annotation |
| `video-tracking/` | Object tracking in video |
| `mask-propagation/` | Draw once, then let SAM 2 track through an occlusion — needs `python make_clip.py` and ffmpeg |
| `video-as-label/` | Video clips as label options |

### [image/](image/) - Image & Document Annotation

| Example | Description |
|---------|-------------|
| `image-annotation/` | Image region annotation (boxes and polygons) |
| `coco-import/` | Correct imported COCO annotations — polygons, RLE masks, and crowd regions |
| `format-migration/` | The same dataset in COCO, YOLO, Pascal VOC and KITTI, with commands proving all four import to identical geometry |
| `geometry-primitives/` | Every drawing tool side by side, including open polylines and ellipses |
| `image-classification/` | Image classification |
| `image-ai-detection/` | AI-generated image detection |
| `image-vllm-rationale/` | Image annotation with vLLM rationale |
| `annotation-critique/` | A vision model reviews the regions you drew: wrong label, loose boundary, missed object |
| `region-captioning/` | One description per region, with agreement over the captions themselves — needs `python generate_images.py` first |
| `text-prompt-labeling/` | Type what to look for and the browser finds it — Grounding DINO, no GPU; needs `python fetch_images.py` first |
| `deep-zoom/` | Gigapixel images through a tile pyramid, with masks at full source resolution — needs `python generate_image.py` first |
| `pdf-annotation/` | PDF document annotation |
| `pdf-bbox/` | PDF bounding box annotation |
| `document-bbox/` | Document bounding box annotation |

### [spatial/](spatial/) - 3D Point Clouds

| Example | Description |
|---------|-------------|
| `kitti-cuboids/` | Oriented 3D boxes on a lidar scan — KITTI `.bin`, PCD, PLY and LAS all load |
| `depth-eval/` | Review a monocular depth prediction: window, colormap, and the distance under the cursor in metres |

### `embodied/` — robot demonstrations

| Example | What it shows |
|---|---|
| `lerobot-episode/` | Phases, outcome and dense progress reward on a multi-stream robot episode |

### `agent-traces/` — agent and world-model evaluation

| Example | What it shows |
|---|---|
| `world-model-rollouts/` | Frame-locked video panels: mark the frame where a generated rollout stops making sense, pick a winner, judge a counterfactual |

### [advanced/](advanced/) - Complex Features & Workflows

| Example | Description |
|---------|-------------|
| `all-annotation-types/` | Demo of every annotation type |
| `all-phases-example/` | Full workflow with all phases |
| `long-guidelines/` | Where annotator instructions live: instructions phase, collapsible banner, codebook button |
| `conditional-logic/` | Show/hide questions based on answers |
| `multi-modal/` | Multi-modal (text + image) annotation |
| `grid-layout/` | Grid-based annotation layout |
| `option-highlight/` | Dynamic keyword highlighting |
| `triage/` | Annotation triage workflow |
| `adjudication/` | Multi-annotator adjudication |
| `mace-demo/` | MACE aggregation demo |
| `active-learning/` | Active learning prioritization |
| `annotation-telemetry/` | Drawing dynamics: time per shape, zoom behaviour, revision, and AI-suggestion accept latency |
| `quality-control/` | Attention checks and gold standards |
| `mturk-example/` | Amazon MTurk integration |
| `diversity/` | Diversity-based ordering |
| `diversity-test/` | Diversity ordering test |
| `embedding-visualization/` | Embedding space visualization |
| `multi-document-events/` | Cross-document event annotation with a 2D corpus map, cluster browser, KNN, and evidence-cited template slots |
| `kwargs-example/` | Custom keyword arguments |
| `url-data/` | Loading data from URLs |
| `html-annotation/` | HTML content annotation |
| `code-annotation/` | Source code annotation |
| `spreadsheet-annotation/` | Tabular data annotation |

#### Qualitative coding (QDA)

| Example | Description |
|---------|-------------|
| `qda-mode-example/` | Composed QDA workspace: codebook + memos + cases + search via `qda_mode` |
| `codebook-example/` | Mutable, on-the-fly codebook (multiselect scheme) |
| `codebook-invivo-example/` | In-vivo coding: mint a code from a text selection (`i`) |
| `codebook-sidebar/` | Read-only per-label codebook (`codebook_mode: fixed`): definitions, use-when/avoid-when, examples |
| `memos-example/` | Annotator notes (instance/span-anchored, private/shared) |
| `cases-example/` | Group instances into units of analysis; crosstab by case attribute |
| `search-example/` | FTS5 search; admin search + annotator search-and-claim |

### [ai-assisted/](ai-assisted/) - AI/ML Integration

| Example | Description |
|---------|-------------|
| `span-ai-keywords-demo/` | AI-powered keyword suggestions for spans |
| `keyword-highlights/` | Smart keyword highlighting |
| `ollama-ai-demo/` | Local LLM integration via Ollama |

### [custom-layouts/](custom-layouts/) - Layout Customization

| Example | Description |
|---------|-------------|
| `custom-layout-example/` | Basic custom HTML layout |
| `category-assignment/` | Category assignment with custom layout |
| `icl-labeling/` | In-context learning labeling layout |
| `content-moderation/` | Content moderation task layout |
| `dialogue-qa/` | Dialogue QA task layout |
| `medical-review/` | Medical review task layout |

### [testing/](testing/) - Verification & Debug

| Example | Description |
|---------|-------------|
| `verify-span-labeling/` | Span labeling verification tests |
| `verify-format-displays/` | Format display verification |

### [simulator-configs/](simulator-configs/) - User Simulation

| File | Description |
|------|-------------|
| `simulator-random.yaml` | Random annotation behavior |
| `simulator-biased.yaml` | Biased annotation behavior |
| `simulator-ollama.yaml` | LLM-powered simulation via Ollama |

## Paper-Specific Projects

Research paper annotation projects are available in the **[Potato Showcase](https://github.com/davidjurgens/potato-showcase/)** repository.

<!-- BEGIN GENERATED INDEX -->

<!-- Generated by scripts/generate_examples_manifest.py. Do not edit by
     hand; edits are overwritten on the next run. Curated descriptions
     belong in the category sections above this marker. -->

## Complete Index

All 214 examples, generated from the configs themselves.
The `Types` column lists the annotation types each one uses.

### advanced/ (56)

| Example | Task | Types |
|---------|------|-------|
| [`active-learning/`](advanced/active-learning/) | Simple Active Learning Example | `radio` |
| [`active-learning-llm-cold-start/`](advanced/active-learning-llm-cold-start/) | Active Learning with LLM Cold-Start | `radio` |
| [`active-learning-strategies/`](advanced/active-learning-strategies/) | Active Learning Strategies Demo | `radio` |
| [`adjudication/`](advanced/adjudication/) | Sentiment Adjudication Demo | `multiselect`, `radio` |
| [`all-annotation-types/`](advanced/all-annotation-types/) | All Annotation Types Showcase | `likert`, `multirate`, `multiselect`, `number`, `pure_display`, `radio`, `select`, `slider`, `span`, `text` |
| [`all-phases-example/`](advanced/all-phases-example/) | All the Phases Annotations | `multiselect`, `radio`, `slider`, `span`, `text` |
| [`annotation-telemetry/`](advanced/annotation-telemetry/) | Annotation telemetry demo | `image_annotation` |
| [`annotator-progress/`](advanced/annotator-progress/) | Annotator Progress Dashboard Example | `radio` |
| [`boundary-probing/`](advanced/boundary-probing/) | Boundary Lab — Politeness | `radio` |
| [`boundary-probing-images/`](advanced/boundary-probing-images/) | Boundary Lab — Scene Setting | `radio` |
| [`cases-example/`](advanced/cases-example/) | Cases Example | `radio` |
| [`code-annotation/`](advanced/code-annotation/) | Code Quality Review | `multiselect`, `radio`, `text` |
| [`codebook-document-example/`](advanced/codebook-document-example/) | Codebook Document Example | `multiselect` |
| [`codebook-example/`](advanced/codebook-example/) | Codebook Example | `multiselect` |
| [`codebook-invivo-example/`](advanced/codebook-invivo-example/) | Codebook In-Vivo Example | `span` |
| [`codebook-sidebar/`](advanced/codebook-sidebar/) | Politeness — Codebook Sidebar | `radio` |
| [`conditional-logic/`](advanced/conditional-logic/) | Conditional Logic Demo - PII Detection | `multiselect`, `radio`, `slider`, `text` |
| [`dataset-publishing/`](advanced/dataset-publishing/) | Movie Review Sentiment | `multiselect`, `radio` |
| [`diversity/`](advanced/diversity/) | Topic Classification with Diversity Ordering | `radio` |
| [`diversity-test/`](advanced/diversity-test/) | Diversity Ordering Test (100 items, 5 themes) | `radio` |
| [`embedding-visualization/`](advanced/embedding-visualization/) | Embedding Visualization Demo | `radio` |
| [`full-study-skeleton/`](advanced/full-study-skeleton/) | Full Study Skeleton | `likert`, `radio`, `span`, `text` |
| [`grid-layout/`](advanced/grid-layout/) | Grid Layout Demo | `likert`, `multiselect`, `radio`, `text` |
| [`heterogeneous-coverage/`](advanced/heterogeneous-coverage/) | Heterogeneous Coverage Example | `radio`, `span` |
| [`hotkey-review/`](advanced/hotkey-review/) | Hotkey Trace Review | `radio` |
| [`html-annotation/`](advanced/html-annotation/) | Simple HTML as Input Example | `multiselect` |
| [`keystroke-calibration/`](advanced/keystroke-calibration/) | keystroke-calibration | `text` |
| [`keystroke-logging/`](advanced/keystroke-logging/) | keystroke-logging | `radio`, `text` |
| [`kwargs-example/`](advanced/kwargs-example/) | Example for using kwargs | `likert` |
| [`live-database-ingestion/`](advanced/live-database-ingestion/) | live-database-ingestion | `radio`, `text` |
| [`long-guidelines/`](advanced/long-guidelines/) | Politeness — Long Guidelines | `radio` |
| [`mace-demo/`](advanced/mace-demo/) | MACE Competence Estimation Demo | `radio` |
| [`memos-example/`](advanced/memos-example/) | Memos Example | `radio` |
| [`mturk-example/`](advanced/mturk-example/) | MTurk Annotation Task | `radio` |
| [`multi-document-events/`](advanced/multi-document-events/) | Cross-Document Disaster Events | `multi_document_event` |
| [`multi-modal/`](advanced/multi-modal/) | Video + Transcript Analysis | `radio`, `span` |
| [`multiplayer-rooms/`](advanced/multiplayer-rooms/) | Multiplayer Rooms — Norming Sarcasm Together | `radio` |
| [`oauth-login/`](advanced/oauth-login/) | OAuth Login Demo | `radio` |
| [`option-highlight/`](advanced/option-highlight/) | Emotion Classification with AI Highlighting | `radio` |
| [`pdf-link-paginated/`](advanced/pdf-link-paginated/) | PDF Linking — Paginated View | `radio` |
| [`pdf-link-scroll/`](advanced/pdf-link-scroll/) | PDF Linking — Scroll View | `radio` |
| [`per-cohort-schemas/`](advanced/per-cohort-schemas/) | Per-Cohort Schemas Example | `radio`, `text` |
| [`pocket-mode/`](advanced/pocket-mode/) | Pocket — Sentiment Triage | `radio` |
| [`psychometrics/`](advanced/psychometrics/) | Psychometrics — Sarcasm with Error Bars | `radio` |
| [`qda-mode-example/`](advanced/qda-mode-example/) | QDA Mode Example | `multiselect`, `span` |
| [`quality-control/`](advanced/quality-control/) | Sentiment Analysis with Quality Control | `radio` |
| [`review-workflow/`](advanced/review-workflow/) | Review Workflow | `radio` |
| [`search-example/`](advanced/search-example/) | Search Example | `radio` |
| [`showcase/`](advanced/showcase/) | Potato Showcase — Politeness | `radio` |
| [`solo-mode/`](advanced/solo-mode/) | sentiment-solo-demo | `radio` |
| [`spreadsheet-annotation/`](advanced/spreadsheet-annotation/) | Data Quality Annotation | `multiselect`, `text` |
| [`surveyflow-conditional-logic/`](advanced/surveyflow-conditional-logic/) | SurveyFlow Conditional Logic | `radio` |
| [`think-aloud/`](advanced/think-aloud/) | Think-Aloud — Politeness | `radio` |
| [`triage/`](advanced/triage/) | Simple Triage Example | `triage` |
| [`truth-serum/`](advanced/truth-serum/) | Truth Serum — Sarcasm | `radio` |
| [`url-data/`](advanced/url-data/) | URL Data Source Demo | `radio` |

### agent-testing/ (3)

| Example | Task | Types |
|---------|------|-------|
| [`coding-agent-docker-test/`](agent-testing/coding-agent-docker-test/) | Live Coding Agent (Docker sandbox) | `likert`, `radio`, `text` |
| [`coding-agent-live-test/`](agent-testing/coding-agent-live-test/) | Live Coding Agent (subprocess sandbox) | `likert`, `radio`, `text` |
| [`interactive-agent-test/`](agent-testing/interactive-agent-test/) | Interactive Agent Testing | `likert`, `radio`, `text` |

### agent-traces/ (57)

| Example | Task | Types |
|---------|------|-------|
| [`agent-comparison/`](agent-traces/agent-comparison/) | Agent Trace Comparison | `multirate`, `radio`, `text` |
| [`agent-scorecard/`](agent-traces/agent-scorecard/) | Multi-Agent Scorecard | `agent_scorecard` |
| [`agent-trace-evaluation/`](agent-traces/agent-trace-evaluation/) | Agent Trace Evaluation | `likert`, `multiselect`, `radio`, `span`, `text` |
| [`anthropic-evaluation/`](agent-traces/anthropic-evaluation/) | Anthropic Claude Trace Evaluation | `likert`, `radio`, `text` |
| [`automation-loop/`](agent-traces/automation-loop/) | Automation Loop | `radio` |
| [`coding-agent-comparison/`](agent-traces/coding-agent-comparison/) | Coding Agent Comparison | `likert`, `text` |
| [`coding-agent-evaluation/`](agent-traces/coding-agent-evaluation/) | Coding Agent Trace Evaluation | `likert`, `multiselect`, `radio`, `text` |
| [`coding-agent-prm/`](agent-traces/coding-agent-prm/) | Coding Agent PRM Annotation | `process_reward`, `radio` |
| [`coding-agent-review/`](agent-traces/coding-agent-review/) | Coding Agent Code Review | `code_review`, `text` |
| [`complex-annotation/`](agent-traces/complex-annotation/) | Agent Trace Evaluation | `likert`, `radio`, `span`, `text` |
| [`context-attribution/`](agent-traces/context-attribution/) | Agent Context-Use Annotation | `context_attribution`, `likert`, `radio` |
| [`continuous-eval/`](agent-traces/continuous-eval/) | Continuous Agent Evaluation | `likert`, `multiselect`, `radio`, `text` |
| [`cot-process-reward/`](agent-traces/cot-process-reward/) | Chain-of-Thought Process Reward | `process_reward`, `radio` |
| [`debate-judging/`](agent-traces/debate-judging/) | Debate Judging | `consensus_tracking`, `likert`, `radio`, `rubric_eval`, `text` |
| [`emergent-behavior/`](agent-traces/emergent-behavior/) | Emergent Behavior Tagging | `emergent_behavior` |
| [`experiments/`](agent-traces/experiments/) | Agent Eval — Datasets & Experiments | `radio` |
| [`failure-attribution/`](agent-traces/failure-attribution/) | Multi-Agent Failure Attribution | `failure_attribution`, `radio` |
| [`failure-taxonomy/`](agent-traces/failure-taxonomy/) | Agent Failure-Mode Taxonomy (MAST) | `hierarchical_multiselect`, `radio`, `text` |
| [`gui-trajectory/`](agent-traces/gui-trajectory/) | GUI Agent Trajectory Review | `gui_trajectory` |
| [`handoff-review/`](agent-traces/handoff-review/) | Agent Handoff Review | `handoff_review` |
| [`interaction-graph/`](agent-traces/interaction-graph/) | Agent Interaction Graph | `agent_interaction_graph` |
| [`judge-alignment/`](agent-traces/judge-alignment/) | Judge Alignment | `radio` |
| [`langchain-integration/`](agent-traces/langchain-integration/) | LangChain Agent Evaluation | `likert`, `radio`, `text` |
| [`live-agent-evaluation/`](agent-traces/live-agent-evaluation/) | Live Agent Evaluation | `radio`, `text` |
| [`live-coding-agent/`](agent-traces/live-coding-agent/) | Live Coding Agent Evaluation | `likert`, `process_reward`, `radio`, `text` |
| [`mast-step-tagging/`](agent-traces/mast-step-tagging/) | MAST Step Tagging | `trajectory_eval` |
| [`model-arena/`](agent-traces/model-arena/) | Model Arena | `radio` |
| [`multi-agent-discussion/`](agent-traces/multi-agent-discussion/) | Multi-Agent Discussion Review | `consensus_tracking`, `likert`, `radio`, `text` |
| [`multi-agent-evaluation/`](agent-traces/multi-agent-evaluation/) | Multi-Agent Trace Evaluation | `likert`, `multiselect`, `radio`, `text` |
| [`multi-dim-comparison/`](agent-traces/multi-dim-comparison/) | Multi-Dimensional Agent Comparison | `pairwise` |
| [`multimodal-reasoning/`](agent-traces/multimodal-reasoning/) | Multimodal Reasoning Review | `multimodal_reasoning` |
| [`negotiation-review/`](agent-traces/negotiation-review/) | Negotiation Review | `consensus_tracking`, `likert`, `multiselect`, `radio`, `slider` |
| [`openai-evaluation/`](agent-traces/openai-evaluation/) | OpenAI Trace Evaluation | `likert`, `radio`, `text` |
| [`orchestration-pattern/`](agent-traces/orchestration-pattern/) | Orchestration Pattern | `radio` |
| [`per-turn-binding/`](agent-traces/per-turn-binding/) | Per-Turn Schema Binding | `likert`, `multiselect`, `radio` |
| [`plan-review/`](agent-traces/plan-review/) | Agent Plan Review | `multiselect`, `radio`, `rubric_eval`, `trajectory_edit` |
| [`rag-evaluation/`](agent-traces/rag-evaluation/) | RAG Pipeline Evaluation | `likert`, `multirate`, `radio`, `span`, `text` |
| [`safety-escalation/`](agent-traces/safety-escalation/) | Agent Safety Escalation Review | `failure_attribution`, `multiselect`, `radio`, `triage` |
| [`sdk-capture/`](agent-traces/sdk-capture/) | SDK Capture — Agent Traces | `radio` |
| [`semantic-curation/`](agent-traces/semantic-curation/) | Semantic Curation | `radio` |
| [`session-scoring/`](agent-traces/session-scoring/) | Session-Level Scoring | `likert`, `multiselect`, `radio`, `text` |
| [`speech-transcript/`](agent-traces/speech-transcript/) | Speech Transcript Error Tagging | `speech_transcript` |
| [`sub-agent-tree/`](agent-traces/sub-agent-tree/) | Sub-Agent Run Tree | `likert`, `multiselect`, `radio` |
| [`swebench-evaluation/`](agent-traces/swebench-evaluation/) | SWE-bench Patch Evaluation | `likert`, `multiselect`, `radio`, `text` |
| [`table-grid/`](agent-traces/table-grid/) | Table Structure Annotation | `table_grid` |
| [`temporal-grounding/`](agent-traces/temporal-grounding/) | Video Temporal Grounding | `temporal_grounding` |
| [`tool-call-review/`](agent-traces/tool-call-review/) | Tool-Call Review | `tool_call_review` |
| [`tool-contention/`](agent-traces/tool-contention/) | Tool Contention Review | `tool_contention` |
| [`trajectory-correction/`](agent-traces/trajectory-correction/) | Trajectory Correction | `multiselect`, `trajectory_edit` |
| [`trajectory-evaluation/`](agent-traces/trajectory-evaluation/) | Agent Trajectory Evaluation | `trajectory_eval` |
| [`triage-queue/`](agent-traces/triage-queue/) | Trace Triage | `radio` |
| [`visual-agent-evaluation/`](agent-traces/visual-agent-evaluation/) | Visual Agent Evaluation | `likert`, `multiselect`, `radio`, `text` |
| [`vlm-eval-backup/`](agent-traces/interactive-vlm-evaluation/vlm-eval-backup/) | Interactive VLM Web Agent Evaluation | `radio`, `text`, `trajectory_eval` |
| [`voice-interaction/`](agent-traces/voice-interaction/) | Voice Agent Turn-Taking | `voice_interaction` |
| [`web-agent-creation/`](agent-traces/web-agent-creation/) | Web Agent Trace Creation | `likert`, `radio`, `text` |
| [`web-agent-review/`](agent-traces/web-agent-review/) | Web Agent Trace Review | `likert`, `multiselect`, `radio`, `text` |
| [`world-model-rollouts/`](agent-traces/world-model-rollouts/) | World-model rollout evaluation | `rollout_evaluation`, `text` |

### ai-assisted/ (6)

| Example | Task | Types |
|---------|------|-------|
| [`grounding-eval/`](ai-assisted/grounding-eval/) | Grounding evaluation | `grounding_eval`, `image_annotation` |
| [`judge-calibration/`](ai-assisted/judge-calibration/) | Judge Calibration Demo | `radio` |
| [`keyword-highlights/`](ai-assisted/keyword-highlights/) | Sentiment Analysis with Keyword Highlights | `radio`, `span` |
| [`llm-chat/`](ai-assisted/llm-chat/) | Sentiment Classification with Chat Support | `radio` |
| [`ollama-ai-demo/`](ai-assisted/ollama-ai-demo/) | AI-Assisted Product Review Analysis | `radio` |
| [`span-ai-keywords-demo/`](ai-assisted/span-ai-keywords-demo/) | Span Annotation with AI & Admin Keywords | `span` |

### audio/ (7)

| Example | Task | Types |
|---------|------|-------|
| [`audio-annotation/`](audio/audio-annotation/) | Audio Segmentation Demo | `audio_annotation`, `radio` |
| [`audio-classification/`](audio/audio-classification/) | Audio Classification | `radio` |
| [`audio-dialogue/`](audio/audio-dialogue/) | Podcast Dialogue Annotation | `likert`, `radio`, `span`, `span_link` |
| [`audio-dialogue-sporc/`](audio/audio-dialogue-sporc/) | SPoRC Podcast Dialogue | `likert`, `radio`, `span`, `span_link` |
| [`audio-with-context/`](audio/audio-with-context/) | Audio Segmentation with Context | `audio_annotation` |
| [`tiered-annotation/`](audio/tiered-annotation/) | Tiered Annotation Example | `tiered_annotation` |
| [`transcript-formats/`](audio/transcript-formats/) | Transcript Formats | `radio`, `span` |

### classification/ (30)

| Example | Task | Types |
|---------|------|-------|
| [`best-worst-scaling/`](classification/best-worst-scaling/) | Sentiment Intensity BWS | `bws` |
| [`card-sort/`](classification/card-sort/) | Topic Card Sorting | `card_sort` |
| [`check-box/`](classification/check-box/) | Simple Check Box Example | `multiselect` |
| [`check-box-dynamic-labels/`](classification/check-box-dynamic-labels/) | Simple Check Box Dynamic Labels Example | `multiselect` |
| [`check-box-with-free-response/`](classification/check-box-with-free-response/) | Simple Check Box With Free Response Example | `multiselect` |
| [`confidence-calibrated/`](classification/confidence-calibrated/) | Confidence-Calibrated Sentiment Annotation | `confidence`, `radio` |
| [`conjoint/`](classification/conjoint/) | AI Assistant Preference Study | `conjoint` |
| [`constant-sum/`](classification/constant-sum/) | Constant-Sum Topic Relevance Allocation | `constant_sum` |
| [`dialogue-classification/`](classification/dialogue-classification/) | Dialogue Classification | `multiselect`, `radio` |
| [`error-span/`](classification/error-span/) | MQM Translation Quality Evaluation | `error_span` |
| [`extractive-qa/`](classification/extractive-qa/) | SQuAD-Style Extractive QA | `extractive_qa` |
| [`hierarchical-multiselect/`](classification/hierarchical-multiselect/) | Hierarchical Topic Classification | `hierarchical_multiselect` |
| [`iterative-bws/`](classification/iterative-bws/) | Sentiment Intensity (Iterative BWS) | `bws` |
| [`likert/`](classification/likert/) | Simple Likert Scale Example | `likert` |
| [`llm-preference/`](classification/llm-preference/) | LLM Response Quality Comparison | `pairwise`, `text` |
| [`multirate/`](classification/multirate/) | Simple Multirate Example | `multirate` |
| [`pairwise-comparison/`](classification/pairwise-comparison/) | Simple Pairwise Comparison Example | `pairwise` |
| [`pairwise-scale/`](classification/pairwise-scale/) | Pairwise Scale Comparison Example | `pairwise` |
| [`range-slider/`](classification/range-slider/) | Range Slider Formality Assessment | `range_slider` |
| [`ranking/`](classification/ranking/) | Response Quality Ranking | `ranking` |
| [`rubric-eval/`](classification/rubric-eval/) | LLM Response Quality Rubric | `rubric_eval` |
| [`semantic-differential/`](classification/semantic-differential/) | Semantic Differential Word Connotation | `semantic_differential` |
| [`single-choice/`](classification/single-choice/) | Simple Single-Choice Example | `radio` |
| [`slider/`](classification/slider/) | Simple Slider Example | `slider` |
| [`soft-label/`](classification/soft-label/) | Soft Label Sentiment Distribution | `soft_label` |
| [`survey-demo/`](classification/survey-demo/) | Survey Instruments Demo | `likert` |
| [`text-box/`](classification/text-box/) | Simple Text Box Example | `text` |
| [`text-edit/`](classification/text-edit/) | Machine Translation Post-Editing | `text_edit` |
| [`two-sliders/`](classification/two-sliders/) | Two Sliders Example | `slider` |
| [`vas/`](classification/vas/) | VAS Pain Level Rating | `vas` |

### conversation/ (4)

| Example | Task | Types |
|---------|------|-------|
| [`convokit-awry/`](conversation/convokit-awry/) | Conversations Gone Awry | `likert`, `multiselect`, `radio`, `span`, `text` |
| [`convokit-politeness/`](conversation/convokit-politeness/) | Wikipedia Politeness | `likert`, `radio`, `span` |
| [`convokit-tree/`](conversation/convokit-tree/) | Thread Structure and Text | `likert`, `radio`, `span` |
| [`threaded-forum/`](conversation/threaded-forum/) | Threaded Discussion Annotation | `likert`, `radio`, `span`, `span_link`, `text` |

### crowdsourcing/ (6)

| Example | Task | Types |
|---------|------|-------|
| [`connect-example/`](crowdsourcing/connect-example/) | Connect Annotation Task | `radio` |
| [`expert-invites-example/`](crowdsourcing/expert-invites-example/) | Expert Annotation Task | `radio` |
| [`generic-panel/`](crowdsourcing/generic-panel/) | Panel Annotation Task | `radio` |
| [`microworkers-example/`](crowdsourcing/microworkers-example/) | Microworkers Annotation Task | `radio` |
| [`prolific-basic/`](crowdsourcing/prolific-basic/) | Prolific Annotation Task | `radio` |
| [`sona-example/`](crowdsourcing/sona-example/) | SONA Annotation Task | `radio` |

### custom-layouts/ (6)

| Example | Task | Types |
|---------|------|-------|
| [`category-assignment/`](custom-layouts/category-assignment/) | Category-Based Assignment Example | `radio` |
| [`content-moderation/`](custom-layouts/content-moderation/) | Content Moderation Dashboard | `radio`, `text` |
| [`custom-layout-example/`](custom-layouts/custom-layout-example/) | Custom Layout Example | `likert`, `multiselect`, `radio`, `text` |
| [`dialogue-qa/`](custom-layouts/dialogue-qa/) | Customer Service Quality Assessment | `likert`, `multiselect`, `radio`, `text` |
| [`icl-labeling/`](custom-layouts/icl-labeling/) | ICL Labeling Example | `radio` |
| [`medical-review/`](custom-layouts/medical-review/) | Radiology Review | `multiselect`, `radio`, `text` |

### embodied/ (1)

| Example | Task | Types |
|---------|------|-------|
| [`lerobot-episode/`](embodied/lerobot-episode/) | Robot episode review | `episode_annotation`, `text` |

### image/ (15)

| Example | Task | Types |
|---------|------|-------|
| [`annotation-critique/`](image/annotation-critique/) | Annotation review (VLM as judge) | `image_annotation` |
| [`coco-import/`](image/coco-import/) | object_detection (imported) | `image_annotation` |
| [`deep-zoom/`](image/deep-zoom/) | Deep-zoom survey annotation | `image_annotation` |
| [`document-bbox/`](image/document-bbox/) | Document Region Annotation | `radio` |
| [`format-migration/`](image/format-migration/) | Format migration | `image_annotation` |
| [`geometry-primitives/`](image/geometry-primitives/) | Geometry Primitives | `image_annotation` |
| [`image-ai-detection/`](image/image-ai-detection/) | AI-Assisted Object Detection | `image_annotation` |
| [`image-annotation/`](image/image-annotation/) | Object Detection Demo | `image_annotation`, `radio` |
| [`image-classification/`](image/image-classification/) | Image Classification | `radio` |
| [`image-vllm-rationale/`](image/image-vllm-rationale/) | Image Classification with AI Rationales | `image_annotation`, `multiselect`, `radio` |
| [`interactive-segmentation/`](image/interactive-segmentation/) | Interactive segmentation | `image_annotation` |
| [`pdf-annotation/`](image/pdf-annotation/) | PDF Entity Annotation | `span` |
| [`pdf-bbox/`](image/pdf-bbox/) | PDF Layout Annotation | `radio`, `text` |
| [`region-captioning/`](image/region-captioning/) | Region captioning | `image_annotation`, `region_caption` |
| [`text-prompt-labeling/`](image/text-prompt-labeling/) | Text-prompt labelling | `image_annotation` |

### span/ (11)

| Example | Task | Types |
|---------|------|-------|
| [`conversation-tree/`](span/conversation-tree/) | Conversation Tree Evaluation | `tree_annotation` |
| [`coreference/`](span/coreference/) | Coreference Annotation Demo | `coreference`, `span` |
| [`dependency-tree/`](span/dependency-tree/) | Dependency Tree Annotation | `span`, `span_link` |
| [`entity-linking/`](span/entity-linking/) | Entity Linking Example | `span` |
| [`event-annotation/`](span/event-annotation/) | Event Annotation Example | `event_annotation`, `span` |
| [`multi-span/`](span/multi-span/) | Multi-Span Annotation Example | `span` |
| [`segmentation/`](span/segmentation/) | Image Segmentation Demo | `image_annotation` |
| [`span-labeling/`](span/span-labeling/) | Simple Highlighting Example | `span` |
| [`span-labeling-with-abbreviations/`](span/span-labeling-with-abbreviations/) | Simple Highlighting Example | `span` |
| [`span-linking/`](span/span-linking/) | Span Linking Example | `span`, `span_link` |
| [`span-required-labeling/`](span/span-required-labeling/) | Simple Highlighting Example | `span` |

### spatial/ (2)

| Example | Task | Types |
|---------|------|-------|
| [`depth-eval/`](spatial/depth-eval/) | Depth prediction review | `multiselect`, `radio`, `text` |
| [`kitti-cuboids/`](spatial/kitti-cuboids/) | Lidar 3D boxes | `spatial_annotation`, `text` |

### testing/ (2)

| Example | Task | Types |
|---------|------|-------|
| [`verify-format-displays/`](testing/verify-format-displays/) | Format Display Verification | `radio`, `text` |
| [`verify-span-labeling/`](testing/verify-span-labeling/) | Span Labeling Verification | `span` |

### video/ (8)

| Example | Task | Types |
|---------|------|-------|
| [`mask-propagation/`](video/mask-propagation/) | Track through an occlusion | `video_annotation` |
| [`polygon-tracking/`](video/polygon-tracking/) | Polygon Tracking | `video_annotation` |
| [`video-annotation/`](video/video-annotation/) | Simple Video as Input Example | `multiselect` |
| [`video-as-label/`](video/video-as-label/) | Simple Video as Label Example | `multiselect` |
| [`video-classification/`](video/video-classification/) | Video Classification | `multiselect`, `radio` |
| [`video-frame-annotation/`](video/video-frame-annotation/) | Video Frame Annotation Example | `video_annotation` |
| [`video-player/`](video/video-player/) | Video Player | `radio`, `video` |
| [`video-tracking/`](video/video-tracking/) | Simple Video Object Tracking | `video_annotation` |

<!-- END GENERATED INDEX -->
