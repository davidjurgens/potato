# Potato vs. Other Annotation Tools

Potato is a flexible, open-source annotation platform built for NLP and ML researchers. This page compares Potato's capabilities with popular alternatives across text, image, audio, video, and multimodal annotation. Last updated: February 2026.

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
| Crowdsourcing (MTurk, Prolific) | Yes | - | - | - | - | - | - | - |
| Keyboard shortcuts | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| YAML configuration (no code) | Yes | XML templates | - | Python | Java config | Config files | GUI | - |
| Export formats | 8+ | Multiple | 10+ | JSONL | UIMA, CoNLL | Standoff | EAF | JSONL |

\* Experimental.

## Where Potato Excels

### Breadth of Annotation Types

Potato supports 15 annotation schemas in a single platform, from standard text classification to specialized types like n-ary event annotation, entity linking, coreference chains, conversation trees, and pairwise comparison. Most tools focus on one modality; Potato covers text, image, audio, video, PDF, code, and spreadsheet annotation.

### AI and LLM Integration

Potato integrates with 12 AI endpoint types out of the box: OpenAI, Anthropic, Google Gemini, Ollama, vLLM, HuggingFace, OpenRouter, and YOLO. Features include:

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

Export annotations in 8+ formats including COCO JSON (with RLE masks), YOLO, Pascal VOC, CoNLL-2003, CoNLL-U, Mask PNG, EAF (ELAN), and TextGrid (Praat), plus standard JSON/JSONL/CSV/TSV.

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

### Image Annotation

**vs. CVAT**: CVAT is purpose-built for computer vision with 3D cuboids, point clouds, SAM integration, and ML-assisted labeling (YOLO, HuggingFace). Potato covers core CV needs (bounding boxes, polygons, segmentation masks, landmarks, video tracking) with COCO/YOLO/VOC export, plus the ability to combine image annotation with text, classification, and other schemas in a single task.

### Audio and Video Annotation

**vs. ELAN**: Potato supports tiered annotation, audio segmentation with waveform visualization, video temporal annotation with object tracking, and exports to EAF and TextGrid formats for full interoperability with ELAN workflows. ELAN has synchronized multi-modal timelines and a dedicated GUI for field linguistics; Potato offers the same core annotation capabilities in a web-based platform with AI assistance and crowdsourcing integration.

**vs. Praat**: Praat is specialized for phonetic analysis with spectrogram visualization. Potato covers audio segmentation and exports to TextGrid format, but does not replace Praat for acoustic analysis tasks.

### LLM Evaluation and Preference Annotation

Potato's pairwise comparison schema (binary A/B and scale slider modes), conversation tree annotation, and triage schema make it suitable for RLHF data collection and LLM evaluation. Combined with 12 AI endpoint types for model-assisted annotation, Potato handles preference annotation workflows that typically require specialized tools.

---

## Recent Academic Annotation Systems (2022-2025)

The following tools have been published at ACL, NAACL, EMNLP, or EACL System Demonstrations tracks since 2022. They represent the evolving landscape of annotation tools, particularly the growing emphasis on AI integration.

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
| Computer vision annotation | **CVAT** | Best CV annotation tooling (SAM, YOLO, tracking) |
| Image + text multimodal annotation | **Label Studio** | Broadest template-based modality coverage |
| Active learning with spaCy | **Prodigy** | Deep spaCy integration, efficient model-in-the-loop |
| LLM alignment / RLHF data | **Argilla** | Purpose-built for preference data, HuggingFace ecosystem |
| Time-aligned audio/video research | **ELAN** | Gold standard for multimedia linguistics research |
| Fine-grained text evaluation | **Thresh** | YAML-driven, community sharing hub |
| Quick lightweight text annotation | **doccano** | Simple setup, MIT license |
| LLM-first annotation with verification | **MEGAnno+** | Jupyter-based LLM-first workflow |

---

## Feature Count Summary

| Feature Category | Potato | Best Alternative |
|-----------------|:---:|:---:|
| Annotation schemas | 15 | ~10 (Label Studio) |
| Display types | 7 | ~5 (Label Studio) |
| AI/LLM endpoint types | 12 | ~3 (Prodigy, Label Studio CE) |
| Data source types | 8 | ~4 (Label Studio) |
| Assignment strategies | 8 | ~3 (Label Studio) |
| Survey instruments | 55 | 0 |
| Crowdsourcing integrations | 2 | ~1 (Label Studio via external) |
| Workflow phases | 8 | ~3 (Label Studio) |

---

## Getting Started

Potato is free, open-source, and runs locally or on any server:

```bash
pip install potato-annotation
potato start config.yaml -p 8000
```

See the [Quick Start Guide](quick-start.md) for a 5-minute setup, or browse [example projects](https://github.com/davidjurgens/potato/tree/master/project-hub/simple_examples) for ready-to-use configurations.

## Related Documentation

- [AI Support](ai-intelligence/ai_support.md) - Potato's AI integration features
- [Quality Control](workflow/quality_control.md) - Attention checks and gold standards
- [Schema Gallery](annotation-types/schemas_and_templates.md) - All annotation types
