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
| `pdf-annotation/` | PDF document annotation |
| `pdf-bbox/` | PDF bounding box annotation |
| `document-bbox/` | Document bounding box annotation |

### [spatial/](spatial/) - 3D Point Clouds

| Example | Description |
|---------|-------------|
| `kitti-cuboids/` | Oriented 3D boxes on a lidar scan — KITTI `.bin`, PCD, PLY and LAS all load |

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
