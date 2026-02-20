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
| `image-annotation/` | Image region annotation |
| `image-classification/` | Image classification |
| `image-ai-detection/` | AI-generated image detection |
| `image-vllm-rationale/` | Image annotation with vLLM rationale |
| `pdf-annotation/` | PDF document annotation |
| `pdf-bbox/` | PDF bounding box annotation |
| `document-bbox/` | Document bounding box annotation |
| `document-annotation/` | Document format annotation |

### [advanced/](advanced/) - Complex Features & Workflows

| Example | Description |
|---------|-------------|
| `all-annotation-types/` | Demo of every annotation type |
| `all-phases-example/` | Full workflow with all phases |
| `conditional-logic/` | Show/hide questions based on answers |
| `multi-modal/` | Multi-modal (text + image) annotation |
| `grid-layout/` | Grid-based annotation layout |
| `option-highlight/` | Dynamic keyword highlighting |
| `triage/` | Annotation triage workflow |
| `adjudication/` | Multi-annotator adjudication |
| `mace-demo/` | MACE aggregation demo |
| `active-learning/` | Active learning prioritization |
| `quality-control/` | Attention checks and gold standards |
| `mturk-example/` | Amazon MTurk integration |
| `diversity/` | Diversity-based ordering |
| `diversity-test/` | Diversity ordering test |
| `embedding-visualization/` | Embedding space visualization |
| `kwargs-example/` | Custom keyword arguments |
| `url-data/` | Loading data from URLs |
| `html-annotation/` | HTML content annotation |
| `code-annotation/` | Source code annotation |
| `spreadsheet-annotation/` | Tabular data annotation |

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

Research paper annotation projects have moved to the **[Potato Showcase](https://github.com/davidjurgens/potato-showcase/)** repository. Use `potato get <project>` to download them:

```bash
potato list all           # See available projects
potato get sentiment_analysis  # Download a project
```
