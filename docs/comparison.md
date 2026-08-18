# Potato vs. Other Annotation Tools

Potato is a flexible, open-source annotation platform built for NLP and ML researchers. This page compares Potato's capabilities with popular alternatives across text, image, video, 3D, robotics, and model-evaluation annotation. Last updated: August 2026.

Most of the tools below are very good at what they were built for, and several beat Potato inside their own specialty; where that is true, this page says so, because the useful outcome is that you pick the right instrument even when it is not this one. Every claim about another product comes from that product's own documentation or changelog, and vendor documentation describes the current version, so re-check anything you plan to rely on.

## At a Glance

| Capability | Potato | Label Studio | CVAT | Prodigy | INCEpTION | BRAT | ELAN | doccano |
|-----------|--------|-------------|------|---------|-----------|------|------|---------|
| Open source | Yes | Community ed. | Yes | No | Yes | Yes | Yes | Yes |
| Text classification | Yes | Yes | - | Yes | Yes | - | - | Yes |
| Span / NER annotation | Yes | Yes | - | Yes | Yes | Yes | - | Yes |
| Relation extraction | Yes | Yes | - | Yes | Yes | Yes | - | Yes |
| Event annotation (n-ary) | Yes | - | - | - | - | Yes | - | - |
| Entity linking (KB) | Yes | - | - | - | Yes | Yes | - | - |
| Coreference chains | Yes | - | - | - | Yes | Yes | - | - |
| Dependency trees | Yes | - | - | - | Yes | - | - | - |
| Tiered annotation | Yes | - | - | - | - | - | Yes | - |
| Pairwise comparison | Yes | Yes | - | - | - | - | - | - |
| Triage (accept/reject) | Yes | - | - | Yes | - | - | - | - |
| Image bounding boxes | Yes | Yes | Yes | Yes | - | - | - | - |
| Image segmentation masks | Yes | Yes | Yes | - | - | - | - | - |
| Audio segmentation | Yes | Yes | - | Yes | - | - | Yes | - |
| Video temporal annotation | Yes | Yes | Yes | Yes | - | - | Yes | - |
| Video object tracking | Yes | - | Yes | - | - | - | - | - |
| PDF/document annotation | Yes | - | - | - | - | - | - | - |
| Code annotation | Yes | - | - | - | - | - | - | - |
| Spreadsheet annotation | Yes | - | - | - | - | - | - | - |
| ML-assisted labeling | Yes | Yes | Yes | Yes | Yes | - | - | - |
| LLM endpoint support | Yes | Yes | - | Yes | Yes* | - | - | - |
| Multiple LLM providers (3+) | Yes | Yes | - | Yes | - | - | - | - |
| AI rationales / explanations | Yes | - | - | - | - | - | - | - |
| Active learning | Yes | Enterprise | - | Yes | Yes | - | - | - |
| Inter-annotator agreement | Yes | Enterprise | - | Yes | Yes | - | - | - |
| Adjudication interface | Yes | Enterprise | - | Yes | Yes | - | - | - |
| MACE competence estimation | Yes | - | - | - | - | - | - | - |
| Attention checks | Yes | - | - | - | - | - | - | - |
| Gold standard items | Yes | Enterprise | - | - | - | - | - | - |
| Behavioral tracking | Yes | - | - | - | - | - | - | - |
| Multi-phase workflows | Yes | - | - | - | - | - | - | - |
| Role-based access control (RBAC) | Yes | Enterprise | Yes | - | - | - | - | - |
| Per-cohort schema assignment | Yes | Enterprise | - | - | - | - | - | - |
| Handles 50k+ items | Yes | Yes | Yes | Yes | Yes | - | - | Yes |
| Crowdsourcing (MTurk, Prolific) | Yes | - | - | - | - | - | - | - |
| Keyboard shortcuts | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| YAML configuration (no code) | Yes | XML templates | - | Python | Java config | Config files | GUI | - |
| Export formats | 29 | Multiple | 19 | JSONL | UIMA, CoNLL | Standoff | EAF | JSONL |
| COCO import (incl. RLE masks) | Yes | - | Yes | - | - | - | - | - |

\* Experimental.

## Vision, 3D, and Model Evaluation at a Glance

Potato's computer-vision, spatial, and evaluation surfaces are newer than its text ones. This table records where each tool is strong rather than ranking them.

| Capability | Potato | CVAT | Label Studio | Roboflow | V7 | Supervisely | Segments.ai |
|---|---|---|---|---|---|---|---|
| Free self-hosted | Yes | Yes (MIT) | Community ed. | - | - | Community ed. | - |
| Bounding boxes, polygons, masks | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Interactive segmentation (click → mask) | In-browser, no GPU | Via Nuclio | Via ML backend | Yes | Yes | Yes | Yes |
| Text-prompt segmentation | - | - | Via ML backend | Yes (SAM 3) | Yes (SAM 3) | Via apps | - |
| Keypoints / skeletons | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Polylines, ellipses, 2D cuboids | Yes | Yes | Partial | Partial | Yes | Yes | Yes |
| Per-object attributes | - | Yes | Yes | Yes | Yes | Yes | Yes |
| Video tracking with interpolation | Yes | Yes | Partial | Partial | Yes | Yes | Yes |
| Model-based mask propagation | Frame-to-frame re-prompt | Via AI agents | Via ML backend | Yes | Yes | Yes | Yes |
| Deep zoom / tiled gigapixel images | Yes (DZI + IIIF) | Partial | - | - | Yes | Yes | - |
| 3D point clouds & cuboids | Yes | Yes | - | - | - | Yes | Yes |
| Point-cloud sequences / episodes | - | Yes | - | - | - | Yes | Yes |
| Sensor fusion (2D↔3D projection) | Yes | Partial | - | - | - | Yes | Yes |
| Depth maps with windowing | Yes | - | - | - | Partial | - | - |
| DICOM / NIfTI / WSI | - | - | - | - | Yes | Yes | - |
| Model training in the same product | - | Partial | - | Yes | Yes | Yes | - |
| CV format import | 15 formats | Extensive | Partial | Extensive | Partial | Extensive | Partial |
| **Chance-corrected agreement over geometry** | **Yes** | - | - | - | - | - | - |
| Robot episode annotation (LeRobot, RLDS, HDF5) | Yes | - | - | - | - | - | - |
| Generative-video / world-model evaluation | Yes | - | - | - | - | - | - |
| VLM grounding & pointing evaluation | Yes | - | - | - | - | - | - |

On every row except the last four, the mature CV platforms generally match or beat Potato. On those four, Potato is currently doing something the other tools do not offer.

## Potato's strengths

### Chance-corrected agreement

Potato reports **chance-corrected** reliability, and it does so for more than categorical labels. Krippendorff's α accepts any distance function, so the same coefficient machinery covers text spans, temporal segments, geometry, 3D cuboids, captions (through a semantic distance), and world-model break-points. Where α is the wrong tool, Potato says so and uses something else. Geometry localization is reported as σ and a KS statistic against an empirical chance baseline. Mask consensus uses STAPLE. Per-annotator competence uses MACE, for the parts of the problem that are genuinely categorical.

Two design choices matter as much as the coefficients:

- **Undefined values explain themselves.** α is undefined on a unanimous corpus; a bare `NaN` reads as a broken computation, and a `1.0` would be a lie.
- **Nothing is truncated silently.** If a report hits its pairwise budget, it says so and states how many items were included.

Most annotation platforms report agreement as raw IoU, exact match, or percent agreement against a ground-truth job. Those are useful numbers, but they answer a different question. Raw agreement is inflated whenever one answer dominates, which is the normal case in real corpora.

### Breadth of Annotation Types

Potato has 61 annotation schemas and 24 display types in one platform. The list includes text classification, n-ary events, entity linking, coreference chains, image and video geometry, 3D point clouds, depth maps, robot episodes, agent traces, and generative-video rollouts. Most tools cover one or two modalities; a Potato project can combine several in one task and measure agreement across all of them.

### AI and LLM Integration

Potato integrates with 13 AI endpoint types, with no plugin to install: OpenAI, Anthropic, Google Gemini, Ollama, vLLM, HuggingFace, OpenRouter, and YOLO. Features include:

- **Intelligent hints** with suggested labels
- **Keyword highlighting** using AI-detected terms
- **Label suggestions** with visual indicators
- **Option highlighting** using LLM-based scoring
- **AI rationales** explaining each label choice
- **Active learning** with uncertainty sampling and diversity clustering

While Label Studio and Prodigy now offer LLM integration, Potato provides the broadest set of AI assistance modes (hints, highlighting, suggestions, rationales, option scoring) in a single platform.

### Research-Oriented Workflow

Potato is designed for research annotation studies with built-in support for:

- **Multi-phase workflows**: consent, instructions, training (with feedback), annotation, post-study surveys
- **Quality control**: attention checks, gold standards, MACE annotator competence estimation
- **Adjudication**: dedicated interface for resolving inter-annotator disagreements
- **55 validated survey instruments** (SUS, NASA-TLX, UMUX, AttrakDiff, and more) for post-study evaluation
- **Behavioral tracking**: keystroke, mouse, and timing data for annotator behavior analysis
- **Crowdsourcing**: native MTurk and Prolific integration

### Data Source Flexibility

Load data from 8 source types: local files, URLs, Google Drive, Dropbox, Amazon S3, HuggingFace datasets, Google Sheets, and databases. Most tools only support local file upload.

### Export Format Coverage

Export annotations in 29 formats and import from 15. Computer vision: COCO (including RLE and panoptic), YOLO, Pascal VOC, CVAT XML, Darwin, LabelMe, KITTI, MOT, DAVIS, Cityscapes, mask PNG, HuggingFace. Import-only: Labelbox, Open Images, VIA, WebDataset. Linguistics and audio: CoNLL-2003, CoNLL-U, EAF (ELAN), TextGrid (Praat), ConvoKit. Robotics and evaluation: per-frame episode JSONL, agent-eval, telemetry streams. Plus JSON/JSONL/CSV/TSV/Parquet.

**Darwin is bidirectional**, which matters if you are leaving a platform rather than joining one: an import-only path lets you take work out once but never hand it back. See the [format matrix](data-export/format_matrix.md), which is generated from the registries and tested against them, so it cannot drift from what the code actually supports.

Potato also **imports** COCO as-is, including polygon and RLE segmentation and `iscrowd` crowd regions, with no preprocessing step. Existing annotations and model output can be corrected instead of recreated. See [Image Annotation Formats](annotation-types/multimedia/image_formats.md).

### Configuration Without Code

Define complete annotation tasks in YAML: schemas, display types, assignment strategies, AI integration, quality control, and workflow phases. No programming required for standard use cases.

---

## Established Platforms

### Label Studio
- **Type:** Open-source + commercial (HumanSignal)
- **URL:** [github.com/HumanSignal/label-studio](https://github.com/HumanSignal/label-studio)
- **License:** Apache 2.0 (Community Edition)
- **Pricing:** Community Edition free; Starter Cloud $149/month; Enterprise custom pricing

Label Studio provides the broadest single-tool modality coverage among general-purpose platforms. It supports text, image, audio, video, and time series annotation through XML-based templates. The Community Edition includes ML backend integration (OpenAI, Azure OpenAI, Ollama via ML SDK) for pre-annotation. The Enterprise Edition adds a managed "Prompts" interface with 9+ LLM providers (Anthropic, Gemini, Cohere, Mistral, etc.), quality review with 30+ agreement metrics, ground truth evaluation, and annotator performance dashboards. Label Studio does not provide research-oriented features like consent workflows, validated survey instruments, or MACE-based adjudication.

**Compared to Potato:** Label Studio offers broader enterprise project management but lacks Potato's research workflow features (multi-phase progression, surveys, behavioral tracking, crowdsourcing integration). Potato provides more AI assistance modes (hints, highlighting, rationales, option scoring) and unique features like Solo Mode.

### CVAT (Computer Vision Annotation Tool)
- **Type:** Open-source (OpenCV)
- **URL:** [github.com/cvat-ai/cvat](https://github.com/cvat-ai/cvat)
- **License:** MIT
- **Pricing:** Self-hosted free; hosted tiers available

CVAT is the leading open-source tool for computer vision annotation. It provides bounding boxes, polygons, polylines, ellipses, cuboids, skeletons, brush/mask segmentation, and video tracking with keyframe interpolation. ML-assisted annotation includes SAM (Segment Anything), YOLO, HuggingFace models, and Roboflow integration via serverless Nuclio functions. CVAT supports customizable keyboard shortcuts, consensus-based annotation scoring, and a review/QA workflow. It does **not** support text annotation or NLP tasks.

**Compared to Potato:** CVAT excels at image/video CV annotation with deep model integration but has zero NLP support. Potato covers both text and image/audio/video annotation in a single platform.

### Prodigy
- **Type:** Commercial (Explosion AI)
- **URL:** [prodi.gy](https://prodi.gy/)
- **Pricing:** ~$490 one-time license; free academic licenses available

Prodigy was designed around active learning and model-in-the-loop annotation with tight spaCy integration. It supports text classification, span labeling (NER), relation annotation (`rel.manual`), audio/video temporal segmentation, image bounding boxes/polygons, and coreference. Since v1.13, Prodigy integrates with LLMs via `spacy-llm` (OpenAI, Anthropic, Cohere, local models). It includes IAA metrics (Krippendorff's alpha, Gwet's AC2), a `review` recipe for adjudication, and JSON-based configuration with Python recipe functions.

**Compared to Potato:** Prodigy is the most feature-rich commercial alternative. It lacks Potato's research workflow features (multi-phase progression, validated surveys, behavioral tracking, crowdsourcing integration), config-driven YAML setup (Prodigy uses Python recipes + JSON), MACE integration, and Solo Mode. Prodigy is closed-source and paid.

### INCEpTION
- **Type:** Open-source (TU Darmstadt)
- **URL:** [inception-project.github.io](https://inception-project.github.io/)
- **License:** Apache 2.0
- **Latest paper:** [Eckart de Castilho et al., EMNLP 2024](https://aclanthology.org/2024.emnlp-demo.12/)

INCEpTION is the successor to WebAnno and is the most mature platform for linguistic annotation. It supports spans, relations, chains (coreference), document-level annotations, and cross-layer relations. Its standout feature is **knowledge base linking** (Wikidata, DBPedia, OWL, SKOS) with auto-completion and contextual re-ranking. INCEpTION has a comprehensive recommender system for ML-assisted annotation with built-in active learning. Recent versions add experimental LLM integration (Ollama, ChatGPT, Azure OpenAI as recommenders) and an LLM-based Assistant sidebar. It provides robust IAA metrics (Cohen's kappa, Fleiss' kappa, Krippendorff's alpha) and a dedicated curation/adjudication interface.

**Compared to Potato:** INCEpTION is the strongest platform for complex linguistic annotation with knowledge bases. It does not support image/audio/video annotation, YAML-based configuration, research workflow phases, surveys, behavioral tracking, or crowdsourcing integration. Its Java-based deployment is heavier than Potato's Python/Flask stack.

### BRAT
- **Type:** Open-source (unmaintained)
- **URL:** [github.com/nlplab/brat](https://github.com/nlplab/brat)
- **License:** MIT
- **Status:** Last release November 2012; last commit October 2021

BRAT was an influential early web-based annotation tool supporting text spans, binary relations, n-ary events, equivalence classes (coreference), and attributes. While still functional, it is no longer actively maintained (470+ open issues, no recent development).

**Compared to Potato:** BRAT is largely superseded by INCEpTION and Potato for new projects, but remains widely deployed for legacy annotation tasks.

### ELAN
- **Type:** Free/open-source (MPI for Psycholinguistics)
- **URL:** [archive.mpi.nl/tla/elan](https://archive.mpi.nl/tla/elan)
- **License:** GPL-3.0
- **Paper:** [Wittenburg et al., LREC 2006](https://aclanthology.org/L06-1082/)

ELAN is the standard tool for time-aligned annotation of audio and video data, widely used in linguistics, sign language research, gesture studies, and multimodal interaction analysis. It supports up to 4 synchronized video files, hierarchical tier systems, controlled vocabularies, and automatic segmentation via a silence detector. It has extensive customizable keyboard shortcuts.

**Compared to Potato:** ELAN is the gold standard for time-aligned multimedia annotation with a desktop application. Potato provides web-based audio/video annotation suitable for distributed annotation campaigns, though with less sophisticated temporal alignment features than ELAN's desktop interface.

### doccano
- **Type:** Open-source
- **URL:** [github.com/doccano/doccano](https://github.com/doccano/doccano)
- **License:** MIT

doccano is a lightweight open-source text annotation tool supporting text classification, sequence labeling (NER), sequence-to-sequence tasks, and relation annotation. It includes auto-labeling via external API integration and customizable keyboard shortcuts.

**Compared to Potato:** doccano is simpler and quicker to deploy for basic text annotation, but lacks Potato's breadth of annotation types, AI/LLM integration, quality control features, and research workflow support.

---

## Comparison by Use Case

### Text Annotation (NER, Classification, Relations)

**vs. BRAT / INCEpTION**: Potato matches BRAT's core NLP capabilities (spans, relations, events, coreference, discontinuous spans, entity linking) while adding AI assistance, active learning, pairwise comparison, triage, and crowdsourcing integration that BRAT lacks. Potato also supports dependency tree annotation via span linking. INCEpTION has a richer plugin architecture and superior knowledge base integration; Potato has broader AI/LLM integration and multi-modal support.

**vs. Prodigy**: Prodigy offers scriptable Python recipes, tight spaCy integration, and now supports relations, audio, video, and LLM endpoints. Potato offers YAML-based configuration (no code), more annotation types, multi-phase research workflows, broader AI provider support, and is fully open-source. Potato's triage schema covers Prodigy's core accept/reject workflow.

**vs. doccano**: Potato offers significantly more annotation types, AI integration, quality control, and crowdsourcing features. doccano now supports relation annotation. doccano is simpler to set up for basic tasks.

**vs. Label Studio**: Label Studio has a visual template editor and enterprise features. Both now offer LLM integration (Label Studio via ML SDK in Community, native in Enterprise). Potato has deeper research workflow support (training phases, behavioral tracking, MACE, adjudication), more AI assistance modes, and native crowdsourcing integration.

### Image and Video Annotation

Potato's CV surface covers boxes, polygons, polylines, ellipses, 2D cuboids, keypoint sets with skeletons, instance-keyed brush masks, and video tubelets with polygon interpolation. Interactive segmentation runs in the browser through ONNX Runtime Web: no GPU to provision, no model server to keep up, and it works air-gapped. Fifteen import formats and twenty-nine export formats let you bring existing work in and take it back out.

**vs. CVAT.** CVAT is the reference open-source CV tool and remains the better choice for high-volume, CV-only pipelines: deeper task/job management, per-object attributes, a larger format ecosystem through Datumaro, and a very large community. Choose Potato when the CV work sits alongside text, audio, or evaluation tasks, or when you need agreement statistics between annotators rather than accuracy against a ground-truth job.

**vs. Roboflow.** Roboflow is excellent if your goal is a trained model: Smart Polygon, batch auto-labelling with SAM 3 text prompts, Label Assist from your own model, and hosted training and deployment in one loop. Potato does not train detectors. Choose Potato when the labels themselves are the research output and their reliability has to be defensible.

**vs. Label Studio.** Label Studio offers the broadest template system and the largest integration ecosystem, and its Enterprise tier adds review workflows and agreement scoring. Potato's agreement measures are chance-corrected and available in the free, self-hosted product; Label Studio's are exact-match, IoU, and span overlap.

**vs. Labelbox, SuperAnnotate, Encord, Kili, V7.** These are mature commercial platforms with workforce management, enterprise governance, and strong model-assisted labelling (SAM 3, GroundingDINO, auto-tracking). If you need a managed workforce, compliance certifications, or petabyte-scale curation, they are the right answer. Potato is free, self-hosted, and research-workflow-first.

**vs. X-AnyLabeling, LabelMe, labelImg.** If you are one person labelling locally and want open-vocabulary auto-labelling today, X-AnyLabeling bundles Grounding DINO, Grounded-SAM 2, SAM 2.1, and YOLO in a desktop app and is very hard to beat for that. Potato's advantage begins when there is more than one annotator.

### Gigapixel and Deep Zoom

Potato builds a tile pyramid served as both DZI and IIIF Image API 3.0. Brush masks work on tiled images at the source's full resolution, because the mask buffer indexes image pixels instead of a GPU texture, so there is no texture-size ceiling to hit. 16-bit scientific TIFF gets a percentile window so faint structure is visible.

For digital pathology specifically, **QuPath** (desktop, open source, the field standard) and **Cytomine** (web, open source, multi-user and blind annotation) are purpose-built, and Potato does not yet read SVS, DICOM, or NIfTI. Use Potato here when your images are large but not clinical-format, or when you need Potato's agreement and workflow layers on top.

### 3D, Point Clouds, and Sensor Fusion

Potato annotates PCD, PLY, LAS, KITTI `.bin`, and `.xyz` clouds with 3D cuboids, points, polylines, and per-point segments; octree level-of-detail keeps large scans interactive; calibration data projects cuboids into each camera image so you can verify in 2D while editing in 3D; orthographic slab panels give axis-aligned editing; depth maps can be unprojected into the same viewer. Cuboid rotation is stored as a quaternion, so pitch and roll survive round-trips that a yaw-only field would silently discard, and agreement over cuboids uses exact rotated 3D IoU.

**Segments.ai**, **Kognic**, **Deepen AI**, **Supervisely**, and **Xtreme1/BasicAI** are specialists here, and for production autonomous-driving pipelines they are ahead: sequence and episode workflows with track propagation, radar and multi-LiDAR support, auto-fit cuboid models, per-object attribute ontologies, and (in Deepen's case) a full targetless calibration product. Supervisely and Xtreme1 are both self-hostable, and Supervisely handles far larger clouds. Choose Potato for 3D when you want reliability statistics over spatial labels, or when 3D is one part of a multimodal study.

### Robotics and Embodied Episodes

Potato's `episode_annotation` schema puts N synchronized video streams and M robot time-series lanes (joint positions, gripper state, force-torque, reward) on one timeline, with phase segmentation, per-phase outcome, dense progress reward, and instruction relabelling. It imports LeRobot v2, HDF5 (RoboMimic/ALOHA), and RLDS/TFDS, and exports a per-frame JSONL sidecar so a read-only public dataset does not have to be rewritten. Agreement is reported three ways: temporal IoU for phase boundaries, α for outcome labels, and ICC plus Pearson for reward curves. Coverage is stated alongside, because a correlation computed over 5% of a timeline says nothing about the rest.

Related tools worth knowing: **ATLAS** (TU Wien, 2026) is a focused desktop tool for long-horizon action segmentation with native ROS bag and RLDS support. Its published result — that showing proprioceptive time series alongside video cuts boundary error against vision-only tools — is why Potato renders those lanes at all. **ELAN** and **BORIS** remain the standards for behavioural coding. **Rerun** and **Foxglove** are the best robotics visualization tools and now carry structured annotations. Potato's distinct contribution is being a *multi-annotator, web-deployed* episode annotator with agreement statistics; for single-annotator boundary precision with ROS bags, ATLAS is purpose-built.

### Generative Video and World-Model Evaluation

The `rollout_evaluation` schema shows 2–N synchronized rollouts on a shared clock and asks the annotator to mark **the frame at which the world stops making sense**, tag which physical or causal property broke, judge preference with a rubric, and rate whether a counterfactual divergence is plausible given the intervention. Panels can be blinded and stably shuffled per annotator. Break-point agreement is reported as detection / localization / category, with the matching tolerance shown as a **sweep** rather than a single threshold.

The evaluation ecosystem here is mostly benchmarks (VBench and VBench-2.0, WorldModelBench, Physics-IQ, WorldArena) plus crowd panels such as Rapidata for large-scale preference collection. These provide the metrics and the reference protocols; Potato provides an instrument for running the human side of such a protocol repeatedly, with reliability measured. The two are complementary, and importing a benchmark's rollouts into Potato is a reasonable way to collect the human data those benchmarks validate against.

### VLM Grounding, Pointing, and Region Captioning

`grounding_eval` pairs a referring expression with the regions that denote it, scoring grounding by IoU at four thresholds, **pointing by point-in-region hit rate** (a point has no area, so IoU against one is always zero), and ungroundedness as an explicit, separately-counted answer. `region_caption` adds per-region captions with agreement computed through a semantic distance, since two annotators describing the same object rarely share a content word.

This area is defined by datasets and harnesses (RefCOCO/+/g, PixMo-Points, PointBench, PointArena, lmms-eval, VLMEvalKit) instead of by annotation products. Potato's role is collecting and measuring the human ground truth those benchmarks are built from.

### Audio and Video Annotation

**vs. ELAN**: Potato supports tiered annotation, audio segmentation with waveform visualization, video temporal annotation with object tracking, and exports to EAF and TextGrid formats for full interoperability with ELAN workflows. ELAN has synchronized multi-modal timelines and a dedicated GUI for field linguistics; Potato offers the same core annotation capabilities in a web-based platform with AI assistance and crowdsourcing integration.

**vs. Praat**: Praat is specialized for phonetic analysis with spectrogram visualization. Potato covers audio segmentation and exports to TextGrid format, but does not replace Praat for acoustic analysis tasks.

### LLM Evaluation and Preference Annotation

Potato's pairwise comparison schema (binary A/B and scale slider modes), conversation tree annotation, and triage schema make it suitable for RLHF data collection and LLM evaluation. Combined with 13 AI endpoint types for model-assisted annotation, Potato handles preference annotation workflows that typically require specialized tools.

## Agent-Evaluation Platforms (LangSmith, LabelBox, Braintrust)

A newer class of tools focuses on **evaluating AI agents and LLM applications** rather than general annotation. Potato now provides this agent-evaluation loop as a free, self-hosted option.

| Capability | Potato | LangSmith | LabelBox |
|------------|--------|-----------|----------|
| License / hosting | Free, open-source, self-hosted | Proprietary SaaS (self-host = Enterprise) | Proprietary SaaS |
| Programmatic evaluators (trajectory match, tool-use, LLM-judge) | Yes | Yes (`agentevals`/`openevals`) | partial |
| Versioned datasets + experiments | Yes (file/SQLite) | Yes | Yes |
| Automation rules (filter → sample → actions) | Yes | Yes | partial |
| CI gating (pytest threshold) | Yes | Yes (pytest/Vitest) | No |
| LLM-as-judge ↔ human calibration (κ, ECE) | Yes (auto-calibration) | Yes (human-correction few-shot) | partial |
| Span + free-text judging | Yes | Yes | Yes |
| Production tracing SDK | Yes (`potato_trace`, OTel) | Yes | partial |
| Semantic search / dynamic slices | Yes | partial | Yes (Catalog) |
| Multi-model arena | Yes | No | Yes |
| Human annotation depth (IAA, training, crowdsourcing) | Yes | partial | Yes (Alignerr workforce) |
| Per-seat / per-trace cost | None | Yes | Yes |

**Compared to LangSmith/LabelBox/Braintrust:** Potato covers the same capture → automate → curate → evaluate → CI-gate → calibrate loop, but free, self-hosted, and on top of a human-annotation platform (inter-annotator agreement, training phases, adjudication, crowdsourcing). The trade-off is that the SaaS tools offer managed cloud hosting, large-scale dashboards, and (for LabelBox) an on-demand expert workforce. See the [Agent Evaluation Guide](guides/agent-evaluation-guide.md).

**Human review in the observability tools.** LangSmith, Langfuse, Braintrust, W&B Weave, and Arize Phoenix are strong tracing and evaluation platforms, and several have good human-review surfaces. LangSmith's annotation queues support rubric feedback keys, a configurable number of reviewers per run, pairwise queues, and reviewers who cannot see each other's feedback. Where Potato differs is what happens *after* two people disagree: these platforms are built to collect human judgements as scores, and none of them documents a reliability statistic over those judgements. Langfuse notes that a second annotation on the same trace replaces the first, so independent double annotation needs a workaround.

If your traces already live in one of these tools, that is a good reason to keep them there. Potato is complementary in that case: export the traces you want measured, run the human study and the agreement report in Potato, and take the scores back.

---

## Recent Academic Annotation Systems (2022-2025)

The following tools have been published at ACL, NAACL, EMNLP, or EACL System Demonstrations tracks since 2022. Most of them integrate an LLM somewhere in the annotation loop.

### Human-LLM Collaborative Annotation

**MEGAnno+** (EACL 2024) - Kim et al. ([paper](https://aclanthology.org/2024.eacl-demo.18/))
LLM agents label data first, humans verify uncertain instances via Jupyter notebooks. Most directly comparable AI-integrated annotation platform to Potato's Solo Mode, though MEGAnno+ uses an LLM-first approach while Potato provides a structured 12-phase human-LLM collaboration workflow.

**CrowdAgent** (EMNLP 2025) - Xiong et al. ([paper](https://aclanthology.org/2025.emnlp-demos.72/))
Multi-agent system coordinating LLMs, small language models, and human experts for cost-optimized multimodal classification. Focuses on multi-agent orchestration rather than individual annotator-LLM collaboration.

**Co-DETECT** (EMNLP 2025) - Xiong, Ni et al. ([paper](https://aclanthology.org/2025.emnlp-demos.25/))
Mixed-initiative annotation integrating human expertise with LLM-guided text classification. Shares Solo Mode's interest in collaborative edge case discovery but focuses on classification tasks.

**ITAKE** (ACL 2024) - Song et al. ([paper](https://aclanthology.org/2024.acl-demos.31/))
Interactive text annotation and knowledge extraction with LLMs, online machine learning, active learning, and model lifecycle monitoring.

**DocSpiral** (ACL 2025) - Sun et al. ([paper](https://aclanthology.org/2025.acl-demo.26/))
"Human-in-the-Spiral" iterative document annotation where models progressively reduce human effort, reporting 41%+ time reduction. Targets image-based documents.

### General-Purpose Annotation

**Thresh** (EMNLP 2023) - Heineman, Dou, Xu ([paper](https://aclanthology.org/2023.emnlp-demo.30/), [site](https://thresh.tools))
YAML-configured fine-grained text evaluation platform with a community hub for sharing annotation frameworks. Shares Potato's YAML-driven philosophy but focuses specifically on text evaluation (summarization, simplification, MT).

**GATE Teamware 2** (EACL 2023) - Wilby et al. ([paper](https://aclanthology.org/2023.eacl-demo.17/))
Open-source, JSON-configurable annotation for document classification with annotator training and quality screening.

**ALANNO** (EACL 2023) - Jukic, Snajder ([paper](https://aclanthology.org/2023.eacl-demo.26/))
Open-source annotation with built-in active learning, multi-annotator setup, and round-based document distribution.

**CodeAnno** (EACL 2023) - Rietz et al. ([paper](https://aclanthology.org/2023.eacl-demo.2/))
Extends WebAnno with hierarchical document-level annotation and automation for social science coding tasks.

### LLM Evaluation and RLHF

**ChatHF** (EMNLP 2024) - Li et al. ([paper](https://aclanthology.org/2024.emnlp-demo.28/))
Interactive chat-based annotation for chatbot evaluation with visual and voice input.

**BotEval** (ACL 2024) - Cho et al. ([paper](https://aclanthology.org/2024.acl-demos.11/))
Open-source human evaluation toolkit for human-bot interactions and NLG evaluation.

### Synthetic Data Generation

**Fabricator** (EMNLP 2023) - Golde et al. ([paper](https://aclanthology.org/2023.emnlp-demo.1/))
Open-source toolkit for generating labeled training data entirely from teacher LLMs. Replaces human annotation entirely with LLM generation, complementary to Potato's human-in-the-loop approach.

### Specialized Annotation

**EventFull** (NAACL 2025) - Eirew et al. ([paper](https://aclanthology.org/2025.naacl-demo.40/))
First tool supporting consistent annotation of temporal, causal, and coreference relations in a unified process.

**First-AID** (ACL 2025) - Menini et al. ([paper](https://aclanthology.org/2025.acl-demo.54/))
Human-in-the-loop data collection for knowledge-driven synthetic dialogue generation using LLM prompting.

**Commentator** (EMNLP 2024) - Sheth et al. ([paper](https://aclanthology.org/2024.emnlp-demo.11/))
Code-mixed multilingual text annotation framework claiming 5x faster annotations.

---

## Commercial and Non-Academic Tools

### Argilla
- **Type:** Open-source (Hugging Face ecosystem)
- **URL:** [github.com/argilla-io/argilla](https://github.com/argilla-io/argilla)
- **License:** Apache 2.0
- **Pricing:** Free (self-hosted); Argilla Cloud available

Argilla (formerly Rubrix) is purpose-built for LLM alignment, preference data collection, and RLHF workflows. It integrates deeply with Hugging Face Datasets, provides a Python SDK, and includes the Distilabel framework for synthetic data generation. It supports text classification, token classification, and text generation evaluation.

**Compared to Potato:** Argilla excels at LLM alignment workflows and Hugging Face integration. Potato is broader in annotation types and research workflow features, with Solo Mode offering a more structured human-LLM collaboration approach.

### LabelBox
- **Type:** Commercial SaaS
- **Pricing:** Free tier available; enterprise pricing

Commercial platform focused on computer vision and multimodal annotation. Strong model-assisted labeling, workflow automation, and enterprise project management. No significant NLP focus.

### Scale AI
- **Type:** Commercial managed annotation service
- **Pricing:** Enterprise custom pricing

Managed annotation platform combining human workforce with AI assistance. Primarily targets enterprise ML training data pipelines. Not self-hosted.

### Amazon SageMaker Ground Truth
- **Type:** Commercial (AWS)
- **Pricing:** Pay-per-label

AWS-integrated annotation with built-in active learning and workforce management (MTurk integration). Focused on classification, bounding boxes, and segmentation. Tied to AWS ecosystem.

---

## When to Choose What

| Use Case | Recommended Tool | Why |
|----------|-----------------|-----|
| General NLP annotation with AI assistance | **Potato** | Broadest AI assistance modes, YAML config, research features |
| Single annotator + LLM collaboration | **Potato** (Solo Mode) | Only tool with structured progressive-autonomy workflow |
| Research annotation with surveys/tracking | **Potato** | Multi-phase workflow, 55 surveys, behavioral tracking, MACE |
| Crowdsourced annotation (MTurk/Prolific) | **Potato** | Native integration with both platforms |
| Complex linguistic annotation + knowledge bases | **INCEpTION** | Strongest KB linking, coreference, IAA, curation |
| Computer vision annotation at volume | **CVAT** | Deepest CV-only tooling, attributes, task management, large community |
| Label → train → deploy in one loop | **Roboflow** | Auto Label, hosted training and inference |
| Image + text multimodal annotation | **Label Studio** | Broadest template-based modality coverage |
| Autonomous-driving 3D at production scale | **Segments.ai / Kognic / Supervisely** | Sequence workflows, radar, multi-LiDAR, calibration products |
| Digital pathology | **QuPath / Cytomine** | WSI-native, field standard, open source |
| 3D medical segmentation with AI assist | **3D Slicer + MONAI Label** | Free, interactive, radiology-native |
| Single-annotator robot action segmentation | **ATLAS** | ROS bag / RLDS native, keyboard-first, lowest boundary error |
| Robotics data visualization and telemetry | **Rerun / Foxglove** | Purpose-built viewers with deep SDK support |
| Large-scale video-generation preference collection | **Rapidata** and similar panels | Tens of thousands of judgements in minutes |
| Dataset curation and error surfacing | **FiftyOne / Lightly** | Embedding-driven curation and model-vs-label review |
| **Reliability of any of the above** | **Potato** | Chance-corrected agreement over geometry, time, 3D, captions, and break-points |
| Robot episode annotation with multiple annotators | **Potato** | Episode schema, LeRobot/RLDS/HDF5 import, phase + reward agreement |
| World-model / rollout evaluation | **Potato** | Break-point marking with agreement over *when* the world broke |
| VLM grounding and pointing evaluation | **Potato** | Point-in-region scoring, threshold sweeps, region captions with semantic agreement |
| Active learning with spaCy | **Prodigy** | Deep spaCy integration, efficient model-in-the-loop |
| LLM alignment / RLHF data | **Argilla** | Purpose-built for preference data, HuggingFace ecosystem |
| Time-aligned audio/video research | **ELAN** | Gold standard for multimedia linguistics research |
| Fine-grained text evaluation | **Thresh** | YAML-driven, community sharing hub |
| Quick lightweight text annotation | **doccano** | Simple setup, MIT license |
| LLM-first annotation with verification | **MEGAnno+** | Jupyter-based LLM-first workflow |

---

## Feature Count Summary

| Feature Category | Potato |
|-----------------|:---:|
| Annotation schemas | 61 |
| Display types | 24 |
| Export formats | 29 |
| Import formats | 15 |
| AI/LLM endpoint types | 13 |
| Data source types | 8 |
| Assignment strategies | 11 |
| Survey instruments | 55 |
| Crowdsourcing integrations | 9 |
| Workflow phases | 8 |

Counts are generated from Potato's own registries. There is no "best alternative" column, because the tools above organise their capabilities differently enough that a single number invites a misleading comparison.

---

## What Potato Does Not Do

So an evaluation does not have to discover these late:

- **No model training.** Potato orders items, pre-labels with existing models, and critiques annotations with a VLM, but it does not train or serve detectors. Roboflow, V7, Supervisely, and Labelbox do.
- **No text-prompt segmentation.** Interactive segmentation is click- and box-driven. SAM 3 / Grounding DINO-class open-vocabulary labelling is available in Roboflow, V7, Labelbox, and the open-source desktop tool X-AnyLabeling.
- **Video mask propagation is frame-to-frame re-prompting, not memory-based tracking.** No published SAM 2 ONNX export includes the memory modules.
- **No per-object attributes yet.** Geometry carries a label; occlusion levels, truncation flags, and sub-type attributes need a companion schema.
- **No point-cloud sequence mode.** 3D annotation is per frame; track propagation across a sweep is not implemented.
- **No DICOM, NIfTI, or WSI formats.** Deep zoom and 16-bit windowing cover large scientific images, not clinical ones.
- **No managed workforce, SAML/SCIM, or compliance certifications.** Potato is software you run; RBAC and OAuth are supported, enterprise governance is not.
- **Air-gapped deployment is not complete.** Fabric.js and OpenSeadragon are vendored, but jQuery, Bootstrap, and Font Awesome still load from CDNs. See [Air-Gapped Deployment](deployment/air_gap.md) for exactly which assets are affected and what breaks without them.

## Getting Started

Potato is free, open-source, and runs locally or on any server:

```bash
pip install potato-annotation
potato start config.yaml -p 8000
```

See the [Quick Start Guide](quick-start.md) for a 5-minute setup, or browse [example projects](https://github.com/davidjurgens/potato/tree/master/examples) for ready-to-use configurations.

## Related Documentation

- [AI Support](ai-intelligence/ai_support.md) - Potato's AI integration features
- [Quality Control](workflow/quality_control.md) - Attention checks and gold standards
- [Schema Gallery](annotation-types/schemas_and_templates.md) - All annotation types
