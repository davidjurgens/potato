# Standard Survey Instruments Library

Potato includes a library of 55 validated survey instruments for use in prestudy and poststudy phases. These instruments cover personality assessment, mental health screening, affect measurement, social attitudes, demographic batteries, and more.

## Quick Start

Use a standard instrument in your config by specifying its ID:

```yaml
phases:
  order: [consent, prestudy, annotation, poststudy]

  prestudy:
    type: prestudy
    instrument: "tipi"  # 10-item personality questionnaire

  poststudy:
    type: poststudy
    instrument: "phq-9"  # 9-item depression screening
```

## Available Instruments

### Personality (6 instruments)

| ID | Name | Items | Description |
|----|------|-------|-------------|
| `bfi-2` | Big Five Inventory-2 | 60 | Comprehensive Big Five personality assessment |
| `tipi` | Ten-Item Personality Inventory | 10 | Ultra-brief Big Five personality measure |
| `pvq-ess` | Portrait Values Questionnaire (ESS) | 21 | Human values from European Social Survey |
| `nfc` | Need for Cognition Scale | 18 | Tendency to engage in and enjoy thinking |
| `ztpi` | Zimbardo Time Perspective Inventory | 56 | Time perspective and temporal orientation |
| `gse` | General Self-Efficacy Scale | 10 | Perceived self-efficacy in coping |

### Mental Health & Well-being (12 instruments)

| ID | Name | Items | Description |
|----|------|-------|-------------|
| `phq-9` | Patient Health Questionnaire-9 | 9 | Depression screening and severity |
| `gad-7` | Generalized Anxiety Disorder-7 | 7 | Anxiety screening and severity |
| `k6` | Kessler Psychological Distress (K6) | 6 | Brief psychological distress screening |
| `k10` | Kessler Psychological Distress (K10) | 10 | Psychological distress screening |
| `ces-d` | CES Depression Scale | 20 | Depression symptoms in general population |
| `pss-10` | Perceived Stress Scale | 10 | Perception of stress in the last month |
| `brs` | Brief Resilience Scale | 6 | Ability to bounce back from stress |
| `swls` | Satisfaction With Life Scale | 5 | Global life satisfaction |
| `shs` | Subjective Happiness Scale | 4 | Global subjective happiness |
| `who-5` | WHO Well-Being Index | 5 | Positive psychological well-being |
| `ghq-12` | General Health Questionnaire-12 | 12 | Psychiatric morbidity screening |
| `sias` | Social Interaction Anxiety Scale | 20 | Anxiety in social situations |

### Affect & Emotion (2 instruments)

| ID | Name | Items | Description |
|----|------|-------|-------------|
| `panas` | Positive and Negative Affect Schedule | 20 | Positive and negative emotional states |
| `iri` | Interpersonal Reactivity Index | 28 | Multidimensional empathy measure |

### Self-Concept & Social (6 instruments)

| ID | Name | Items | Description |
|----|------|-------|-------------|
| `rse` | Rosenberg Self-Esteem Scale | 10 | Global self-esteem |
| `ucla-loneliness` | UCLA Loneliness Scale (v3) | 20 | Subjective feelings of loneliness |
| `mos-ss` | MOS Social Support Survey | 19 | Perceived social support availability |
| `macarthur-ladder` | MacArthur Subjective Social Status | 1 | Perceived social status |
| `ios` | Inclusion of Other in Self Scale | 1 | Interpersonal closeness |
| `cses` | Collective Self-Esteem Scale | 16 | Self-esteem from group memberships |

### Social/Political Attitudes (8 instruments)

| ID | Name | Items | Description |
|----|------|-------|-------------|
| `sdo-7` | Social Dominance Orientation | 16 | Preference for group-based hierarchy |
| `rwa` | Right-Wing Authoritarianism | 22 | Authoritarian attitudes |
| `mfq` | Moral Foundations Questionnaire | 30 | Moral reasoning across five foundations |
| `trust-ess` | Social Trust Scale (ESS) | 3 | Generalized social trust |
| `rotter-trust` | Interpersonal Trust Scale | 25 | Trust in others |
| `eds` | Everyday Discrimination Scale | 9 | Day-to-day discrimination experiences |
| `political-efficacy` | Political Efficacy Scale (ANES) | 4 | Belief in political influence |
| `rci-10` | Religious Commitment Inventory | 10 | Religious commitment |

### Response Style (1 instrument)

| ID | Name | Items | Description |
|----|------|-------|-------------|
| `mc-sds` | Marlowe-Crowne Social Desirability | 33 | Socially desirable responding |

### Short-Form Instruments (12 instruments)

Ultra-brief versions of common instruments for time-constrained studies:

| ID | Name | Items | Description |
|----|------|-------|-------------|
| `bfi-10` | Big Five Inventory-10 | 10 | Ultra-brief Big Five personality |
| `mini-ipip` | Mini-IPIP | 20 | 20-item short form of IPIP-FFM |
| `phq-2` | Patient Health Questionnaire-2 | 2 | Ultra-brief depression screening |
| `gad-2` | Generalized Anxiety Disorder-2 | 2 | Ultra-brief anxiety screening |
| `pss-4` | Perceived Stress Scale-4 | 4 | Ultra-brief perceived stress |
| `ucla-loneliness-3` | UCLA Loneliness Scale-3 | 3 | Ultra-brief loneliness screening |
| `grips` | GRAT-Short (Gratitude) | 8 | Short-form gratitude measure |
| `mfq-20` | Moral Foundations Questionnaire-20 | 20 | Short form of MFQ |
| `sdo-7-short` | SDO7(s) Short Form | 8 | Brief social dominance orientation |
| `rwa-short` | RWA Short Scale | 12 | Short form right-wing authoritarianism |
| `bscs` | Brief Self-Control Scale | 13 | Brief dispositional self-control |
| `srh` | Single-Item Self-Rated Health | 1 | Global health status |

### Demographic Batteries (8 instruments)

Standard demographic question sets from major surveys:

| ID | Name | Items | Description |
|----|------|-------|-------------|
| `anes-demographics` | ANES Demographic Battery | 12 | American National Election Studies |
| `gss-demographics` | GSS Core Demographics | 14 | General Social Survey |
| `ess-demographics` | ESS Core Demographics | 12 | European Social Survey |
| `wvs-demographics` | WVS Demographics | 12 | World Values Survey |
| `hrs-ses` | HRS SES Module | 14 | Health and Retirement Study |
| `midus-demographics` | MIDUS Core Demographics | 13 | Midlife in the United States |
| `ipums-demographics` | IPUMS Harmonized Demographics | 12 | Cross-survey compatible demographics |
| `acs-demographics` | ACS Demographics | 14 | American Community Survey |

## Using Multiple Instruments

Combine multiple instruments in a single phase:

```yaml
phases:
  poststudy:
    type: poststudy
    instruments:
      - "phq-9"
      - "gad-7"
      - "pss-10"
```

## Combining with Custom Questions

Add custom questions after instrument questions:

```yaml
phases:
  poststudy:
    type: poststudy
    instrument: "panas"
    file: surveys/demographics.json  # Appended after instrument
```

## Using Demographic Batteries

Collect standardized demographics in prestudy:

```yaml
phases:
  prestudy:
    type: prestudy
    instruments:
      - "gss-demographics"  # Core demographics
      - "srh"               # Single health item
```

Or use a compact battery for quick collection:

```yaml
phases:
  prestudy:
    type: prestudy
    instrument: "ipums-demographics"  # Harmonized cross-survey format
```

## Instrument File Format

Each instrument is stored as a JSON file with this structure:

```json
{
  "id": "phq-9",
  "name": "Patient Health Questionnaire-9",
  "short_name": "PHQ-9",
  "description": "A 9-item self-report measure...",
  "url": "https://www.phqscreeners.com/",
  "reference": "Kroenke, K. et al. (2001)...",
  "items_count": 9,
  "domains": ["mental_health", "depression"],
  "scoring": {
    "method": "sum",
    "range": [0, 27],
    "interpretation": {...}
  },
  "instructions": "Over the last 2 weeks...",
  "questions": [
    {
      "name": "phq9_1",
      "description": "Little interest or pleasure...",
      "annotation_type": "radio",
      "labels": [...],
      "label_requirement": {"required": true}
    }
  ]
}
```

## API Reference

The survey instruments can also be accessed programmatically:

```python
from potato.survey_instruments import (
    get_registry,
    get_instrument,
    get_instrument_questions,
    list_instruments,
    get_categories
)

# List all available instruments
instruments = list_instruments()

# List instruments by category
mental_health = list_instruments(category="mental_health")
short_forms = list_instruments(category="short_forms")
demographics = list_instruments(category="demographics")

# Get full instrument definition
phq9 = get_instrument("phq-9")
print(phq9["description"])

# Get just the questions (for annotation schemes)
questions = get_instrument_questions("tipi")

# Get all categories
categories = get_categories()
```

## Adding Custom Instruments

To add a custom instrument:

1. Create a JSON file following the format above in `potato/survey_instruments/instruments/`
2. Register it in `potato/survey_instruments/registry.json`

The questions use standard Potato annotation types:
- `radio` - Single choice with labels
- `likert` - Likert scale with min/max labels
- `slider` - Numeric slider
- `textbox` - Free text input

## Scoring Information

Each instrument includes scoring metadata:

- `method`: How to compute scores (sum, mean, subscales)
- `reverse_items`: Items that need reverse coding
- `range`: Expected score range
- `interpretation`: Clinical/normative cutoffs

Note: Potato does not automatically compute scores. The scoring information is provided for researchers to implement their own scoring logic during data analysis.

## Citations

Each instrument file includes:
- `reference`: Full citation for the original publication
- `reference_url`: DOI or URL to the publication
- `url`: Link to the instrument website or documentation

When using these instruments, please cite the original authors according to the provided references.

## Example Project

See `project-hub/simple_examples/simple-survey-demo/` for a complete example using survey instruments.

## Backward Compatibility

The existing `file:` syntax continues to work unchanged. The `instrument:` and `instruments:` keys are additions, not replacements.
