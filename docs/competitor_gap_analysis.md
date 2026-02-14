# Competitor Annotation Tool Gap Analysis

**Date:** 2026-02-13
**Scope:** 25+ competitor tools across text, image, audio, video, multimodal, and LLM-preference categories

---

## Table of Contents

1. [Potato's Current Capability Inventory](#1-potatos-current-capability-inventory)
2. [Competitor-by-Competitor Analysis](#2-competitor-by-competitor-analysis)
   - [A. Text Annotation Tools](#a-text-annotation-tools)
   - [B. Image Annotation Tools](#b-image-annotation-tools)
   - [C. Audio Annotation Tools](#c-audio-annotation-tools)
   - [D. Video Annotation Tools](#d-video-annotation-tools)
   - [E. Multimodal & LLM Preference Tools](#e-multimodal--llm-preference-tools)
3. [Consolidated Gap Prioritization](#3-consolidated-gap-prioritization)
4. [Potato's Existing Competitive Strengths](#4-potatos-existing-competitive-strengths)
5. [Strategic Recommendations](#5-strategic-recommendations)

---

## 1. Potato's Current Capability Inventory

### Annotation Schemas (16 types)

Verified against `potato/server_utils/schemas/registry.py`:

| Schema | Description |
|--------|-------------|
| `radio` | Single-choice radio button selection |
| `multiselect` | Multiple-choice checkbox selection |
| `select` | Dropdown selection |
| `likert` | Likert scale rating |
| `slider` | Slider for selecting a value in a range |
| `number` | Numeric input field |
| `text` | Free-form text input |
| `span` | Text span annotation/highlighting |
| `span_link` | Relationships/links between spans |
| `multirate` | Rate multiple items on a scale |
| `video` | Video player display |
| `image_annotation` | Bounding boxes, polygons, freeform drawing, and landmarks |
| `audio_annotation` | Audio segmentation and annotation with waveform visualization |
| `video_annotation` | Temporal segments, frame classification, and keyframes |
| `pairwise` | Pairwise comparison (binary selection or scale rating) |
| `pure_display` | Display-only content (instructions, headers) |

### Display Types (11)

Verified against `potato/server_utils/displays/registry.py`:

| Display | Description | Span Target |
|---------|-------------|-------------|
| `text` | Plain text content | Yes |
| `html` | HTML content (sanitized) | No |
| `image` | Image with optional zoom | No |
| `video` | Video player | No |
| `audio` | Audio player | No |
| `dialogue` | Dialogue/conversation turns | Yes |
| `pairwise` | Side-by-side comparison | No |
| `pdf` | PDF document (PDF.js rendering) | Yes |
| `document` | DOCX, Markdown documents | Yes |
| `spreadsheet` | Spreadsheet/table with row or cell annotation | Yes |
| `code` | Source code with syntax highlighting | Yes |

### Data Sources (8)

Verified against `potato/data_sources/base.py`:

| Source | Type |
|--------|------|
| `file` | Local file (CSV, TSV, JSON, JSONL) |
| `url` | Remote URL |
| `google_drive` | Google Drive |
| `dropbox` | Dropbox |
| `s3` | Amazon S3 |
| `huggingface` | HuggingFace datasets |
| `google_sheets` | Google Sheets |
| `database` | Database connection |

### AI/ML Integration (14+ endpoint types)

Verified against `potato/ai/` directory:

| Endpoint | File |
|----------|------|
| OpenAI | `openai_endpoint.py` |
| OpenAI Vision | `openai_vision_endpoint.py` |
| Anthropic | `anthropic_endpoint.py` |
| Anthropic Vision | `anthropic_vision_endpoint.py` |
| Ollama | `ollama_endpoint.py` |
| Ollama Vision | `ollama_vision_endpoint.py` |
| Gemini | `gemini_endpoint.py` |
| HuggingFace | `huggingface_endpoint.py` |
| OpenRouter | `openrouter_endpoint.py` |
| vLLM | `vllm_endpoint.py` |
| YOLO | `yolo_endpoint.py` |
| Visual AI | `visual_ai_endpoint.py` |
| Active Learning Manager | `llm_active_learning.py` |
| ICL Labeler | `icl_labeler.py` |

Supporting modules: `ai_prompt.py`, `ai_help_wrapper.py`, `ai_cache.py`, `icl_prompt_builder.py`

### Quality Control

- Attention checks
- Gold standards
- Pre-annotation
- MACE aggregation
- Adjudication workflow

### Assignment Strategies (8)

Verified against `potato/item_state_management.py`:

| Strategy | Description |
|----------|-------------|
| `random` | Random assignment |
| `fixed_order` | Sequential order |
| `active_learning` | Model-driven uncertainty sampling |
| `llm_confidence` | Route low-confidence items to humans |
| `max_diversity` | Maximize annotator diversity |
| `least_annotated` | Prioritize items with fewest annotations |
| `category_based` | Expert routing by category |
| `diversity_clustering` | Cluster-based diversity sampling |

### Export Formats (4)

Verified against `potato/flask_server.py` and `potato/create_task_cli.py`:

JSON, JSONL, CSV, TSV

---

## 2. Competitor-by-Competitor Analysis

### A. Text Annotation Tools

#### BRAT

| Feature | BRAT | Potato |
|---------|------|--------|
| Span labeling / NER | Yes | Yes (`span` schema) |
| Relation extraction | Yes (binary relations) | Yes (`span_link`) |
| Event annotation (n-ary) | Yes | **GAP** |
| Coreference chains | Yes | **GAP** |
| Discontinuous spans | Yes | **GAP** |
| Entity normalization (KB linking) | Yes | **GAP** |
| Attribute annotation on entities | Yes | Partial (via conditional logic) |
| Standoff format export | Yes | **GAP** |
| SVG/PDF visualization export | Yes | **GAP** |
| Annotation comparison/diff | Yes | Partial (adjudication) |

**Key gaps:** N-ary event structures, coreference chains, discontinuous spans, entity normalization/KB linking, annotation visualization export.

#### WebAnno

| Feature | WebAnno | Potato |
|---------|---------|--------|
| Span annotations | Yes | Yes |
| Dependency relations | Yes | **GAP** (no tree structures) |
| Coreference chains | Yes | **GAP** |
| Morphological layers | Yes | **GAP** |
| Semantic role labeling | Yes | **GAP** |
| Custom annotation layers | Yes | Partial (schemas are configurable) |
| Correction mode | Yes | Partial (pre-annotation) |
| Curation mode | Yes | Yes (adjudication) |
| CoNLL export formats | Yes (2000/2002/2003/2006/2009/2012) | **GAP** |
| UIMA CAS export | Yes | **GAP** |

**Key gaps:** Dependency tree annotation, multi-layer linguistic annotation, CoNLL/UIMA export formats.

#### INCEpTION

| Feature | INCEpTION | Potato |
|---------|-----------|--------|
| All WebAnno features | Yes | See above |
| Knowledge base integration | Yes | **GAP** |
| Entity linking to KB (Wikidata etc.) | Yes | **GAP** |
| Recommender framework | Yes (internal + external) | Partial (AI suggestions) |
| Real-time ML learning | Yes | Yes (active learning) |
| Fact linking / frame annotation | Yes | **GAP** |
| Plugin architecture | Yes | **GAP** (extensible via schemas but no formal plugin system) |
| IAA metrics (Cohen/Fleiss kappa, Krippendorff alpha) | Yes | Yes (Krippendorff's alpha via admin API + CLI) |

**Key gaps:** Knowledge base integration, entity linking, semantic frame annotation. (Cohen's/Fleiss' kappa not yet implemented but Krippendorff's alpha is available.)

#### doccano

| Feature | doccano | Potato |
|---------|---------|--------|
| Text classification | Yes | Yes (`radio`/`multiselect`) |
| Sequence labeling | Yes | Yes (`span`) |
| Seq2seq annotation | Yes | **GAP** (no explicit seq2seq) |
| Simple Docker deploy | Yes | Comparable |

**Key gaps:** Seq2seq task type (input text -> output text annotation). Potato's `text` schema can approximate this.

#### Prodigy

| Feature | Prodigy | Potato |
|---------|---------|--------|
| Binary accept/reject interface | Yes | **GAP** (no dedicated binary triage) |
| Scriptable recipes | Yes | **GAP** (no Python scripting interface) |
| Pattern-based bootstrapping | Yes | **GAP** |
| Model training from annotations | Yes | Partial (active learning trains models) |
| spaCy integration | Yes (native) | **GAP** |
| Custom task routing | Yes | Yes (assignment strategies) |

**Key gaps:** Binary accept/reject rapid triage interface, scriptable annotation recipes, pattern-based bootstrapping, spaCy native integration.

#### LightTag

| Feature | LightTag | Potato |
|---------|----------|--------|
| Zero-tokenization span annotation | Yes | Yes |
| Real-time collaboration | Yes | Yes |
| RTL/CJK language support | Yes | Partial (depends on browser) |
| Team-based auto assignment | Yes | Yes (`category_based`) |
| AI suggestion rate | Yes | Comparable (AI endpoints) |

**Key gaps:** Minimal. Potato is largely competitive here.

#### Label Studio (Text features)

| Feature | Label Studio | Potato |
|---------|-------------|--------|
| XML template system | Yes | YAML config (comparable) |
| Q&A annotation | Yes | Partial (`text` schema) |
| Ranking annotation | Yes | Yes (`pairwise`, `likert`) |
| LLM eval / scoring | Yes | Partial (`pairwise`) |
| Visual template builder | Yes | **GAP** |

**Key gaps:** Visual template/config builder, dedicated Q&A annotation format.

#### TagTog

| Feature | TagTog | Potato |
|---------|--------|--------|
| Biomedical entity types | Yes | Configurable (not pre-built) |
| Entity normalization via dictionaries | Yes | **GAP** |
| Ontology integration (Gene Ontology) | Yes | **GAP** |
| Full-text scientific article support | Yes | Yes (`document`/`pdf` display) |
| Semi-supervised learning | Yes | Comparable (active learning) |

**Key gaps:** Dictionary-based entity normalization, ontology/knowledge base integration (overlaps INCEpTION gap).

---

### B. Image Annotation Tools

#### CVAT

| Feature | CVAT | Potato |
|---------|------|--------|
| Bounding boxes | Yes | Yes |
| Polygons | Yes | Yes |
| Polylines | Yes | **GAP** |
| Keypoints / skeletons | Yes | Partial (landmarks) |
| Segmentation masks | Yes | **GAP** (no pixel-level masks) |
| 3D cuboids | Yes | **GAP** |
| Point cloud annotation | Yes | **GAP** |
| Video interpolation (keyframe fill) | Yes | **GAP** |
| Object tracking across frames | Yes | **GAP** |
| SAM 2 integration | Yes | **GAP** |
| COCO export | Yes | **GAP** |
| YOLO export | Yes | **GAP** |
| Pascal VOC export | Yes | **GAP** |
| KITTI export | Yes | **GAP** |

**Key gaps:** Segmentation masks, 3D cuboids, point clouds, video interpolation/tracking, SAM integration, all standard CV export formats (COCO, YOLO, VOC, KITTI).

#### LabelImg

| Feature | LabelImg | Potato |
|---------|----------|--------|
| Bounding boxes | Yes | Yes |
| Pascal VOC export | Yes | **GAP** |
| YOLO export | Yes | **GAP** |

**Key gaps:** Potato already surpasses LabelImg in features. Only gap is export formats.

#### VGG Image Annotator (VIA)

| Feature | VIA | Potato |
|---------|-----|--------|
| Circle/ellipse regions | Yes | **GAP** |
| Freehand mask regions | Yes | Yes (freeform drawing) |
| 100% offline / single HTML file | Yes | **GAP** (Potato requires server) |
| Temporal video segments | Yes | Yes |

**Key gaps:** Circle/ellipse annotation shapes. Privacy/offline mode.

#### SuperAnnotate

| Feature | SuperAnnotate | Potato |
|---------|--------------|--------|
| Smart routing (ambiguous -> humans) | Yes | Partial (`llm_confidence`) |
| SAM/AI superpixels | Yes | **GAP** |
| LiDAR annotation | Yes | **GAP** |
| Workforce management | Yes | **GAP** (basic admin only) |
| QA automation | Yes | Partial (attention checks) |

**Key gaps:** SAM-powered segmentation, LiDAR support, advanced workforce management.

#### Scalabel

| Feature | Scalabel | Potato |
|---------|----------|--------|
| 2D/3D bounding boxes | Yes | 2D only |
| Lane marking (Bezier curves) | Yes | **GAP** |
| Drivable area segmentation | Yes | **GAP** |
| Multi-object video tracking | Yes | **GAP** |

**Key gaps:** 3D annotation, domain-specific autonomous driving features. Niche use case.

#### makesense.ai

| Feature | makesense.ai | Potato |
|---------|-------------|--------|
| Zero-install browser tool | Yes | **GAP** (requires server) |
| COCO SSD pre-labeling | Yes | Potato has YOLO endpoint |
| POSE-NET keypoints | Yes | Partial (landmarks) |

**Key gaps:** Minimal. Potato is more capable overall.

---

### C. Audio Annotation Tools

#### Audacity

| Feature | Audacity | Potato |
|---------|----------|--------|
| Point labels on waveform | Yes | Yes |
| Region labels (time spans) | Yes | Yes |
| Multiple label tracks | Yes | **GAP** (single annotation layer) |
| Audio editing | Yes | **GAP** (view-only) |

**Key gaps:** Multiple parallel label tracks/tiers. Audio editing is out of scope for annotation.

#### ELAN

| Feature | ELAN | Potato |
|---------|------|--------|
| Hierarchical annotation tiers | Yes (unlimited) | **GAP** |
| Controlled vocabularies | Yes | Partial (predefined labels) |
| Video+audio sync | Yes | **GAP** (separate displays) |
| Template system for tier configs | Yes | Yes (YAML config) |
| EAF export format | Yes | **GAP** |
| TextGrid export | Yes | **GAP** |
| Interlinear glossing | Yes | **GAP** |

**Key gaps:** Hierarchical/tiered annotation layers, synchronized multi-modal timeline, linguistic export formats (EAF, TextGrid), interlinear glossing.

#### Praat

| Feature | Praat | Potato |
|---------|-------|--------|
| TextGrid (interval + point tiers) | Yes | **GAP** |
| Spectrogram visualization | Yes | **GAP** |
| Formant/pitch/intensity overlays | Yes | **GAP** |
| IPA transcription support | Yes | **GAP** |
| Scripting language | Yes | **GAP** |

**Key gaps:** Spectrogram visualization, acoustic analysis overlays, phonetic transcription support. Highly specialized for speech science.

---

### D. Video Annotation Tools

Largely covered by CVAT, VIA, ELAN, and Scalabel above.

| Feature | Best-in-class Tool | Potato |
|---------|-------------------|--------|
| Keyframe interpolation | CVAT | **GAP** |
| Object tracking across frames | CVAT, Scalabel | **GAP** |
| Frame-level classification | CVAT | Yes (`video_annotation`) |
| Temporal segmentation | ELAN, CVAT | Yes (`video_annotation`) |
| Multi-layer timeline | ELAN | **GAP** |
| Gesture/sign language annotation | ELAN | **GAP** |

---

### E. Multimodal & LLM Preference Tools

#### Label Studio (Multimodal)

| Feature | Label Studio | Potato |
|---------|-------------|--------|
| Time-series annotation | Yes | **GAP** |
| Spectrogram + waveform display | Yes | **GAP** |
| Combined text+image+audio tasks | Yes | Yes (multiple display types) |
| Conversational AI / dialogue eval | Yes | Yes (`dialogue` display + `pairwise`) |
| LLM-as-a-Judge evaluation | Yes | **GAP** |
| 30+ agreement metrics | Yes (Enterprise) | Partial (Krippendorff's alpha + MACE; no Cohen's/Fleiss' kappa) |
| Visual template editor | Yes | **GAP** |

#### OpenAssistant

| Feature | OpenAssistant | Potato |
|---------|--------------|--------|
| Conversation tree annotation | Yes | **GAP** (flat dialogue only) |
| Response ranking within trees | Yes | Partial (`pairwise`) |
| Multi-turn quality evaluation | Yes | Partial |
| Tideman ranking aggregation | Yes | **GAP** |

#### AlpacaEval

| Feature | AlpacaEval | Potato |
|---------|-----------|--------|
| Automated LLM-as-judge eval | Yes | **GAP** |
| Length-controlled win rates | Yes | **GAP** |
| Leaderboard generation | Yes | **GAP** |
| Human annotation interface | No (automated) | Yes (`pairwise`) |

#### Scale Spellbook

| Feature | Scale Spellbook | Potato |
|---------|----------------|--------|
| Prompt IDE / comparison | Yes | **GAP** |
| Multi-row prompt testing | Yes | **GAP** |
| Hit rate evaluation | Yes | **GAP** |
| Model deployment | Yes | Out of scope |

---

## 3. Consolidated Gap Prioritization

### Tier 1: High-Impact Gaps (competitive necessity)

Capabilities supported by multiple competitors and frequently requested in NLP/ML research:

| # | Gap | Competitors with Feature | Impact |
|---|-----|------------------------|--------|
| 1 | **Coreference chain annotation** | BRAT, WebAnno, INCEpTION | Core NLP task; many research teams need this |
| 2 | **Standard CV export formats** (COCO, YOLO, VOC) | CVAT, LabelImg, Label Studio | Blocks adoption for CV use cases |
| ~~3~~ | ~~**Formal IAA metrics**~~ | ~~INCEpTION, WebAnno, Label Studio~~ | Already implemented: Krippendorff's alpha available via `/admin/api/agreement` and CLI |
| 4 | **CoNLL export formats** (2003, CoNLL-U) | WebAnno, INCEpTION, doccano | Standard NLP interchange format |
| 5 | **Segmentation masks** (pixel-level) | CVAT, SuperAnnotate, Label Studio | Required for semantic segmentation tasks |
| 6 | **Conversation tree annotation** | OpenAssistant, Label Studio | Growing RLHF/LLM alignment demand |
| 7 | **LLM-as-a-Judge evaluation** | Label Studio, AlpacaEval | Scalable LLM evaluation workflow |
| 8 | **Video object tracking / interpolation** | CVAT, Scalabel | Major time-saver for video annotation |

### Tier 2: Medium-Impact Gaps (differentiation opportunity)

| # | Gap | Competitors with Feature | Impact |
|---|-----|------------------------|--------|
| 9 | **Knowledge base / entity linking** | INCEpTION, TagTog, BRAT | Important for biomedical and IE research |
| 10 | **Dependency tree annotation** | WebAnno, INCEpTION | Linguistics use cases |
| 11 | **Spectrogram visualization** | Praat, Label Studio | Speech/audio ML research |
| 12 | **Hierarchical annotation tiers** | ELAN | Linguistics, gesture, multimodal research |
| 13 | **Binary accept/reject triage** | Prodigy | Rapid data filtering/curation workflow |
| 14 | **N-ary event annotation** | BRAT | Information extraction research |
| 15 | **Discontinuous spans** | BRAT | Handling non-contiguous entity mentions |
| 16 | **Time-series annotation** | Label Studio | IoT, sensor, physiological data |
| 17 | **Visual config/template builder** | Label Studio | Lowers barrier to entry for non-technical users |

### Tier 3: Lower-Impact / Niche Gaps

| # | Gap | Competitors with Feature | Impact |
|---|-----|------------------------|--------|
| 18 | **3D cuboid / point cloud annotation** | CVAT, Scalabel | Autonomous driving niche |
| 19 | **Polyline annotation** | CVAT | Road/boundary marking niche |
| 20 | **Circle/ellipse annotation shapes** | VIA | Uncommon but occasionally useful |
| 21 | **UIMA CAS export** | WebAnno, INCEpTION | Academic NLP ecosystem |
| 22 | **EAF/TextGrid export** | ELAN, Praat | Linguistics ecosystem |
| 23 | **Pattern-based bootstrapping** | Prodigy | Useful but Potato's AI suggestions partially cover |
| 24 | **Lane marking / Bezier curves** | Scalabel | Autonomous driving only |
| 25 | **Scriptable annotation recipes** | Prodigy | Developer workflow; Potato has YAML config |
| 26 | **Interlinear glossing** | ELAN | Field linguistics niche |
| 27 | **LiDAR annotation** | SuperAnnotate, Scalabel | Specialized hardware domain |

---

## 4. Potato's Existing Competitive Strengths

Areas where Potato is already at or above parity with competitors:

| Strength | Details |
|----------|---------|
| **Breadth of AI/LLM integrations** | 14+ endpoint types including OpenAI, Anthropic, Gemini, Ollama, vLLM, YOLO -- more than any single competitor |
| **Active learning** | Model-driven uncertainty sampling + diversity clustering + LLM confidence routing |
| **ICL labeling & verification** | Unique feature: use high-agreement examples for in-context learning, then route back for human verification |
| **Pairwise comparison** | Binary + scale modes for LLM evaluation; most text tools lack this entirely |
| **MACE integration** | Built-in multi-annotator competence estimation with adjudication |
| **Data source diversity** | 8 source types (S3, HuggingFace, Google Drive, databases, etc.) |
| **Document format support** | PDF, DOCX, spreadsheet, code display with bounding box annotation |
| **Crowdsourcing integration** | MTurk + Prolific built in; most academic tools lack this |
| **Workflow phases** | Consent -> instructions -> training -> annotation -> post-study; more structured than competitors |
| **Conditional display logic** | Dynamic form visibility based on prior responses; rare feature |
| **Embedding visualization** | UMAP projection with interactive prioritization; unique to Potato |
| **Behavioral tracking** | Keystroke, mouse, timing data; unique depth of instrumentation |
| **Assignment strategies** | 8 strategies including category-based expert routing; more than most competitors |
| **Display type breadth** | 11 display types including code, spreadsheet, PDF with span targeting; wider than most tools |

---

## 5. Strategic Recommendations

### Quick Wins (export format additions, moderate effort)

These add high value for relatively low implementation cost since they are format converters over existing annotation data:

| # | Recommendation | Builds On | Priority |
|---|---------------|-----------|----------|
| 1 | Add **COCO JSON export** for `image_annotation` bounding boxes/polygons | Existing bbox/polygon data | High |
| 2 | Add **YOLO format export** for `image_annotation` | Existing bbox data | High |
| 3 | Add **CoNLL-2003 export** for `span` annotations | Existing span data | High |
| ~~4~~ | ~~Add Cohen's kappa / Krippendorff's alpha~~ | Already implemented | Already available via `/admin/api/agreement` |
| 5 | Add **Pascal VOC export** for `image_annotation` | Existing bbox data | Medium |

### Medium-Term Investments (new annotation capabilities)

| # | Recommendation | Builds On | Priority |
|---|---------------|-----------|----------|
| 6 | **Coreference chain annotation** schema | `span_link` infrastructure | High |
| 7 | **Conversation tree annotation** for LLM evaluation | `dialogue` display | High |
| 8 | **Binary accept/reject triage** mode | Lightweight new schema | Medium |
| 9 | **Segmentation mask annotation** for images | `image_annotation` brush tool | Medium |
| 10 | **LLM-as-a-Judge** automated evaluation pipeline | AI endpoints infrastructure | Medium |

### Longer-Term Differentiators

| # | Recommendation | Builds On | Priority |
|---|---------------|-----------|----------|
| 11 | **Knowledge base / entity linking** integration | `span` + external KB APIs | Medium |
| 12 | **Video keyframe interpolation** and object tracking | `video_annotation` | Low |
| 13 | **Spectrogram visualization** for audio | `audio_annotation` waveform | Low |
| 14 | **Hierarchical annotation tiers** | New multi-layer architecture | Low |
| 15 | **Visual config builder** (web UI for YAML generation) | Admin dashboard | Low |

---

## Appendix: Methodology

### Verification Sources

- **Schema types:** Verified against `potato/server_utils/schemas/registry.py` (16 registered schemas)
- **Display types:** Verified against `potato/server_utils/displays/registry.py` (11 registered display types)
- **Data sources:** Verified against `potato/data_sources/base.py` (`SourceType` enum, 8 types)
- **AI endpoints:** Verified against `potato/ai/` directory (14+ endpoint files)
- **Assignment strategies:** Verified against `potato/item_state_management.py` (`AssignmentStrategy` enum, 8 strategies)
- **Export formats:** Verified against `potato/flask_server.py` and `potato/create_task_cli.py` (JSON, JSONL, CSV, TSV)
- **Competitor features:** Cross-referenced against official documentation and public feature lists for each tool

### Tools Analyzed

**Text:** BRAT, WebAnno, INCEpTION, doccano, Prodigy, LightTag, Label Studio, TagTog
**Image:** CVAT, LabelImg, VGG Image Annotator (VIA), SuperAnnotate, Scalabel, makesense.ai
**Audio:** Audacity, ELAN, Praat
**Video:** CVAT, Scalabel, ELAN (cross-referenced from other categories)
**Multimodal/LLM:** Label Studio, OpenAssistant, AlpacaEval, Scale Spellbook
