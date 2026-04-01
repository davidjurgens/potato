# Confidence-Calibrated Annotation

The confidence annotation schema pairs any primary annotation with an explicit confidence rating. Annotators first make their label choice through a separate schema, then rate how confident they are in that choice using either a Likert scale or a continuous slider. This enables downstream filtering, calibration analysis, and active learning strategies that prioritize uncertain annotations.

## Overview

Annotator confidence is systematically underused in NLP datasets. Recording it explicitly allows researchers to:

- Filter low-confidence annotations before model training
- Weight annotations by confidence during aggregation
- Identify items where human judgment is genuinely uncertain
- Route low-confidence items to additional annotators or adjudication
- Calibrate annotator reliability over time

The confidence schema is a lightweight add-on: it contributes a single additional answer field per annotation round without disrupting the primary annotation flow.

## Research Basis

- Kutlu et al. (2020). "Annotator Rationales for Labeling Tasks in Crowdsourcing." *Journal of Artificial Intelligence Research (JAIR)*. Demonstrates that annotator self-reported confidence predicts label quality and inter-annotator agreement.
- Sheng et al. (2008). "Get Another Label? Improving Data Quality and Data Mining Using Multiple, Noisy Labelers." *KDD 2008*. Shows that confidence-weighted aggregation outperforms simple majority voting, especially under high annotator disagreement.

## Configuration

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `annotation_type` | — | Must be `confidence_annotation` |
| `name` | — | Schema identifier (required) |
| `description` | — | Prompt shown to annotators |
| `target_schema` | `null` | Name of the primary schema this confidence rating applies to |
| `scale_type` | `"likert"` | Rating input type: `likert` or `slider` |
| `scale_points` | `5` | Number of Likert points (ignored when `scale_type` is `slider`) |
| `labels` | see below | Label text for Likert options (auto-generated if omitted) |
| `slider_min` | `0` | Minimum value for slider mode |
| `slider_max` | `100` | Maximum value for slider mode |
| `label_requirement.required` | `false` | Require a confidence rating before proceeding |

Default Likert labels (5-point):
`["Not at all confident", "Slightly confident", "Moderately confident", "Very confident", "Completely confident"]`

### YAML Example — Likert Scale

```yaml
annotation_schemes:
  - annotation_type: radio
    name: sentiment
    description: "What is the sentiment of this text?"
    labels:
      - Positive
      - Neutral
      - Negative

  - annotation_type: confidence_annotation
    name: sentiment_confidence
    description: "How confident are you in your sentiment rating above?"
    target_schema: sentiment
    scale_type: likert
    scale_points: 5
    label_requirement:
      required: true
```

### YAML Example — Slider Scale

```yaml
annotation_schemes:
  - annotation_type: confidence_annotation
    name: toxicity_confidence
    description: "Rate your confidence (0 = completely uncertain, 100 = fully certain)."
    target_schema: toxicity
    scale_type: slider
    slider_min: 0
    slider_max: 100
    label_requirement:
      required: true
```

## Output Format

### Likert Scale Output

The selected Likert point is stored as its 1-based position string:

```json
{
  "sentiment_confidence": {
    "3": "3"
  }
}
```

### Slider Scale Output

```json
{
  "sentiment_confidence": {
    "confidence_level": "75"
  }
}
```

## Use Cases

- **Annotator calibration studies** — measure how well self-reported confidence predicts accuracy
- **Data quality filtering** — exclude annotations below a confidence threshold before training
- **Active learning** — surface items where annotators consistently express low confidence
- **Adjudication prioritization** — flag low-confidence annotations for expert review
- **Uncertainty quantification** — train models to predict human uncertainty, not just labels
- **Crowdsourcing quality control** — detect unreliable workers who are overconfident on difficult items

## Troubleshooting

**Annotators always select maximum confidence:** Add a calibration note in the instructions explaining that partial confidence is expected and valued. Consider showing examples of genuinely ambiguous items.

**target_schema has no effect on display:** The `target_schema` field links the confidence rating semantically in the output; it does not automatically co-locate the widgets. Place the confidence schema immediately after the target schema in `annotation_schemes` for natural visual grouping.

## Related Documentation

- [Likert Scale](schemas_and_templates.md#likert) — standalone Likert rating schema
- [Slider](schemas_and_templates.md#slider) — continuous numeric slider schema
- [Quality Control](quality_control.md) — attention checks and gold standards
- [Active Learning](active_learning_guide.md) — ML-based item prioritization
