# Semantic Differential

The semantic differential schema measures the connotative meaning of words, phrases, or texts by placing them on a series of bipolar adjective scales. Each scale runs between two antonyms (e.g., *Good — Bad*, *Strong — Weak*) with a 7-point (or configurable) rating. This is one of the most established psycholinguistic measurement instruments in the social sciences.

## Overview

Osgood's semantic differential revealed that connotative meaning clusters into three primary dimensions:

- **Evaluation** — Good/Bad, Pleasant/Unpleasant, Beautiful/Ugly
- **Potency** — Strong/Weak, Large/Small, Heavy/Light
- **Activity** — Active/Passive, Fast/Slow, Sharp/Dull

Potato's implementation presents all bipolar pairs for a single item simultaneously, with the left adjective anchoring the negative pole and the right adjective anchoring the positive pole. Annotators drag a slider or click a point on each scale.

## Research Basis

- Osgood, C. E., Suci, G. J., & Tannenbaum, P. H. (1957). *The Measurement of Meaning*. University of Illinois Press. Foundational work introducing the semantic differential and demonstrating the EPA (Evaluation, Potency, Activity) structure of meaning.
- Mohammad, S. M. (2018). "Obtaining Reliable Human Ratings of Valence, Arousal, and Dominance for 20,000 English Words." *ACL 2018*. Large-scale modern application of semantic differential to NLP lexical resources (NRC VAD Lexicon).

## Configuration

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `annotation_type` | — | Must be `semantic_differential` |
| `name` | — | Schema identifier (required) |
| `description` | — | Instruction shown above the scale grid |
| `pairs` | — | List of `[left_adjective, right_adjective]` pairs (required) |
| `scale_points` | `7` | Number of points on each scale (typically 5 or 7) |
| `show_center_label` | `true` | Label the center point as "Neutral" |
| `label_requirement.required` | `false` | Require all scales to be rated |

### YAML Example

```yaml
annotation_schemes:
  - annotation_type: semantic_differential
    name: word_meaning
    description: "Rate the meaning of the highlighted word on each scale. Select the point that best reflects your sense of the word's connotation."
    scale_points: 7
    show_center_label: true
    pairs:
      - [Bad, Good]
      - [Unpleasant, Pleasant]
      - [Weak, Strong]
      - [Small, Large]
      - [Passive, Active]
      - [Slow, Fast]
    label_requirement:
      required: true
```

### EPA Subset Example

For tasks focusing only on the Evaluation dimension:

```yaml
annotation_schemes:
  - annotation_type: semantic_differential
    name: valence_rating
    description: "How positive or negative is the sentiment expressed in this sentence?"
    scale_points: 7
    pairs:
      - [Negative, Positive]
      - [Bad, Good]
      - [Unpleasant, Pleasant]
```

### Brand Perception Example

```yaml
annotation_schemes:
  - annotation_type: semantic_differential
    name: brand_perception
    description: "Rate this brand description on each dimension."
    scale_points: 5
    pairs:
      - [Untrustworthy, Trustworthy]
      - [Old-fashioned, Modern]
      - [Cold, Warm]
      - [Niche, Mainstream]
```

## Output Format

Each bipolar pair is stored with a key formed from `LeftAdjective__RightAdjective` (double underscore separator). The value is the 1-based position on the scale:

```json
{
  "word_meaning": {
    "Bad__Good": "6",
    "Unpleasant__Pleasant": "5",
    "Weak__Strong": "4",
    "Small__Large": "3",
    "Passive__Active": "6",
    "Slow__Fast": "7"
  }
}
```

A value of `1` corresponds to the leftmost (negative) pole; a value of `scale_points` corresponds to the rightmost (positive) pole. The midpoint is `ceil(scale_points / 2)`.

## Use Cases

- **Sentiment lexicon construction** — rate words on valence, arousal, and dominance dimensions
- **Brand and product perception** — measure connotative associations with brand names or descriptions
- **Figurative language** — measure connotative shifts introduced by metaphors or idioms
- **Cross-lingual semantic comparison** — compare EPA ratings across translated terms
- **Affective computing** — build training data for emotion-aware NLP systems
- **Psycholinguistic studies** — measure reader responses to stylistic choices

## Troubleshooting

**Annotators overuse the center point:** Provide clear examples in instructions showing what an extreme rating looks like. Consider a 6-point scale (no center) to force a directional judgment.

**Scale order effects:** Counterbalance the order of bipolar pairs across annotators if your study design requires it. This can be achieved by defining multiple schemas with different pair orderings and assigning them to different user groups.

## Related Documentation

- [Likert Scale](schemas_and_templates.md#likert) — unipolar rating scales
- [Multirate](schemas_and_templates.md#multirate) — rating matrix for multiple items/dimensions
- [Slider](schemas_and_templates.md#slider) — single continuous numeric slider
- [Schema Gallery](schemas_and_templates.md) — all annotation types with examples
