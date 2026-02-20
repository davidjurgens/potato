# Potato vs. Other Annotation Tools

Potato is a flexible, open-source annotation platform built for NLP and ML researchers. This page compares Potato's capabilities with popular alternatives across text, image, audio, video, and multimodal annotation.

## At a Glance

| Capability | Potato | Label Studio | CVAT | Prodigy | INCEpTION | BRAT | ELAN |
|-----------|--------|-------------|------|---------|-----------|------|------|
| Open source | Yes | Community ed. | Yes | No | Yes | Yes | Yes |
| Text classification | Yes | Yes | - | Yes | Yes | - | - |
| Span / NER annotation | Yes | Yes | - | Yes | Yes | Yes | - |
| Relation extraction | Yes | Yes | - | - | Yes | Yes | - |
| Event annotation (n-ary) | Yes | - | - | - | - | Yes | - |
| Entity linking (KB) | Yes | - | - | - | Yes | Yes | - |
| Coreference chains | Yes | - | - | - | Yes | Yes | - |
| Pairwise comparison | Yes | Yes | - | - | - | - | - |
| Triage (accept/reject) | Yes | - | - | Yes | - | - | - |
| Image bounding boxes | Yes | Yes | Yes | - | - | - | - |
| Image segmentation masks | Yes | Yes | Yes | - | - | - | - |
| Audio segmentation | Yes | Yes | - | - | - | - | Yes |
| Video temporal annotation | Yes | Yes | Yes | - | - | - | Yes |
| Video object tracking | Yes | - | Yes | - | - | - | - |
| PDF/document annotation | Yes | - | - | - | - | - | - |
| Code annotation | Yes | - | - | - | - | - | - |
| Spreadsheet annotation | Yes | - | - | - | - | - | - |
| AI/LLM assistance | 14+ endpoints | Yes | - | spaCy | Yes | - | - |
| Active learning | Yes | Enterprise | - | Yes | Yes | - | - |
| Crowdsourcing (MTurk, Prolific) | Yes | - | - | - | - | - | - |
| Multi-phase workflows | Yes | - | - | - | - | - | - |
| YAML configuration (no code) | Yes | XML templates | - | Python | Java config | Config files | GUI |
| Export formats | 12+ | Multiple | 10+ | JSONL | UIMA, CoNLL | Standoff | EAF |

## Where Potato Excels

### Breadth of Annotation Types

Potato supports 20+ annotation schemas in a single platform, from standard text classification to specialized types like n-ary event annotation, entity linking, coreference chains, conversation trees, and pairwise comparison. Most tools focus on one modality; Potato covers text, image, audio, video, PDF, code, and spreadsheet annotation.

### AI and LLM Integration

Potato integrates with 14+ AI endpoints out of the box: OpenAI, Anthropic, Google Gemini, Ollama, vLLM, HuggingFace, OpenRouter, and YOLO. Features include:

- **Intelligent hints** with suggested labels
- **Keyword highlighting** using AI-detected terms
- **Label suggestions** with visual indicators
- **Option highlighting** using LLM-based scoring
- **AI rationales** explaining each label choice
- **Active learning** with uncertainty sampling and diversity clustering

No other annotation tool offers this breadth of AI integration.

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

Export annotations in 12+ formats including COCO JSON (with RLE masks), YOLO, Pascal VOC, CoNLL-2003, CoNLL-U, Mask PNG, EAF (ELAN), and TextGrid (Praat), plus standard JSON/JSONL/CSV/TSV.

### Configuration Without Code

Define complete annotation tasks in YAML: schemas, display types, assignment strategies, AI integration, quality control, and workflow phases. No programming required for standard use cases.

## Comparison by Use Case

### Text Annotation (NER, Classification, Relations)

**vs. BRAT / INCEpTION**: Potato now matches BRAT's core NLP capabilities (spans, relations, events, coreference, discontinuous spans, entity linking) while adding AI assistance, active learning, pairwise comparison, triage, and crowdsourcing integration that BRAT lacks. INCEpTION has a richer plugin architecture and dependency tree annotation; Potato has broader AI/LLM integration and multi-modal support.

**vs. Prodigy**: Prodigy offers scriptable Python recipes and tight spaCy integration. Potato offers YAML-based configuration (no code), more annotation types, multi-phase research workflows, and broader AI provider support. Potato's triage schema covers Prodigy's core accept/reject workflow.

**vs. doccano**: Potato offers significantly more annotation types, AI integration, quality control, and crowdsourcing features. doccano is simpler to set up for basic tasks.

**vs. Label Studio**: Label Studio has a visual template editor and enterprise features. Potato has deeper research workflow support (training phases, behavioral tracking, MACE, adjudication), more AI endpoints, and native crowdsourcing integration.

### Image Annotation

**vs. CVAT**: CVAT is purpose-built for computer vision with 3D cuboids, point clouds, and SAM integration. Potato covers core CV needs (bounding boxes, polygons, segmentation masks, landmarks, video tracking) with COCO/YOLO/VOC export, plus the ability to combine image annotation with text, classification, and other schemas in a single task.

**vs. LabelImg**: Potato surpasses LabelImg across all features and now supports the same export formats (Pascal VOC, YOLO).

### Audio and Video Annotation

**vs. ELAN**: ELAN has hierarchical annotation tiers and synchronized multi-modal timelines for linguistics research. Potato has audio segmentation with waveform visualization, video temporal annotation with object tracking, and now exports to EAF and TextGrid formats for interoperability with ELAN workflows.

**vs. Praat**: Praat is specialized for phonetic analysis with spectrogram visualization. Potato covers audio segmentation and exports to TextGrid format, but does not replace Praat for acoustic analysis tasks.

### LLM Evaluation and Preference Annotation

Potato's pairwise comparison schema (binary A/B and scale slider modes), conversation tree annotation, and triage schema make it suitable for RLHF data collection and LLM evaluation. Combined with 14+ AI endpoints for model-assisted annotation, Potato handles preference annotation workflows that typically require specialized tools.

## Remaining Gaps

Potato does not currently support:

- **Dependency tree annotation** (available in WebAnno, INCEpTION)
- **Spectrogram visualization** (available in Praat, Label Studio)
- **Hierarchical annotation tiers** (available in ELAN)
- **Time-series annotation** (available in Label Studio)
- **3D cuboid / point cloud annotation** (available in CVAT, Scalabel)
- **SAM 2 integration** for AI-assisted segmentation (available in CVAT)
- **Visual template builder** for configuration (available via [Potato Playground](https://www.potatoannotator.com/))
- **LLM-as-a-Judge** automated evaluation pipeline (in progress)

## Getting Started

Potato is free, open-source, and runs locally or on any server:

```bash
pip install potato-annotation
potato start config.yaml -p 8000
```

See the [Quick Start Guide](quick-start.md) for a 5-minute setup, or browse [example projects](https://github.com/davidjurgens/potato/tree/master/project-hub/simple_examples) for ready-to-use configurations.
