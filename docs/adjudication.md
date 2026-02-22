# Adjudication Mode

## Overview

Adjudication is a quality assurance workflow that allows designated reviewers (adjudicators) to resolve disagreements between annotators and produce gold-standard final labels. In any multi-annotator project, annotators will inevitably disagree on some items -- whether due to ambiguous text, gaps in annotation guidelines, or genuine annotator error. Adjudication provides a structured process for a subject-matter expert to review these disagreements, examine each annotator's response alongside timing data and agreement scores, and render a final decision.

Adjudication in Potato is implemented as a **parallel workflow**, not a phase. Adjudicators access a dedicated `/adjudicate` route with its own interface, separate from the standard annotation flow. This design avoids disrupting the existing phase progression system (consent, instructions, training, annotation, post-study) while giving adjudicators a purpose-built environment for reviewing and resolving conflicts.

### When to Use Adjudication

- You have multiple annotators labeling the same items and need to produce a single gold-standard label per item.
- You want a human-in-the-loop process for resolving inter-annotator disagreements rather than relying solely on majority vote.
- You need provenance tracking that records whether each final label came from unanimous agreement or an adjudicator's decision.
- You want to categorize sources of disagreement (ambiguous text, guideline gaps, annotator error) to improve your annotation guidelines over time.

---

## Configuration

Adjudication is configured through the `adjudication` section of your project's YAML config file. Below is a complete example with all available options and their descriptions.

```yaml
# Adjudication configuration
adjudication:
  # Enable or disable adjudication mode.
  # Type: bool
  # Default: false
  enabled: true

  # List of usernames authorized to access the adjudication interface.
  # These users can log in and navigate to /adjudicate. Regular annotators
  # cannot access this route.
  # Type: list of strings
  adjudicator_users:
    - "adjudicator"
    - "senior_annotator"

  # Minimum number of annotations an item must have before it becomes
  # eligible for adjudication. Items with fewer annotations are excluded
  # from the queue.
  # Type: int
  # Default: 2
  min_annotations: 2

  # Agreement threshold (0.0 to 1.0). Items with overall agreement at or
  # above this threshold are considered resolved and excluded from the
  # adjudication queue (unless show_all_items is true). Lower values mean
  # fewer items need adjudication; higher values are more conservative.
  # Type: float
  # Default: 0.75
  agreement_threshold: 0.75

  # When true, all items that meet the min_annotations criterion appear
  # in the queue, including items where annotators unanimously agree.
  # Useful for auditing or when you want adjudicators to verify even
  # unanimous decisions.
  # Type: bool
  # Default: false
  show_all_items: false

  # Whether to display annotator usernames in the adjudication interface.
  # When false, annotations are shown as "Annotator" without identifying
  # information, which can reduce bias.
  # Type: bool
  # Default: true
  show_annotator_names: true

  # Whether to display per-annotator timing data (how long each annotator
  # spent on the item). Helps adjudicators identify rushed annotations.
  # Type: bool
  # Default: true
  show_timing_data: true

  # Whether to display per-schema agreement scores in the interface.
  # Type: bool
  # Default: true
  show_agreement_scores: true

  # Time threshold in milliseconds. If an annotator spent less than this
  # amount on an item, their annotation is flagged with a warning icon
  # to alert the adjudicator that the decision may have been rushed.
  # Set to 0 to disable the warning.
  # Type: int
  # Default: 2000
  fast_decision_warning_ms: 2000

  # Whether the adjudicator is required to select a confidence level
  # (high, medium, low) for each decision.
  # Type: bool
  # Default: true
  require_confidence: true

  # Whether the adjudicator must provide notes when overriding all
  # annotators' choices (i.e., when the final decision does not match
  # any annotator's response).
  # Type: bool
  # Default: false
  require_notes_on_override: false

  # List of error category labels that adjudicators can assign to
  # classify the source of disagreement. Customize these to match your
  # project's needs.
  # Type: list of strings
  # Default: [ambiguous_text, guideline_gap, annotator_error,
  #           edge_case, subjective_disagreement, other]
  error_taxonomy:
    - "ambiguous_text"
    - "guideline_gap"
    - "annotator_error"
    - "edge_case"
    - "subjective_disagreement"
    - "other"

  # Similarity-based item grouping (not yet available -- reserved for
  # a future release). When enabled, similar items would be shown
  # alongside the current item to help adjudicators maintain consistency.
  # Type: object
  similarity:
    enabled: false
    # model: "all-MiniLM-L6-v2"
    # top_k: 5
    # precompute_on_start: true

  # Subdirectory name within the annotation output directory where
  # adjudication decisions are stored.
  # Type: string
  # Default: "adjudication"
  output_subdir: "adjudication"
```

### Required Supporting Configuration

Adjudication requires that multiple annotators can be assigned to the same item. Make sure your main config includes:

```yaml
# Allow multiple annotators per item (must be >= min_annotations)
max_annotations_per_item: 3
```

---

## How It Works

The adjudication workflow consists of three stages: annotation, adjudication, and export.

### Stage 1: Annotation

Regular annotators complete their work through the standard `/annotate` interface. As annotations accumulate, the adjudication system monitors each item's annotation count and inter-annotator agreement.

### Stage 2: Queue Building and Adjudication

When an adjudicator logs in and navigates to `/adjudicate`, the system builds the adjudication queue by scanning all items. An item enters the queue when:

1. It has at least `min_annotations` completed annotations (excluding adjudicator users).
2. Its overall agreement score falls below `agreement_threshold` (unless `show_all_items` is true).

Agreement is computed as pairwise percentage agreement: for each annotation schema, the system counts how many annotator pairs chose the same label and divides by the total number of pairs. The overall agreement is the mean across all schemas.

The queue is sorted with pending items first (lowest agreement first), followed by in-progress items, and finally completed items. This ordering ensures adjudicators address the most contentious items first.

### Stage 3: Export

After adjudication is complete (or at any point during the process), you can generate a final dataset using the export CLI. The export merges three categories of items:

- **Unanimous items**: All annotators agreed. The shared label is used directly.
- **Adjudicated items**: An adjudicator reviewed the disagreement and submitted a decision. The adjudicator's decision is used.
- **Unresolved items**: Annotators disagreed but no adjudication decision has been submitted yet. These are excluded by default but can be included with a flag.

Each item in the exported dataset includes a `source` field indicating its provenance (`"unanimous"`, `"adjudicated"`, or `"unresolved"`).

### Data Flow Diagram

```
Annotators                    Adjudicator                   Export
    |                              |                           |
    |-- annotate items -->         |                           |
    |   (via /annotate)            |                           |
    |                              |                           |
    |   [items reach min_annotations and low agreement]        |
    |                              |                           |
    |                    view queue at /adjudicate              |
    |                    review annotations + timing            |
    |                    submit decisions                       |
    |                              |                           |
    |                              |-- decisions saved -->     |
    |                              |   (annotation_output/     |
    |                              |    adjudication/           |
    |                              |    decisions.json)         |
    |                              |                           |
    |                              |           python -m potato.adjudication_export
    |                              |                    merges unanimous + adjudicated
    |                              |                    outputs final dataset
```

---

## Setting Up

Follow these steps to add adjudication to an existing annotation project.

### Step 1: Configure Multiple Annotators Per Item

Ensure your config allows multiple annotators to label the same items:

```yaml
max_annotations_per_item: 3
```

### Step 2: Add the Adjudication Section

Add the `adjudication` block to your config file. At minimum:

```yaml
adjudication:
  enabled: true
  adjudicator_users:
    - "adjudicator"
  min_annotations: 2
  agreement_threshold: 0.75
```

### Step 3: Create Adjudicator Accounts

Adjudicator usernames listed in `adjudicator_users` are standard user accounts. They log in through the same login page as regular annotators. The system checks the username against the `adjudicator_users` list to grant access to the `/adjudicate` route.

If your project uses password authentication, adjudicators need valid credentials. If it uses standard (passwordless) login, they simply enter their username.

### Step 4: Run Annotations

Start the server and have annotators complete their work:

```bash
python potato/flask_server.py start config.yaml -p 8000
```

Annotators use the standard `/annotate` interface. Adjudicators should wait until a sufficient number of items have been annotated before beginning adjudication.

### Step 5: Begin Adjudication

Once annotations are underway, an adjudicator logs in and navigates to:

```
http://localhost:8000/adjudicate
```

The adjudication queue automatically populates with items that meet the configured criteria.

### Step 6: Export the Final Dataset

After adjudication is complete, generate the merged dataset:

```bash
python -m potato.adjudication_export --config config.yaml --output final_dataset.jsonl
```

---

## Using the Adjudication Interface

The adjudication interface is a dedicated page with three main areas: the sidebar queue, the main content area, and the bottom navigation bar.

### Sidebar Queue

The left sidebar displays the adjudication queue as a scrollable list. Each item shows:

- The instance ID.
- The number of annotators who labeled it.
- A color-coded agreement badge (red for low, amber for medium, green for high).

Items are sorted by status (pending first) and then by agreement score (lowest first). Three filter buttons at the top of the sidebar allow switching between views:

- **Pending** -- Items that have not yet been adjudicated (default view).
- **All** -- All items in the queue regardless of status.
- **Done** -- Only items that have been adjudicated.

A progress bar at the top of the sidebar shows overall completion percentage.

### Main Content Area

When you select an item from the queue, the main area displays:

1. **Item Header** -- The instance ID, agreement score badge, and annotator count.

2. **Item Text** -- The full text (or data fields) of the item being adjudicated. If the item has multiple data fields, each field is displayed with its key as a label.

3. **Annotator Responses** -- For each annotation schema, a grouped panel shows what each annotator selected. Each annotator's response appears in a card with:
   - The annotator's username (or "Annotator" if `show_annotator_names` is false).
   - Their selected label(s) or text response.
   - Time spent on the item (if `show_timing_data` is true), with a warning icon if the time was below `fast_decision_warning_ms`.
   - A per-schema agreement badge (if `show_agreement_scores` is true).

4. **Your Decision** -- For each schema, a compact decision form is rendered based on the annotation type:
   - **Radio/single-choice**: Options listed vertically with radio buttons. Colored annotator chips appear next to each option showing which annotators chose it. Click an option or an annotator chip to select it.
   - **Multiselect/checkbox**: Similar to radio but with checkboxes for multiple selection.
   - **Likert/slider**: A track showing dots for each annotator's rating, plus a slider for the adjudicator's decision. Click an annotator dot to adopt their value.
   - **Text/number**: Each annotator's text response is shown as a clickable card. Click a card to adopt its text into your response textarea, or type your own.

5. **Decision Metadata** -- Below the schema forms:
   - **Confidence** (if `require_confidence` is true): A dropdown to select high, medium, or low confidence.
   - **Error Type**: Clickable tags from the `error_taxonomy` list. Select one or more to classify the source of disagreement.
   - **Notes**: A free-text area for optional notes about the decision.
   - **Flag for Guideline Update**: A checkbox to flag items that reveal a gap or ambiguity in the annotation guidelines, with an optional text field to describe the issue.

### Bottom Navigation Bar

The navigation bar provides three actions:

- **Previous** -- Go to the previous item in the queue.
- **Skip** -- Mark the current item as skipped and move to the next.
- **Submit & Next** -- Submit the decision and advance to the next item.

---

## Keyboard Shortcuts

The following keyboard shortcuts are available when focus is not in an input field, textarea, or dropdown:

| Key | Action |
|-----|--------|
| `n` or Right Arrow | Navigate to the next item in the queue |
| `p` or Left Arrow | Navigate to the previous item in the queue |
| `Ctrl+Enter` | Submit the current decision and advance to the next item |

These shortcuts are disabled when you are typing in a textarea (such as notes or text-based annotation decisions) or interacting with a select dropdown.

---

## Export CLI

The export CLI generates a final dataset by merging unanimous agreements and adjudication decisions. It reads the project's annotation output directory, loads all user annotations and adjudication decisions, and produces a single output file.

### Basic Usage

```bash
# Export as JSONL (default format, one JSON object per line)
python -m potato.adjudication_export --config config.yaml --output final_dataset.jsonl

# Export as CSV
python -m potato.adjudication_export --config config.yaml --output final_dataset.csv --format csv

# Export as JSON (single JSON array)
python -m potato.adjudication_export --config config.yaml --output final_dataset.json --format json
```

### Including Unresolved Items

By default, items where annotators disagreed but no adjudication decision has been submitted are excluded from the output. To include them:

```bash
python -m potato.adjudication_export --config config.yaml --output final_dataset.jsonl --include-unresolved
```

### Verbose Output

For detailed logging during the export process:

```bash
python -m potato.adjudication_export --config config.yaml --output final_dataset.jsonl --verbose
```

### Command Reference

```
python -m potato.adjudication_export [OPTIONS]

Required:
  --config CONFIG       Path to the Potato config YAML file
  --output OUTPUT       Output file path

Optional:
  --format {jsonl,json,csv}
                        Output format (default: jsonl)
  --include-unresolved  Include items without adjudication or consensus
  --verbose, -v         Verbose output with debug logging
```

### Output Format

Each item in the exported dataset includes the following fields:

| Field | Description |
|-------|-------------|
| `instance_id` | The unique identifier for the item |
| `item_data` | The original item data (JSONL/JSON only) |
| `labels` | The final label decisions (keyed by schema name) |
| `source` | Provenance: `"unanimous"`, `"adjudicated"`, or `"unresolved"` |
| `adjudicator` | Username of the adjudicator (adjudicated items only) |
| `confidence` | Adjudicator's confidence level (adjudicated items only) |
| `provenance` | Per-schema source mapping (adjudicated items only) |
| `num_annotators` | Number of annotators (unanimous/unresolved items) |

### Export Summary

After export, a summary is printed to the console:

```
Export complete: final_dataset.jsonl
  Total items: 150
  Unanimous:   98
  Adjudicated: 47
  Format:      jsonl
```

If `--include-unresolved` is used, unresolved items are included in the count:

```
Export complete: final_dataset.jsonl
  Total items: 155
  Unanimous:   98
  Adjudicated: 47
  Unresolved:  10
  Format:      jsonl
```

---

## Decisions Storage

Adjudication decisions are persisted to disk automatically after each submission. They are stored in:

```
<output_annotation_dir>/<output_subdir>/decisions.json
```

With the default settings, this is:

```
annotation_output/adjudication/decisions.json
```

The file contains a JSON object with a `decisions` array and a `last_updated` timestamp. Each decision record includes:

- `instance_id` -- The item that was adjudicated.
- `adjudicator_id` -- Who made the decision.
- `timestamp` -- ISO format timestamp of the decision.
- `label_decisions` -- The final labels (keyed by schema name).
- `span_decisions` -- Any span annotation decisions.
- `source` -- Per-schema provenance (which annotator's response was adopted, or `"adjudicator"` for a novel decision).
- `confidence` -- The adjudicator's confidence rating.
- `notes` -- Free-text notes.
- `error_taxonomy` -- Selected error classification tags.
- `guideline_update_flag` -- Whether the item was flagged for guideline review.
- `guideline_update_notes` -- Description of the guideline issue (if flagged).
- `time_spent_ms` -- Time the adjudicator spent reviewing the item.

Previously saved decisions are automatically loaded when the server restarts, so adjudication progress is not lost.

---

## Example Project

A complete, self-contained example project is available at:

```
examples/advanced/adjudication/
```

This example includes a sentiment analysis task with two annotation schemas (single-choice sentiment and multi-select topics), sample data with 8 review texts, and pre-created annotation output from three simulated annotators.

### Running the Example

From the repository root:

```bash
python potato/flask_server.py start examples/advanced/adjudication/config.yaml -p 8000
```

Then:

1. Open `http://localhost:8000` in your browser.
2. Log in as `user_1`, `user_2`, or `user_3` to view or add annotations.
3. Log in as `adjudicator` to access the adjudication interface at `http://localhost:8000/adjudicate`.

The example config has `show_all_items: true` so all items with sufficient annotations appear in the queue, including those with unanimous agreement.

### Example Data

The sample data (`data/adjudication-example.json`) contains items designed to produce a mix of agreement and disagreement:

```json
[
  {
    "id": "item_001",
    "text": "The restaurant had amazing food but terrible service. I waited 45 minutes for my appetizer."
  },
  {
    "id": "item_002",
    "text": "This product exceeded my expectations in every way. Highly recommend!"
  }
]
```

Items like `item_001` with mixed sentiment ("amazing food but terrible service") are likely to produce disagreement between annotators, making them good candidates for adjudication.

---

## Supported Annotation Types

The adjudication interface renders custom decision forms for the following annotation schema types:

| Annotation Type | Adjudication Form |
|-----------------|-------------------|
| `radio` / `select` | Radio buttons with annotator chips showing who chose each option |
| `multiselect` | Checkboxes with annotator chips |
| `likert` | Visual track with annotator dots plus a slider |
| `slider` | Same as likert (visual track with slider) |
| `text` / `number` | Clickable response cards with a textarea for the final answer |

Display-only types (`pure_display`, `video`) are skipped in the adjudication interface since they do not produce annotation data.

---

## Troubleshooting

### "Not authorized as adjudicator" error

The logged-in username must exactly match one of the entries in `adjudicator_users`. Usernames are case-sensitive. Verify the username in your config:

```yaml
adjudication:
  adjudicator_users:
    - "adjudicator"    # Must match exactly
```

### Empty adjudication queue

If the queue shows no items, check:

1. That annotators have completed annotations on items. Each item needs at least `min_annotations` completed annotations.
2. That `agreement_threshold` is not set too low. A threshold of 0.0 would exclude all items unless `show_all_items` is true.
3. That annotator usernames are not listed in `adjudicator_users`. Annotations from adjudicator users are excluded from agreement calculations.

### Adjudication is not enabled error (export CLI)

The export CLI requires `adjudication.enabled: true` in the config file. If you see this error, verify your config.

### Decisions not persisting after restart

Decisions are saved to `<output_annotation_dir>/<output_subdir>/decisions.json`. Ensure the output directory exists and is writable. Check the server logs for any "Failed to save adjudication decisions" error messages.

---

## Related Documentation

- [Quality Control](quality_control.md) -- Attention checks and gold standards for annotator quality.
- [Task Assignment](task_assignment.md) -- Configuring how items are assigned to annotators.
- [Behavioral Tracking](behavioral_tracking.md) -- Understanding the timing data shown in adjudication.
- [Admin Dashboard](admin_dashboard.md) -- Monitoring overall annotation progress.
- [Data Format](data_format.md) -- Input and output data format details.
