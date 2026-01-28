# Implementation Plan: Core Quality Features

This document outlines the implementation plan for four core quality features that will significantly improve annotation quality control in Potato.

---

## Overview

| Feature | Priority | Estimated Effort | Dependencies |
|---------|----------|------------------|--------------|
| Pre-annotation Support | 4.5 | 1-2 days | None |
| Attention Checks | 4 | 2-3 days | None |
| Gold Standard Items | 4 | 2-3 days | Attention Checks (shared infrastructure) |
| Agreement Metrics Dashboard | 4 | 1-2 days | existing `agreement.py` |

**Total Estimated Effort:** 6-10 days

---

## Feature 1: Pre-annotation Support (Model Predictions)

### Purpose
Allow data files to include pre-computed predictions that pre-fill annotation forms. This dramatically speeds up annotation when:
- Correcting model outputs
- Active learning workflows
- Bootstrapping from existing annotations

### Configuration Design

```yaml
# Option 1: Global pre-annotation config
pre_annotation:
  enabled: true
  field: "predictions"           # Field in data item containing predictions
  allow_modification: true       # Can annotators change pre-filled values?
  show_confidence: true          # Show model confidence if available
  highlight_low_confidence: 0.7  # Highlight items below this threshold

# Option 2: Per-schema pre-annotation (more flexible)
annotation_schemes:
  - name: sentiment
    annotation_type: radio
    labels: [positive, negative, neutral]
    pre_annotation:
      field: "predicted_sentiment"  # Schema-specific field
      confidence_field: "sentiment_confidence"
```

### Data Format

```json
{
  "id": "item_001",
  "text": "I love this product!",
  "predictions": {
    "sentiment": "positive",
    "sentiment_confidence": 0.92
  }
}
```

For span annotations:
```json
{
  "id": "item_002",
  "text": "Apple announced new iPhone in California.",
  "predicted_entities": [
    {"start": 0, "end": 5, "label": "ORG", "confidence": 0.85},
    {"start": 27, "end": 37, "label": "LOC", "confidence": 0.91}
  ]
}
```

### Implementation Details

#### Backend Changes

**File: `potato/server_utils/config_module.py`**
- Add `validate_pre_annotation_config()` function
- Validate field exists in data items during data loading

**File: `potato/flask_server.py`**
- In `load_data()`, extract pre-annotation data and store with items
- Add pre-annotation data to item response in `/getinstancecontent`

```python
def get_instance_content(instance_id):
    item = get_item_state_manager().get_item(instance_id)
    response = {
        "id": item["id"],
        "text": item["text"],
        # Add pre-annotation data
        "pre_annotations": extract_pre_annotations(item, config)
    }
    return response
```

#### Frontend Changes

**File: `potato/static/annotation.js`**
- In `loadInstance()`, check for `pre_annotations` in response
- Call new `applyPreAnnotations(schemaName, preAnnotationData)` function

```javascript
function applyPreAnnotations(schemaName, data) {
    const schema = annotationSchemes[schemaName];

    if (schema.type === 'radio' || schema.type === 'multiselect') {
        // Pre-select checkboxes/radios
        const value = data[schemaName];
        if (value) {
            const input = document.querySelector(
                `input[name="${schemaName}"][value="${value}"]`
            );
            if (input) input.checked = true;
        }
    } else if (schema.type === 'span') {
        // Pre-create span overlays
        const spans = data[schemaName] || [];
        spans.forEach(span => {
            spanManager.createSpanFromData(span);
        });
    }
    // ... handle other schema types
}
```

**File: `potato/templates/annotate.html`**
- Add visual indicator for pre-annotated items (subtle badge/icon)
- Add confidence display if configured

#### Usability Considerations

1. **Visual Distinction**: Pre-filled values should be visually distinct (e.g., dashed border) so annotators know they're reviewing, not creating from scratch
2. **Confidence Display**: Show confidence scores as color-coded badges (green > 0.8, yellow 0.5-0.8, red < 0.5)
3. **Modification Tracking**: Track whether annotator modified pre-annotations for analysis
4. **Clear All Button**: Provide easy way to clear all pre-annotations and start fresh

### Testing Strategy

**Unit Tests** (`tests/unit/test_pre_annotation.py`):
- Config validation tests
- Data extraction tests for each annotation type
- Missing field handling

**Integration Tests** (`tests/server/test_pre_annotation.py`):
- Pre-annotation data included in `/getinstancecontent` response
- Different schema types (radio, multiselect, span, likert)
- Confidence threshold filtering

**Selenium Tests** (`tests/selenium/test_pre_annotation.py`):
- Pre-filled radio buttons appear selected
- Pre-filled span overlays appear correctly
- Modification tracking works
- "Clear pre-annotations" button works

### Documentation

- Create `docs/pre_annotation.md` with:
  - Configuration options
  - Data format examples for each annotation type
  - Best practices for model prediction format
  - Workflow examples (active learning, correction)
- Add example config: `project-hub/simple_examples/configs/pre-annotation-example.yaml`
- Add sample data: `project-hub/simple_examples/data/pre-annotation-example.json`

---

## Feature 2: Attention Checks with Failure Handling

### Purpose
Inject known-answer items periodically to verify annotators are paying attention. Track failures and optionally warn or block annotators who fail too many checks.

### Configuration Design

```yaml
attention_checks:
  enabled: true

  # Items with known correct answers
  items_file: "attention_checks.json"

  # Injection frequency
  frequency: 10                    # Insert one every N items
  # OR
  probability: 0.1                 # 10% chance per item

  # Timing (optional)
  min_response_time: 3.0           # Flag if answered in < 3 seconds

  # Failure handling
  failure_handling:
    warn_threshold: 2              # Show warning after 2 failures
    warn_message: "Please read items carefully before answering."
    block_threshold: 5             # Block after 5 failures
    block_message: "You have been blocked due to too many incorrect attention check responses."

  # Admin visibility
  show_in_dashboard: true
  highlight_failures: true
```

### Attention Check Data Format

```json
[
  {
    "id": "attn_001",
    "text": "Please select 'Positive' for this item to verify you are reading carefully.",
    "expected_answer": {
      "sentiment": "positive"
    },
    "is_attention_check": true
  },
  {
    "id": "attn_002",
    "text": "This is a test item. The correct answer is 'Negative'. Please select it now.",
    "expected_answer": {
      "sentiment": "negative"
    },
    "is_attention_check": true
  }
]
```

### Implementation Details

#### Backend Changes

**File: `potato/server_utils/config_module.py`**
- Add `validate_attention_check_config()` function
- Validate attention check items file exists and has correct format

**File: `potato/flask_server.py`**
- Load attention check items separately from main data
- Store expected answers in memory (not sent to client)

**File: `potato/item_state_management.py`**

Leverage the existing ICL (In-Context Learning) verification framework:

```python
class ItemStateManager:
    def __init__(self, ...):
        # Existing fields
        self.icl_queue = {}           # User -> queue of ICL items
        self.icl_check_probability = 0.1

        # New attention check fields
        self.attention_items = []      # Loaded attention check items
        self.attention_expected = {}   # item_id -> expected_answer
        self.attention_results = {}    # user -> {passed: [], failed: []}

    def load_attention_checks(self, items_file, config):
        """Load attention check items from file."""
        with open(items_file) as f:
            items = json.load(f)

        for item in items:
            self.attention_items.append(item)
            self.attention_expected[item["id"]] = item["expected_answer"]

    def inject_attention_check(self, user_id, regular_item):
        """Potentially inject attention check before regular item."""
        config = self.attention_config

        # Check if we should inject
        if config.get("frequency"):
            items_since_last = self._items_since_attention_check(user_id)
            if items_since_last < config["frequency"]:
                return regular_item
        elif config.get("probability"):
            if random.random() > config["probability"]:
                return regular_item

        # Select random attention check item
        check_item = random.choice(self.attention_items)

        # Queue the regular item for after
        self._queue_item_after_attention(user_id, regular_item)

        return check_item

    def validate_attention_response(self, user_id, item_id, response):
        """Check if attention check response is correct."""
        if item_id not in self.attention_expected:
            return None  # Not an attention check

        expected = self.attention_expected[item_id]
        passed = self._compare_responses(expected, response)

        # Record result
        if user_id not in self.attention_results:
            self.attention_results[user_id] = {"passed": [], "failed": []}

        result_list = "passed" if passed else "failed"
        self.attention_results[user_id][result_list].append({
            "item_id": item_id,
            "timestamp": datetime.now().isoformat(),
            "response": response,
            "expected": expected
        })

        return passed
```

**File: `potato/routes.py`**

In `/updateinstance` route (around line 2596):

```python
@app.route("/updateinstance", methods=["POST"])
def update_instance():
    data = request.json
    instance_id = data["instance_id"]
    user_id = get_current_user()

    # Check if this is an attention check
    ism = get_item_state_manager()
    attention_result = ism.validate_attention_response(
        user_id, instance_id, data["annotations"]
    )

    if attention_result is not None:
        # This was an attention check
        if not attention_result:
            # Failed - check thresholds
            failures = len(ism.attention_results[user_id]["failed"])
            config = ism.attention_config["failure_handling"]

            if failures >= config.get("block_threshold", float("inf")):
                # Block user
                get_user_state_manager().block_user(user_id, config["block_message"])
                return jsonify({
                    "status": "blocked",
                    "message": config["block_message"]
                })
            elif failures >= config.get("warn_threshold", float("inf")):
                # Warn user
                return jsonify({
                    "status": "warning",
                    "message": config["warn_message"],
                    "next_instance": get_next_instance(user_id)
                })

        # Passed or failed below threshold - continue normally
        return jsonify({
            "status": "success",
            "next_instance": get_next_instance(user_id)
        })

    # Regular annotation - existing logic
    # ...
```

**File: `potato/admin.py`**

Add attention check metrics to admin dashboard:

```python
def get_attention_check_metrics(self):
    """Get attention check statistics for dashboard."""
    ism = get_item_state_manager()
    results = ism.attention_results

    metrics = {
        "total_checks": 0,
        "total_passed": 0,
        "total_failed": 0,
        "by_user": [],
        "failure_rate": 0.0
    }

    for user_id, user_results in results.items():
        passed = len(user_results["passed"])
        failed = len(user_results["failed"])
        total = passed + failed

        metrics["total_checks"] += total
        metrics["total_passed"] += passed
        metrics["total_failed"] += failed

        metrics["by_user"].append({
            "user_id": user_id,
            "passed": passed,
            "failed": failed,
            "total": total,
            "pass_rate": passed / total if total > 0 else 0
        })

    if metrics["total_checks"] > 0:
        metrics["failure_rate"] = metrics["total_failed"] / metrics["total_checks"]

    return metrics
```

#### Frontend Changes

**File: `potato/static/annotation.js`**

Handle attention check responses:

```javascript
async function submitAnnotation() {
    const response = await fetch('/updateinstance', {
        method: 'POST',
        body: JSON.stringify(annotationData)
    });

    const result = await response.json();

    if (result.status === 'blocked') {
        showBlockedModal(result.message);
        return;
    }

    if (result.status === 'warning') {
        showWarningModal(result.message, () => {
            loadInstance(result.next_instance);
        });
        return;
    }

    // Normal flow
    loadInstance(result.next_instance);
}

function showWarningModal(message, onDismiss) {
    const modal = document.createElement('div');
    modal.className = 'attention-warning-modal';
    modal.innerHTML = `
        <div class="modal-content">
            <div class="modal-icon">⚠️</div>
            <div class="modal-message">${message}</div>
            <button class="btn btn-primary" onclick="this.closest('.attention-warning-modal').remove(); (${onDismiss})();">
                I understand
            </button>
        </div>
    `;
    document.body.appendChild(modal);
}
```

**File: `potato/templates/admin.html`**

Add attention check tab to admin dashboard:

```html
<li class="nav-item">
    <a class="nav-link" data-toggle="tab" href="#attention-checks">
        Attention Checks
    </a>
</li>

<!-- Tab content -->
<div class="tab-pane" id="attention-checks">
    <div class="row">
        <div class="col-md-4">
            <div class="card">
                <div class="card-body">
                    <h5>Overall Statistics</h5>
                    <p>Total Checks: <span id="attn-total"></span></p>
                    <p>Pass Rate: <span id="attn-pass-rate"></span></p>
                    <p>Failure Rate: <span id="attn-fail-rate"></span></p>
                </div>
            </div>
        </div>
        <div class="col-md-8">
            <div class="card">
                <div class="card-body">
                    <h5>By Annotator</h5>
                    <table class="table table-striped" id="attn-user-table">
                        <thead>
                            <tr>
                                <th>User</th>
                                <th>Passed</th>
                                <th>Failed</th>
                                <th>Pass Rate</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody></tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
</div>
```

#### Usability Considerations

1. **Non-obvious Checks**: Attention check items should look like normal items, not obviously different
2. **Fair Distribution**: Spread checks evenly, don't cluster at start or end
3. **Graduated Response**: Warn before blocking to give chance to improve
4. **Clear Feedback**: Warning messages should be helpful, not punitive
5. **Admin Override**: Allow admins to unblock users who were incorrectly blocked
6. **Response Time**: Optionally flag suspiciously fast responses

### Testing Strategy

**Unit Tests** (`tests/unit/test_attention_checks.py`):
- Config validation
- Attention check injection logic (frequency and probability modes)
- Response validation (correct/incorrect detection)
- Threshold calculations

**Integration Tests** (`tests/server/test_attention_checks.py`):
- Attention checks injected at correct frequency
- Warning triggered at threshold
- Block triggered at threshold
- Admin can view attention check metrics

**Selenium Tests** (`tests/selenium/test_attention_checks.py`):
- Warning modal appears after failures
- Block modal appears and prevents further annotation
- Attention check items appear normally (no visual distinction)

### Documentation

- Create `docs/attention_checks.md` with:
  - Configuration options
  - Attention check item format
  - Failure handling strategies
  - Best practices for writing good attention checks
- Add example config: `project-hub/simple_examples/configs/attention-checks-example.yaml`
- Add sample attention checks: `project-hub/simple_examples/data/attention-checks.json`

---

## Feature 3: Gold Standard Items with Accuracy Tracking

### Purpose
Load expert-labeled items, compare annotator responses, and compute accuracy metrics. Used for:
- Quality assurance
- Annotator training feedback
- Filtering unreliable annotators
- Calibration during annotation

### Configuration Design

```yaml
gold_standards:
  enabled: true

  # Gold standard items with expert labels
  items_file: "gold_standards.json"

  # How to use gold standards
  mode: "training"              # Options: training, mixed, separate
  # - training: Show during training phase only
  # - mixed: Mix into regular annotation (like attention checks)
  # - separate: Dedicated gold standard evaluation phase

  # For mixed mode
  frequency: 20                 # Insert one every N items

  # Accuracy requirements
  accuracy:
    min_threshold: 0.7          # Minimum required accuracy
    evaluation_count: 10        # Evaluate after this many gold items

  # Feedback
  feedback:
    show_correct_answer: true   # Show correct answer after submission
    show_explanation: true      # Show explanation if provided

  # Admin visibility
  show_in_dashboard: true
  export_accuracy_report: true
```

### Gold Standard Data Format

```json
[
  {
    "id": "gold_001",
    "text": "The service was absolutely terrible and I will never return.",
    "gold_label": {
      "sentiment": "negative"
    },
    "explanation": "Strong negative language ('absolutely terrible', 'never return') clearly indicates negative sentiment.",
    "difficulty": "easy"
  },
  {
    "id": "gold_002",
    "text": "The food was okay but nothing special.",
    "gold_label": {
      "sentiment": "neutral"
    },
    "explanation": "Mixed signals ('okay' positive, 'nothing special' mild negative) balance to neutral.",
    "difficulty": "medium"
  }
]
```

### Implementation Details

#### Backend Changes

**File: `potato/server_utils/config_module.py`**
- Add `validate_gold_standard_config()` function

**File: `potato/item_state_management.py`**

```python
class ItemStateManager:
    def __init__(self, ...):
        # Gold standard fields
        self.gold_items = []           # Loaded gold standard items
        self.gold_labels = {}          # item_id -> gold_label
        self.gold_explanations = {}    # item_id -> explanation
        self.gold_results = {}         # user -> [{item_id, correct, response, gold}]

    def load_gold_standards(self, items_file, config):
        """Load gold standard items from file."""
        with open(items_file) as f:
            items = json.load(f)

        for item in items:
            self.gold_items.append(item)
            self.gold_labels[item["id"]] = item["gold_label"]
            if "explanation" in item:
                self.gold_explanations[item["id"]] = item["explanation"]

    def validate_gold_response(self, user_id, item_id, response):
        """Check if response matches gold standard."""
        if item_id not in self.gold_labels:
            return None  # Not a gold standard item

        gold = self.gold_labels[item_id]
        correct = self._compare_responses(gold, response)

        # Record result
        if user_id not in self.gold_results:
            self.gold_results[user_id] = []

        self.gold_results[user_id].append({
            "item_id": item_id,
            "correct": correct,
            "response": response,
            "gold_label": gold,
            "timestamp": datetime.now().isoformat()
        })

        return {
            "correct": correct,
            "gold_label": gold,
            "explanation": self.gold_explanations.get(item_id)
        }

    def get_user_gold_accuracy(self, user_id):
        """Calculate user's accuracy on gold standards."""
        if user_id not in self.gold_results:
            return None

        results = self.gold_results[user_id]
        if not results:
            return None

        correct = sum(1 for r in results if r["correct"])
        total = len(results)

        return {
            "correct": correct,
            "total": total,
            "accuracy": correct / total,
            "results": results
        }
```

**File: `potato/routes.py`**

In `/updateinstance` route, add gold standard validation:

```python
# After attention check validation
gold_result = ism.validate_gold_response(user_id, instance_id, data["annotations"])

if gold_result is not None:
    config = ism.gold_config

    response_data = {
        "status": "gold_standard",
        "correct": gold_result["correct"],
    }

    # Include feedback if configured
    if config.get("feedback", {}).get("show_correct_answer"):
        response_data["gold_label"] = gold_result["gold_label"]
    if config.get("feedback", {}).get("show_explanation") and gold_result["explanation"]:
        response_data["explanation"] = gold_result["explanation"]

    # Check accuracy threshold
    accuracy_data = ism.get_user_gold_accuracy(user_id)
    eval_count = config.get("accuracy", {}).get("evaluation_count", 10)

    if accuracy_data["total"] >= eval_count:
        min_threshold = config.get("accuracy", {}).get("min_threshold", 0.7)
        if accuracy_data["accuracy"] < min_threshold:
            response_data["accuracy_warning"] = True
            response_data["current_accuracy"] = accuracy_data["accuracy"]
            response_data["required_accuracy"] = min_threshold

    response_data["next_instance"] = get_next_instance(user_id)
    return jsonify(response_data)
```

**File: `potato/admin.py`**

Add gold standard accuracy to dashboard:

```python
def get_gold_standard_metrics(self):
    """Get gold standard accuracy for all users."""
    ism = get_item_state_manager()

    metrics = {
        "total_evaluations": 0,
        "overall_accuracy": 0.0,
        "by_user": [],
        "by_item": [],
        "below_threshold": []
    }

    all_correct = 0
    all_total = 0

    for user_id in ism.gold_results:
        accuracy = ism.get_user_gold_accuracy(user_id)
        if accuracy:
            metrics["by_user"].append({
                "user_id": user_id,
                "accuracy": accuracy["accuracy"],
                "correct": accuracy["correct"],
                "total": accuracy["total"]
            })
            all_correct += accuracy["correct"]
            all_total += accuracy["total"]

            # Track users below threshold
            threshold = ism.gold_config.get("accuracy", {}).get("min_threshold", 0.7)
            if accuracy["accuracy"] < threshold:
                metrics["below_threshold"].append(user_id)

    metrics["total_evaluations"] = all_total
    if all_total > 0:
        metrics["overall_accuracy"] = all_correct / all_total

    # Per-item accuracy
    item_results = {}
    for user_id, results in ism.gold_results.items():
        for result in results:
            item_id = result["item_id"]
            if item_id not in item_results:
                item_results[item_id] = {"correct": 0, "total": 0}
            item_results[item_id]["total"] += 1
            if result["correct"]:
                item_results[item_id]["correct"] += 1

    for item_id, counts in item_results.items():
        metrics["by_item"].append({
            "item_id": item_id,
            "accuracy": counts["correct"] / counts["total"],
            "total": counts["total"]
        })

    return metrics
```

#### Frontend Changes

**File: `potato/static/annotation.js`**

Handle gold standard feedback:

```javascript
async function submitAnnotation() {
    const result = await submitToServer();

    if (result.status === 'gold_standard') {
        showGoldFeedbackModal(result, () => {
            loadInstance(result.next_instance);
        });
        return;
    }
    // ... rest of handling
}

function showGoldFeedbackModal(result, onContinue) {
    const correct = result.correct;
    const modal = document.createElement('div');
    modal.className = 'gold-feedback-modal';

    let feedbackHTML = `
        <div class="modal-content ${correct ? 'correct' : 'incorrect'}">
            <div class="modal-icon">${correct ? '✓' : '✗'}</div>
            <div class="modal-title">${correct ? 'Correct!' : 'Incorrect'}</div>
    `;

    if (result.gold_label) {
        feedbackHTML += `
            <div class="correct-answer">
                <strong>Correct answer:</strong> ${formatGoldLabel(result.gold_label)}
            </div>
        `;
    }

    if (result.explanation) {
        feedbackHTML += `
            <div class="explanation">
                <strong>Explanation:</strong> ${result.explanation}
            </div>
        `;
    }

    if (result.accuracy_warning) {
        feedbackHTML += `
            <div class="accuracy-warning">
                ⚠️ Your current accuracy is ${(result.current_accuracy * 100).toFixed(1)}%.
                The minimum required is ${(result.required_accuracy * 100).toFixed(1)}%.
                Please review the guidelines carefully.
            </div>
        `;
    }

    feedbackHTML += `
            <button class="btn btn-primary" onclick="this.closest('.gold-feedback-modal').remove(); (${onContinue})();">
                Continue
            </button>
        </div>
    `;

    modal.innerHTML = feedbackHTML;
    document.body.appendChild(modal);
}
```

#### Usability Considerations

1. **Constructive Feedback**: Show explanations to help annotators learn, not just "wrong"
2. **Progress Tracking**: Show annotators their accuracy over time
3. **Difficulty Calibration**: Use easy gold standards early, harder ones later
4. **No Punishment Feel**: Frame as "calibration" not "testing"
5. **Clear Distinction from Attention Checks**: Gold standards provide learning, attention checks verify engagement

### Testing Strategy

**Unit Tests** (`tests/unit/test_gold_standards.py`):
- Config validation
- Gold label comparison for different annotation types
- Accuracy calculation
- Per-item accuracy aggregation

**Integration Tests** (`tests/server/test_gold_standards.py`):
- Gold standards mixed into annotation flow
- Feedback returned correctly
- Accuracy threshold warnings
- Admin metrics calculation

**Selenium Tests** (`tests/selenium/test_gold_standards.py`):
- Feedback modal appears with correct/incorrect indicator
- Explanation displayed when available
- Accuracy warning appears when below threshold

### Documentation

- Create `docs/gold_standards.md` with:
  - Configuration options
  - Gold standard item format
  - Modes (training, mixed, separate)
  - Best practices for creating gold standards
- Add example config: `project-hub/simple_examples/configs/gold-standards-example.yaml`
- Add sample gold standards: `project-hub/simple_examples/data/gold-standards.json`

---

## Feature 4: Agreement Metrics in Admin Dashboard

### Purpose
Display real-time inter-annotator agreement metrics in the admin dashboard. This leverages the existing `agreement.py` module which already implements Krippendorff's alpha via the `simpledorff` library.

### Configuration Design

```yaml
agreement_metrics:
  enabled: true

  # Which metrics to calculate
  metrics:
    - krippendorff_alpha     # Already implemented in agreement.py
    - percent_agreement      # Simple percentage

  # Calculation settings
  min_overlap: 2              # Minimum annotators per item for calculation

  # Display settings
  show_per_schema: true       # Show agreement for each annotation scheme
  show_per_label: true        # Show agreement broken down by label

  # Auto-refresh
  auto_refresh: true
  refresh_interval: 60        # Seconds
```

### Implementation Details

#### Backend Changes

**File: `potato/admin.py`**

```python
from potato.agreement import calculate_alpha_scores

class AdminDashboard:
    def get_agreement_metrics(self):
        """Calculate inter-annotator agreement metrics."""
        config = get_config()
        agreement_config = config.get("agreement_metrics", {})

        if not agreement_config.get("enabled", False):
            return {"enabled": False}

        # Get annotation data
        ism = get_item_state_manager()
        usm = get_user_state_manager()

        # Build annotation matrix for each schema
        metrics = {
            "enabled": True,
            "overall": {},
            "by_schema": {},
            "by_item": [],
            "warnings": []
        }

        for scheme in config.get("annotation_schemes", []):
            schema_name = scheme["name"]

            # Collect annotations per item
            annotations_by_item = self._collect_annotations_for_schema(schema_name)

            # Check minimum overlap
            min_overlap = agreement_config.get("min_overlap", 2)
            valid_items = {
                item_id: annots
                for item_id, annots in annotations_by_item.items()
                if len(annots) >= min_overlap
            }

            if not valid_items:
                metrics["by_schema"][schema_name] = {
                    "error": f"No items with {min_overlap}+ annotators"
                }
                continue

            # Calculate Krippendorff's alpha using existing agreement.py
            try:
                # Format data for simpledorff
                reliability_data = self._format_for_simpledorff(valid_items)
                alpha = calculate_alpha_scores(reliability_data)

                metrics["by_schema"][schema_name] = {
                    "krippendorff_alpha": alpha,
                    "items_evaluated": len(valid_items),
                    "interpretation": self._interpret_alpha(alpha)
                }
            except Exception as e:
                metrics["by_schema"][schema_name] = {
                    "error": str(e)
                }

        # Calculate overall metrics
        if metrics["by_schema"]:
            alphas = [
                m["krippendorff_alpha"]
                for m in metrics["by_schema"].values()
                if "krippendorff_alpha" in m
            ]
            if alphas:
                metrics["overall"]["krippendorff_alpha"] = sum(alphas) / len(alphas)
                metrics["overall"]["interpretation"] = self._interpret_alpha(
                    metrics["overall"]["krippendorff_alpha"]
                )

        return metrics

    def _interpret_alpha(self, alpha):
        """Human-readable interpretation of Krippendorff's alpha."""
        if alpha >= 0.8:
            return "Good agreement"
        elif alpha >= 0.67:
            return "Tentative agreement"
        elif alpha >= 0.33:
            return "Low agreement"
        else:
            return "Poor agreement"

    def _collect_annotations_for_schema(self, schema_name):
        """Collect all annotations for a schema, grouped by item."""
        usm = get_user_state_manager()
        annotations_by_item = {}

        for user_id in usm.get_all_users():
            user_annotations = usm.get_user_annotations(user_id)

            for item_id, annotation_data in user_annotations.items():
                if schema_name in annotation_data:
                    if item_id not in annotations_by_item:
                        annotations_by_item[item_id] = []
                    annotations_by_item[item_id].append({
                        "user_id": user_id,
                        "value": annotation_data[schema_name]
                    })

        return annotations_by_item

    def _format_for_simpledorff(self, annotations_by_item):
        """Format annotations for simpledorff library."""
        data = []
        for item_id, annotations in annotations_by_item.items():
            for annot in annotations:
                data.append({
                    "unit": item_id,
                    "annotator": annot["user_id"],
                    "annotation": self._normalize_annotation(annot["value"])
                })
        return data

    def _normalize_annotation(self, value):
        """Normalize annotation value for comparison."""
        if isinstance(value, list):
            return tuple(sorted(value))
        return value
```

**File: `potato/routes.py`**

Add API endpoint for agreement metrics:

```python
@app.route("/admin/api/agreement", methods=["GET"])
@login_required
@admin_required
def get_agreement_metrics():
    """Get inter-annotator agreement metrics."""
    dashboard = AdminDashboard()
    return jsonify(dashboard.get_agreement_metrics())
```

#### Frontend Changes

**File: `potato/templates/admin.html`**

Add Agreement tab:

```html
<li class="nav-item">
    <a class="nav-link" data-toggle="tab" href="#agreement">
        Agreement
    </a>
</li>

<div class="tab-pane" id="agreement">
    <div class="row mb-3">
        <div class="col-12">
            <button class="btn btn-outline-secondary" onclick="refreshAgreement()">
                ↻ Refresh
            </button>
            <span id="agreement-last-updated" class="text-muted ml-2"></span>
        </div>
    </div>

    <div class="row">
        <div class="col-md-4">
            <div class="card">
                <div class="card-header">Overall Agreement</div>
                <div class="card-body">
                    <div class="agreement-score" id="overall-alpha">
                        <span class="score">--</span>
                        <span class="interpretation">Loading...</span>
                    </div>
                </div>
            </div>
        </div>

        <div class="col-md-8">
            <div class="card">
                <div class="card-header">By Annotation Scheme</div>
                <div class="card-body">
                    <table class="table" id="schema-agreement-table">
                        <thead>
                            <tr>
                                <th>Schema</th>
                                <th>Krippendorff's α</th>
                                <th>Items</th>
                                <th>Interpretation</th>
                            </tr>
                        </thead>
                        <tbody></tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <div class="row mt-3">
        <div class="col-12">
            <div class="card">
                <div class="card-header">Agreement Interpretation Guide</div>
                <div class="card-body">
                    <ul class="interpretation-guide">
                        <li><span class="badge badge-success">α ≥ 0.8</span> Good agreement - reliable for most purposes</li>
                        <li><span class="badge badge-warning">0.67 ≤ α < 0.8</span> Tentative agreement - draw tentative conclusions</li>
                        <li><span class="badge badge-danger">α < 0.67</span> Low agreement - review guidelines and training</li>
                    </ul>
                </div>
            </div>
        </div>
    </div>
</div>
```

**File: `potato/static/admin.js`**

```javascript
async function loadAgreementMetrics() {
    const response = await fetch('/admin/api/agreement');
    const data = await response.json();

    if (!data.enabled) {
        document.getElementById('agreement').innerHTML =
            '<p class="text-muted">Agreement metrics not enabled in configuration.</p>';
        return;
    }

    // Update overall
    if (data.overall.krippendorff_alpha !== undefined) {
        document.getElementById('overall-alpha').innerHTML = `
            <span class="score">${data.overall.krippendorff_alpha.toFixed(3)}</span>
            <span class="interpretation badge ${getAlphaBadgeClass(data.overall.krippendorff_alpha)}">
                ${data.overall.interpretation}
            </span>
        `;
    }

    // Update per-schema table
    const tbody = document.querySelector('#schema-agreement-table tbody');
    tbody.innerHTML = '';

    for (const [schema, metrics] of Object.entries(data.by_schema)) {
        const row = document.createElement('tr');

        if (metrics.error) {
            row.innerHTML = `
                <td>${schema}</td>
                <td colspan="3" class="text-danger">${metrics.error}</td>
            `;
        } else {
            row.innerHTML = `
                <td>${schema}</td>
                <td>${metrics.krippendorff_alpha.toFixed(3)}</td>
                <td>${metrics.items_evaluated}</td>
                <td><span class="badge ${getAlphaBadgeClass(metrics.krippendorff_alpha)}">
                    ${metrics.interpretation}
                </span></td>
            `;
        }
        tbody.appendChild(row);
    }

    // Update timestamp
    document.getElementById('agreement-last-updated').textContent =
        `Last updated: ${new Date().toLocaleTimeString()}`;
}

function getAlphaBadgeClass(alpha) {
    if (alpha >= 0.8) return 'badge-success';
    if (alpha >= 0.67) return 'badge-warning';
    return 'badge-danger';
}

function refreshAgreement() {
    loadAgreementMetrics();
}

// Auto-refresh if configured
document.addEventListener('DOMContentLoaded', () => {
    loadAgreementMetrics();

    // Set up auto-refresh (default 60 seconds)
    setInterval(loadAgreementMetrics, 60000);
});
```

#### Usability Considerations

1. **Clear Interpretation**: Always show what the numbers mean, not just the numbers
2. **Visual Indicators**: Color-code agreement levels (green/yellow/red)
3. **Actionable Insights**: Suggest next steps when agreement is low
4. **Historical Tracking**: Show agreement over time (optional enhancement)
5. **Export Option**: Allow exporting agreement data for reports

### Testing Strategy

**Unit Tests** (`tests/unit/test_agreement_metrics.py`):
- Alpha calculation with known values
- Edge cases (single annotator, no overlap, all same value)
- Interpretation thresholds

**Integration Tests** (`tests/server/test_agreement_metrics.py`):
- API endpoint returns correct structure
- Calculation with real annotation data
- Permission checking (admin only)

**Selenium Tests** (`tests/selenium/test_agreement_dashboard.py`):
- Agreement tab displays correctly
- Refresh button works
- Color coding matches values

### Documentation

- Create `docs/agreement_metrics.md` with:
  - Configuration options
  - Interpretation guide for Krippendorff's alpha
  - When to use different metrics
  - How to improve low agreement
- Update admin dashboard documentation

---

## Implementation Order

### Phase 1: Shared Infrastructure (Day 1)

1. Create base validation/comparison utilities for responses
2. Create modal system for feedback (used by attention checks and gold standards)
3. Add new admin dashboard API endpoint pattern

### Phase 2: Attention Checks (Days 2-3)

1. Config validation
2. Item loading and storage
3. Injection logic (leverage existing ICL framework)
4. Response validation
5. Failure handling (warn/block)
6. Admin dashboard integration
7. Tests and documentation

### Phase 3: Gold Standards (Days 4-5)

1. Config validation (shares pattern with attention checks)
2. Item loading and storage
3. Response validation with feedback
4. Accuracy tracking
5. Admin dashboard integration
6. Tests and documentation

### Phase 4: Agreement Metrics (Days 6-7)

1. Config validation
2. Annotation collection and formatting
3. Integration with existing agreement.py
4. Admin dashboard tab
5. Auto-refresh functionality
6. Tests and documentation

### Phase 5: Pre-annotation Support (Days 8-9)

1. Config validation
2. Data loading and extraction
3. API response modification
4. Frontend pre-fill logic for each schema type
5. Visual indicators
6. Tests and documentation

### Phase 6: Integration Testing & Polish (Day 10)

1. End-to-end tests with all features enabled
2. Performance testing with large datasets
3. Documentation review
4. Example project creation

---

## File Summary

### New Files to Create

| File | Purpose |
|------|---------|
| `tests/unit/test_pre_annotation.py` | Pre-annotation unit tests |
| `tests/unit/test_attention_checks.py` | Attention check unit tests |
| `tests/unit/test_gold_standards.py` | Gold standard unit tests |
| `tests/unit/test_agreement_metrics.py` | Agreement metrics unit tests |
| `tests/server/test_pre_annotation.py` | Pre-annotation integration tests |
| `tests/server/test_attention_checks.py` | Attention check integration tests |
| `tests/server/test_gold_standards.py` | Gold standard integration tests |
| `tests/server/test_agreement_metrics.py` | Agreement metrics integration tests |
| `tests/selenium/test_pre_annotation.py` | Pre-annotation UI tests |
| `tests/selenium/test_attention_checks.py` | Attention check UI tests |
| `tests/selenium/test_gold_standards.py` | Gold standard UI tests |
| `tests/selenium/test_agreement_dashboard.py` | Agreement dashboard UI tests |
| `docs/pre_annotation.md` | Pre-annotation documentation |
| `docs/attention_checks.md` | Attention check documentation |
| `docs/gold_standards.md` | Gold standard documentation |
| `docs/agreement_metrics.md` | Agreement metrics documentation |
| `project-hub/simple_examples/configs/pre-annotation-example.yaml` | Example config |
| `project-hub/simple_examples/configs/attention-checks-example.yaml` | Example config |
| `project-hub/simple_examples/configs/gold-standards-example.yaml` | Example config |
| `project-hub/simple_examples/data/pre-annotation-example.json` | Example data |
| `project-hub/simple_examples/data/attention-checks.json` | Example data |
| `project-hub/simple_examples/data/gold-standards.json` | Example data |

### Files to Modify

| File | Changes |
|------|---------|
| `potato/server_utils/config_module.py` | Add validation functions for new configs |
| `potato/flask_server.py` | Load special items, modify data responses |
| `potato/item_state_management.py` | Add attention/gold tracking, injection logic |
| `potato/routes.py` | Add validation hooks in `/updateinstance`, new API endpoints |
| `potato/admin.py` | Add metrics methods for dashboard |
| `potato/static/annotation.js` | Pre-fill logic, feedback modal handling |
| `potato/static/admin.js` | New dashboard tabs and data loading |
| `potato/templates/admin.html` | New dashboard tabs UI |
| `potato/templates/annotate.html` | Pre-annotation indicators, feedback modals |
| `potato/static/styles.css` | Styles for new UI elements |

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Performance with large datasets | Use lazy loading, pagination in dashboard |
| Complex interaction between features | Clear separation of concerns, feature flags |
| Breaking existing annotation flow | Extensive integration tests, gradual rollout |
| User confusion with multiple feedback types | Clear visual distinction between feature types |
| Admin dashboard clutter | Tabbed interface, optional feature display |

---

## Success Criteria

1. **Pre-annotation**: Forms pre-fill correctly for all annotation types
2. **Attention Checks**: Checks inject at configured frequency, failures tracked
3. **Gold Standards**: Accuracy calculated correctly, feedback displayed
4. **Agreement Metrics**: Alpha matches manual calculation, dashboard updates
5. **All features**: Can be enabled/disabled independently
6. **Documentation**: Complete guides with working examples
7. **Tests**: >90% coverage for new code
