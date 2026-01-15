# Category-Based Assignment

Category-based assignment allows you to automatically match annotators with annotation instances based on their demonstrated expertise. Annotators are assessed during training or prestudy phases on category-specific questions, and only receive instances from categories they have qualified for.

## Overview

The category-based assignment system works as follows:

1. **Data Tagging**: Instances in your data files are tagged with one or more categories
2. **Training Assessment**: Training questions are also tagged with categories
3. **Performance Tracking**: The system tracks each user's accuracy per category during training
4. **Qualification**: Users who meet the threshold accuracy for a category are "qualified"
5. **Assignment**: During annotation, users only receive instances from their qualified categories

## Configuration

### Basic Setup

Add the following to your YAML configuration:

```yaml
# Enable category-based assignment strategy
assignment_strategy: category_based

# Configure category key in item_properties
item_properties:
  id_key: id
  text_key: text
  category_key: category  # Field in data containing category

# Category assignment settings
category_assignment:
  enabled: true
  qualification:
    source: training      # Where qualification comes from
    threshold: 0.7        # 70% accuracy required
    min_questions: 2      # At least 2 questions per category
  fallback: uncategorized # What to do if user qualifies for nothing
```

### Configuration Options

#### `assignment_strategy`

Set to `category_based` to enable category-based assignment.

#### `item_properties.category_key`

The field name in your data files that contains the category. Categories can be:
- A single string: `"category": "economics"`
- A list of strings: `"category": ["economics", "finance"]`

#### `category_assignment`

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | boolean | true | Enable/disable category assignment |
| `qualification.source` | string | "training" | Where qualification scores come from: "training", "prestudy", or "both" |
| `qualification.threshold` | float | 0.7 | Minimum accuracy (0.0-1.0) to qualify for a category |
| `qualification.min_questions` | integer | 1 | Minimum questions answered per category to qualify |
| `qualification.combine_method` | string | "average" | How to combine scores when source is "both": "average", "max", or "sum" |
| `fallback` | string | "uncategorized" | Behavior when user doesn't qualify for any category |

#### Fallback Options

- `uncategorized`: Assign instances that have no category
- `random`: Assign randomly from all remaining instances
- `none`: Don't assign any instances (user will see no new work)

## Data Format

### Instance Data

Your data files should include the category field:

```json
{"id": "econ_001", "text": "Market analysis text...", "category": "economics"}
{"id": "sci_001", "text": "Research findings...", "category": "science"}
{"id": "multi_001", "text": "Interdisciplinary topic...", "category": ["economics", "science"]}
{"id": "general_001", "text": "General content...", "category": null}
```

Instances with `null` category or missing category field are considered "uncategorized" and will be assigned via fallback behavior.

### Training Data

Training instances should include categories to enable per-category assessment:

```json
{
  "training_instances": [
    {
      "id": "train_econ_1",
      "text": "Question about economic concepts...",
      "category": "economics",
      "correct_answers": {"topic": "Economics"},
      "explanation": "This is an economics topic because..."
    },
    {
      "id": "train_sci_1",
      "text": "Question about scientific method...",
      "category": ["science", "research"],
      "correct_answers": {"topic": "Science"},
      "explanation": "This relates to scientific research..."
    }
  ]
}
```

## How Qualification Works

### During Training

As users answer training questions:

1. The system records the category(ies) of each training question
2. For each category, it tracks:
   - Total questions answered in that category
   - Number of correct answers in that category
   - Accuracy (correct / total)

### After Training Completes

When a user passes training:

1. The system calculates accuracy for each category
2. Categories where the user meets both:
   - The minimum accuracy threshold
   - The minimum questions requirement

   ...are added to the user's "qualified categories"

3. These qualifications persist for the session and are saved with user state

### Example

If threshold is 0.7 (70%) and min_questions is 2:

| Category | Questions | Correct | Accuracy | Qualified? |
|----------|-----------|---------|----------|------------|
| Economics | 3 | 3 | 100% | Yes |
| Science | 2 | 1 | 50% | No (below threshold) |
| Sports | 1 | 1 | 100% | No (below min_questions) |

User would only receive "Economics" instances.

## Use Cases

### Expert Routing

Route specialized content to qualified annotators:

- Medical texts to annotators who demonstrate medical knowledge
- Legal documents to those who understand legal terminology
- Technical content to those with technical expertise

### Quality Control

Ensure quality by only assigning content to qualified individuals:

- Annotators prove competence before receiving real work
- Different quality thresholds for different content types
- Fallback to simpler content for less qualified annotators

### Workload Distribution

Distribute work based on expertise:

- High-complexity items to expert annotators
- General items to all annotators
- Specialized items to specialists

## Complete Example

See `project-hub/simple_examples/configs/category-assignment-example.yaml` for a complete working example including:

- Configuration file with category assignment enabled
- Training data with category-tagged questions
- Instance data with various categories
- Uncategorized items for fallback

To run the example:

```bash
python potato/flask_server.py start project-hub/simple_examples/configs/category-assignment-example.yaml -p 8000
```

## Troubleshooting

### Users Not Getting Assigned Instances

Check:
1. Does the user have qualified categories? (Check training performance)
2. Are there instances in those categories that haven't been annotated?
3. Is `fallback` set appropriately for users with no qualifications?

### Categories Not Being Tracked

Verify:
1. `category_key` is set in `item_properties`
2. Training instances have the `category` field
3. `category_assignment.enabled` is `true`

### All Users Getting Random Instances

Ensure:
1. `assignment_strategy` is set to `category_based`
2. Users are completing training (not skipping it)
3. Training questions have categories assigned

## API Reference

### TrainingState Methods

```python
# Record an answer for category tracking
training_state.record_category_answer(categories=['economics'], is_correct=True)

# Get score for a specific category
score = training_state.get_category_score('economics')
# Returns: {'correct': 3, 'total': 4, 'accuracy': 0.75}

# Get all category scores
all_scores = training_state.get_all_category_scores()

# Get qualified categories based on threshold
qualified = training_state.get_qualified_categories(threshold=0.7, min_questions=2)
# Returns: ['economics', 'science']
```

### UserState Methods

```python
# Add a qualified category
user_state.add_qualified_category('economics', score=0.85)

# Check if user is qualified for a category
is_qualified = user_state.is_qualified_for_category('economics')

# Get all qualified categories
categories = user_state.get_qualified_categories()

# Calculate qualifications from training state
newly_qualified = user_state.calculate_and_set_qualifications(
    threshold=0.7,
    min_questions=2
)
```

### ItemStateManager Methods

```python
# Get all instances in a category
instances = ism.get_instances_by_category('economics')

# Get instances in multiple categories
instances = ism.get_instances_by_categories({'economics', 'finance'})

# Get uncategorized instances
uncategorized = ism.get_uncategorized_instances()

# Get all unique categories
categories = ism.get_all_categories()

# Get instance counts per category
counts = ism.get_category_counts()
# Returns: {'economics': 10, 'science': 8, 'sports': 5}
```

## Dynamic Expertise Mode

Dynamic expertise mode enables on-the-fly expertise assessment during annotation, without requiring gold-labeled training data. Instead of qualification through training, expertise is determined by agreement with other annotators.

### Overview

In dynamic mode:

1. **All annotators can receive any category** (probabilistic routing, not hard filtering)
2. **Expertise scores are updated based on agreement** with consensus from other annotators
3. **A background worker** periodically calculates consensus and updates expertise scores
4. **Probabilistic routing** makes annotators more likely to receive categories they're experts in

This is useful when:
- Gold-labeled data is not available for training
- You want expertise to emerge naturally from annotation behavior
- You want to gradually improve annotator-category matching during the annotation process

### Configuration

```yaml
assignment_strategy: category_based

item_properties:
  id_key: id
  text_key: text
  category_key: category

category_assignment:
  enabled: true
  dynamic:
    enabled: true
    agreement_method: majority_vote  # How to determine consensus
    min_annotations_for_consensus: 2  # Min annotations before calculating consensus
    learning_rate: 0.1               # How quickly expertise scores change (0-1)
    update_interval_seconds: 60       # How often to recalculate expertise
    base_probability: 0.1             # Minimum probability for any category
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | boolean | false | Enable dynamic expertise mode |
| `agreement_method` | string | "majority_vote" | How to calculate consensus |
| `min_annotations_for_consensus` | integer | 2 | Minimum annotations needed before calculating consensus |
| `learning_rate` | float | 0.1 | How quickly expertise scores update (0.0-1.0) |
| `update_interval_seconds` | integer | 60 | Seconds between expertise recalculation |
| `base_probability` | float | 0.1 | Minimum probability of receiving any category |

### Agreement Methods

- **`majority_vote`**: Consensus is reached when >50% agree
- **`super_majority`**: Consensus requires ≥66% agreement
- **`unanimous`**: All annotators must agree

### How It Works

1. **Initial State**: All annotators start with neutral expertise (0.5) for all categories

2. **Probabilistic Assignment**:
   - All categories have at least `base_probability` chance of being assigned
   - Categories where the user has higher expertise have proportionally higher probability
   - For example, with expertise {economics: 0.8, science: 0.2}:
     - Higher chance of receiving economics instances
     - Still possible to receive science instances

3. **Background Processing**:
   - Every `update_interval_seconds`, the system:
     - Finds instances with enough annotations (≥ `min_annotations_for_consensus`)
     - Calculates consensus for each instance
     - Updates expertise scores for each annotator based on agreement

4. **Expertise Updates**:
   - When an annotator agrees with consensus, their expertise increases
   - When they disagree, their expertise decreases
   - The `learning_rate` controls how quickly scores change
   - Scores are bounded between 0.0 and 1.0

### Example Scenario

Consider an annotation task with 3 categories: Economics, Science, Sports.

**Initial assignment** (new user with 0.5 expertise in all):
- Equal probability (~33% each) of receiving any category

**After some annotations**:
- User agrees with consensus on 5/5 Economics instances
- User disagrees on 2/3 Science instances
- No Sports instances annotated yet

**Updated probabilities**:
- Economics: ~50% (high expertise)
- Science: ~20% (low expertise)
- Sports: ~30% (neutral expertise)

The user will now receive more Economics instances, fewer Science instances, while still having a chance to improve in Science.

### ExpertiseManager API

```python
from potato.expertise_manager import get_expertise_manager

em = get_expertise_manager()

# Get expertise profile for a user
profile = em.get_user_profile('username')

# Get expertise score for a category
score = profile.get_expertise_score('economics')  # Returns 0.0-1.0

# Get all expertise scores
all_scores = profile.get_all_expertise_scores()
# Returns: {'economics': 0.8, 'science': 0.3, 'sports': 0.5}

# Get category probabilities for assignment
probs = em.get_category_probabilities('username', {'economics', 'science'})
# Returns: {'economics': 0.73, 'science': 0.27}

# Select a category probabilistically
category = em.select_category_probabilistically('username', {'economics', 'science'})
# Returns: 'economics' (most likely) or 'science' (less likely)
```

### Combining with Training-Based Qualification

You can use both training-based qualification AND dynamic expertise:

1. Training qualification gates initial access to categories
2. Dynamic expertise refines routing within qualified categories

```yaml
category_assignment:
  enabled: true
  qualification:
    source: training
    threshold: 0.7
    min_questions: 2
  dynamic:
    enabled: true
    learning_rate: 0.1
```

In this setup:
- Users must pass training to access categories
- Within qualified categories, dynamic expertise optimizes routing

### Best Practices

1. **Set appropriate `min_annotations_for_consensus`**:
   - Too low (2) may not represent true consensus
   - Too high may delay expertise updates

2. **Tune `learning_rate`**:
   - Higher rates (0.2-0.3) respond quickly but may be noisy
   - Lower rates (0.05-0.1) are more stable but slower to adapt

3. **Use `base_probability`**:
   - Prevents complete exclusion from any category
   - Allows recovery from early poor performance
   - Recommended: 0.05-0.15

4. **Monitor expertise scores**:
   - Check for annotators with very low scores in most categories
   - Consider intervention if patterns suggest quality issues
