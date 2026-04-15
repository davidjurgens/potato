# Choosing the Right Annotation Type

With 36 annotation schema types, Potato covers virtually every annotation paradigm used in NLP research, LLM evaluation, survey methodology, and crowdsourcing. This guide helps you choose the right schema for your task.

## Decision Flowchart

```
What kind of judgment do you need?
│
├─ CLASSIFY items into categories
│  ├─ One label per item?
│  │  ├─ Few options (2-10) → radio
│  │  ├─ Many options (10+) → select (dropdown)
│  │  └─ Quick accept/reject → triage
│  ├─ Multiple labels per item?
│  │  ├─ Flat list → multiselect
│  │  └─ Hierarchical tree → hierarchical_multiselect
│  └─ Per-item confidence? → Add confidence schema after primary
│
├─ RATE / SCORE items
│  ├─ Single dimension
│  │  ├─ Discrete points (1-7) → likert
│  │  ├─ Discrete slider with steps → slider
│  │  ├─ Continuous (no tick marks) → vas
│  │  └─ Acceptable range (min-max) → range_slider
│  ├─ Multiple dimensions
│  │  ├─ Same items, different criteria → multirate
│  │  ├─ Different criteria, same scales → rubric_eval
│  │  └─ Bipolar adjective pairs → semantic_differential
│  └─ Per-rating justification? → Add text schema with target_schema
│
├─ COMPARE items
│  ├─ Two items → pairwise
│  ├─ Best + worst from set → bws
│  ├─ Full ordering → ranking
│  └─ Multi-attribute profiles → conjoint
│
├─ DISTRIBUTE / ALLOCATE
│  ├─ Probability across labels → soft_label
│  └─ Fixed budget of points → constant_sum
│
├─ ANNOTATE TEXT STRUCTURE
│  ├─ Label spans in text → span
│  ├─ Relationships between spans → span_link
│  ├─ Coreference chains → coreference
│  ├─ Event triggers + arguments → event_annotation
│  ├─ Answer a question from passage → extractive_qa
│  └─ Mark errors with type/severity → error_span
│
├─ PRODUCE / EDIT TEXT
│  ├─ Free text input → text
│  └─ Edit existing text with diff → text_edit
│
├─ ORGANIZE / GROUP
│  ├─ Sort items into groups → card_sort
│  ├─ Order items → ranking
│  └─ Select from hierarchy → hierarchical_multiselect
│
└─ ANNOTATE MEDIA
   ├─ Images (bbox, polygon, landmarks) → image_annotation
   ├─ Audio (segments, labels) → audio_annotation
   ├─ Video (temporal segments, tracking) → video_annotation
   └─ Multi-tier time-aligned → tiered_annotation
```

## Quick Reference Table

| Type Key | Description | Output | Typical Use Case |
|----------|-------------|--------|-----------------|
| `radio` | Single-choice radio buttons | `{"label": "value"}` | Sentiment, intent classification |
| `multiselect` | Multiple-choice checkboxes | `{"label1": "val", "label2": "val"}` | Multi-label classification |
| `select` | Dropdown selection | `{"label": "value"}` | Many categories (10+) |
| `likert` | Discrete point scale | `{"label": "3"}` | Agreement, quality rating |
| `slider` | Numeric slider with steps | `{"label": "75"}` | Bounded numeric judgments |
| `vas` | Continuous analog scale | `{"label": "67.3"}` | Fine-grained magnitude estimation |
| `range_slider` | Dual-thumb range | `{"low": "30", "high": "70"}` | Acceptable range annotation |
| `text` | Free text input / textarea | `{"text_box": "..."}` | Open-ended responses, rationales |
| `number` | Numeric input field | `{"label": "42"}` | Count, quantity annotation |
| `span` | Text span highlighting | via span API | NER, POS tagging |
| `span_link` | Relationships between spans | via span API | Relation extraction |
| `coreference` | Coreference chains | via span API | Entity coreference |
| `event_annotation` | Event triggers + arguments | via event API | Event extraction |
| `extractive_qa` | Answer span in passage | `{"answer_text", "start", "end"}` | Reading comprehension |
| `error_span` | Error spans with type/severity | `{"errors": [...], "score": N}` | MQM translation evaluation |
| `pairwise` | Compare two items | `{"label": "A"}` | Model comparison |
| `bws` | Best-worst from a set | `{"best": "X", "worst": "Y"}` | Relative scaling |
| `ranking` | Drag-and-drop ordering | `{"order": "a,b,c"}` | Preference ranking |
| `conjoint` | Choose from multi-attribute profiles | `{"chosen_profile": 2}` | Attribute importance |
| `multirate` | Rate multiple items on a scale | `{"item1": "3", "item2": "5"}` | Batch rating |
| `rubric_eval` | Multi-criteria rating grid | `{"crit1": "4", "crit2": "5"}` | LLM evaluation rubrics |
| `semantic_differential` | Bipolar adjective scales | `{"pair1": "3"}` | Connotative meaning |
| `soft_label` | Probability distribution sliders | `{"label1": "60", "label2": "40"}` | Uncertainty capture |
| `confidence` | Confidence meta-annotation | `{"value": "4"}` | Annotator certainty |
| `constant_sum` | Fixed-budget point allocation | `{"label1": "30", "label2": "70"}` | Relative importance |
| `text_edit` | Edit text with diff tracking | `{"edited_text", "edit_distance"}` | MT post-editing |
| `card_sort` | Drag items into groups | `{"group1": ["a","b"]}` | Taxonomy, IA testing |
| `hierarchical_multiselect` | Tree-structured label selection | `{"selected": "path"}` | Deep taxonomies |
| `triage` | Accept/reject/skip | `{"decision": "accept"}` | Rapid data curation |
| `image_annotation` | Bbox, polygon, landmarks | JSON annotation data | Object detection |
| `audio_annotation` | Audio segment labeling | JSON annotation data | Speech, music analysis |
| `video_annotation` | Video temporal annotation | JSON annotation data | Activity recognition |
| `tiered_annotation` | Multi-tier time-aligned | JSON annotation data | ELAN-style annotation |
| `pure_display` | Display-only content | (none) | Instructions, headers |
| `video` | Video player | (none) | Video display |
| `tree_annotation` | Conversation tree | JSON annotation data | Dialogue analysis |

## By Research Goal

### "I need to classify items"

| If you need... | Use | Why |
|---------------|-----|-----|
| One label per item, few options | `radio` | Simple, supports keyboard shortcuts |
| One label, many options | `select` | Dropdown saves space |
| Quick binary decision | `triage` | Accept/reject with one click |
| Multiple labels per item | `multiselect` | Checkboxes for independent labels |
| Labels from a deep hierarchy | `hierarchical_multiselect` | Tree with search and auto-propagation |

### "I need to rate or score items"

| If you need... | Use | Why |
|---------------|-----|-----|
| Discrete points (1-5, 1-7) | `likert` | Standard survey scale |
| Numeric value with steps | `slider` | Visual, bounded |
| Continuous, no discrete bins | `vas` | Psychophysical precision |
| An acceptable range | `range_slider` | Dual-thumb min/max |
| Rate on multiple criteria | `rubric_eval` | Grid layout, ideal for LLM eval |
| Rate multiple items on one scale | `multirate` | Items × options matrix |
| Bipolar adjective pairs | `semantic_differential` | Warm-Cold, Good-Bad scales |

### "I need to compare items"

| If you need... | Use | Why |
|---------------|-----|-----|
| Compare exactly 2 items | `pairwise` | A vs B (binary or scale) |
| Best and worst from a set | `bws` | Best-worst scaling |
| Full preference ordering | `ranking` | Drag-and-drop reorder |
| Choose among multi-attribute profiles | `conjoint` | Attribute importance estimation |

### "I need to distribute or allocate"

| If you need... | Use | Why |
|---------------|-----|-----|
| Probability across labels | `soft_label` | Constrained sliders summing to 100% |
| Fixed budget of points | `constant_sum` | Allocate N points across categories |

### "I need to annotate text structure"

| If you need... | Use | Why |
|---------------|-----|-----|
| Label spans (NER, POS) | `span` | Multi-label span highlighting |
| Relationships between spans | `span_link` | Directed edges between spans |
| Coreference chains | `coreference` | Group mentions of same entity |
| Event extraction | `event_annotation` | Triggers + typed arguments |
| Answer a question from text | `extractive_qa` | SQuAD-style QA |
| Mark errors with type/severity | `error_span` | MQM quality evaluation |

### "I need annotators to produce or edit text"

| If you need... | Use | Why |
|---------------|-----|-----|
| Free text response | `text` | Textarea with optional min_chars |
| Edit existing text with change tracking | `text_edit` | Diff visualization + edit distance |
| Justification for another annotation | `text` with `target_schema` | Visual grouping as rationale |

### "I need to evaluate AI outputs"

| If you need... | Use | Why |
|---------------|-----|-----|
| Multi-criteria rubric | `rubric_eval` | MT-Bench-style evaluation |
| A vs B comparison | `pairwise` | Which response is better |
| Rank multiple outputs | `ranking` | Preference ordering |
| Identify specific errors | `error_span` | MQM-style error annotation |
| Post-edit model output | `text_edit` | Correction with diff |
| Rate confidence in evaluation | `confidence` | Meta-annotation |

### "I need to capture uncertainty"

| If you need... | Use | Why |
|---------------|-----|-----|
| Per-annotation confidence | `confidence` | Meta-annotation schema |
| Probability distribution | `soft_label` | Label probability sliders |
| Acceptable range | `range_slider` | Min-max bounds |
| Fine-grained continuous rating | `vas` | No discrete anchoring |

## Head-to-Head Comparisons

### likert vs slider vs vas

- **likert**: Discrete points (1-7) with labeled buttons. Best for standard survey scales where distinct categories matter.
- **slider**: Discrete steps along a track with visible tick marks and value display. Best for bounded numeric values.
- **vas**: Continuous line with endpoint labels only, no tick marks. Best for magnitude estimation where you want maximum precision without anchoring to discrete values.

### radio vs select vs triage

- **radio**: Visible buttons, supports keyboard shortcuts. Best for 2-10 options that annotators need to see.
- **select**: Dropdown, compact. Best for 10+ options where space matters.
- **triage**: Binary accept/reject with optional skip. Best for rapid data curation.

### pairwise vs bws vs ranking vs conjoint

- **pairwise**: Compare exactly 2 items. Simplest, most reliable.
- **bws**: Select best + worst from 3-5 items. Efficient relative scaling.
- **ranking**: Full ordering of all items. Most informative but cognitively demanding.
- **conjoint**: Choose among multi-attribute profiles. Best for attribute importance.

### multirate vs rubric_eval vs semantic_differential

- **multirate**: Rate multiple items (from data) on the same set of options. Rows = items, columns = options.
- **rubric_eval**: Rate one item on multiple criteria. Rows = criteria (from config), columns = scale points.
- **semantic_differential**: Rate on bipolar adjective pairs. Rows = adjective pairs, columns = scale points between poles.

### span vs extractive_qa vs error_span

- **span**: General multi-label span annotation (NER, POS, etc.). Multiple spans, multiple categories.
- **extractive_qa**: Single answer span for a specific question. One span at a time, with "unanswerable" option.
- **error_span**: Error spans with type taxonomy and severity. Multiple spans, each with type + severity + quality score.

### text vs text_edit

- **text**: Free text input for new content (responses, rationales, translations from scratch).
- **text_edit**: Edit existing text with change tracking (post-editing, correction, simplification).

### soft_label vs constant_sum

- **soft_label**: Probability distribution. Sliders auto-normalize to 100%. For label uncertainty.
- **constant_sum**: Fixed budget allocation. Manual balancing. For relative importance judgments.

### multiselect vs hierarchical_multiselect

- **multiselect**: Flat list of checkboxes. For independent labels without hierarchy.
- **hierarchical_multiselect**: Tree with expand/collapse, search, auto-propagation. For deep taxonomies.

### ranking vs card_sort

- **ranking**: Order items along one dimension (preference, relevance).
- **card_sort**: Group items into categories (topic, similarity). No ordering within groups.

## Combining Schemas

Potato supports multiple annotation schemas per task. Common patterns:

### Classification + Confidence

```yaml
annotation_schemes:
  - annotation_type: radio
    name: sentiment
    labels: ["Positive", "Negative", "Neutral"]
  - annotation_type: confidence
    name: confidence
    target_schema: sentiment
```

### Classification + Rationale

```yaml
annotation_schemes:
  - annotation_type: radio
    name: toxicity
    labels: ["Toxic", "Not toxic"]
  - annotation_type: text
    name: rationale
    description: "Why did you choose this label?"
    target_schema: toxicity
    min_chars: 10
    show_char_count: true
    collapsible: true
    multiline: true
    rows: 3
```

### Multi-Dimensional LLM Evaluation

```yaml
annotation_schemes:
  - annotation_type: rubric_eval
    name: quality
    criteria:
      - name: helpfulness
      - name: accuracy
      - name: safety
    scale_points: 5
    show_overall: true
  - annotation_type: confidence
    name: eval_confidence
    target_schema: quality
  - annotation_type: text
    name: justification
    description: "Explain your ratings"
    target_schema: quality
    min_chars: 20
    show_char_count: true
    multiline: true
    rows: 4
```

### Error Annotation + Post-Edit

```yaml
annotation_schemes:
  - annotation_type: error_span
    name: errors
    error_types:
      - name: Accuracy
        subtypes: ["Omission", "Mistranslation"]
      - name: Fluency
        subtypes: ["Grammar", "Spelling"]
    show_score: true
  - annotation_type: text_edit
    name: correction
    source_field: "mt_output"
    show_diff: true
```
