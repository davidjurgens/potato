# Assignment Strategy Tests

This document describes the comprehensive test suite for different item assignment strategies in the Potato annotation platform.

## Overview

The assignment strategy tests verify that different item assignment algorithms work correctly, ensuring proper distribution of annotation tasks across users and items. The tests cover all implemented strategies and various edge cases.

## Implemented Assignment Strategies

### 1. Random Assignment (`random`)
- **Purpose**: Assigns items randomly to annotators
- **Use Case**: When you want unbiased, random sampling of items
- **Behavior**: Each annotator gets a random item from the available pool
- **Test Coverage**: Distribution verification, completion scenarios

### 2. Fixed Order Assignment (`fixed_order`)
- **Purpose**: Assigns items in a predetermined sequence
- **Use Case**: When you need consistent, predictable item ordering
- **Behavior**: Items are assigned in the order they appear in the dataset
- **Test Coverage**: Order verification, completion scenarios

### 3. Least-Annotated Assignment (`least_annotated`)
- **Purpose**: Prioritizes items with the fewest annotations
- **Use Case**: When you want to ensure even distribution of annotations
- **Behavior**: Items with fewer annotations are assigned first
- **Test Coverage**: Distribution balance, completion scenarios

### 4. Max-Diversity Assignment (`max_diversity`)
- **Purpose**: Prioritizes items with highest disagreement/diversity in existing annotations
- **Use Case**: When you want to focus on items that need more annotation due to disagreement
- **Behavior**: Items with conflicting or diverse annotations are assigned first
- **Test Coverage**: Disagreement calculation, completion scenarios

### 5. Active Learning Assignment (`active_learning`)
- **Purpose**: Uses machine learning to prioritize uncertain items
- **Use Case**: When you want to maximize annotation efficiency
- **Behavior**: Currently falls back to random assignment (placeholder implementation)
- **Test Coverage**: Basic functionality, fallback behavior

### 6. LLM Confidence Assignment (`llm_confidence`)
- **Purpose**: Uses LLM confidence scores to prioritize items
- **Use Case**: When you have LLM predictions and want to focus on low-confidence items
- **Behavior**: Currently falls back to random assignment (placeholder implementation)
- **Test Coverage**: Basic functionality, fallback behavior

## Test Scenarios

### Basic Strategy Tests

Each strategy is tested with the following scenarios:

1. **Small Dataset Test**
   - 4-6 items with max 2-3 annotations per item
   - 6-12 annotators (more than needed)
   - Verifies proper distribution and completion

2. **Fixed Order Verification**
   - Tests that items are assigned in the correct sequence
   - Verifies that the first round follows the expected order

3. **Distribution Balance**
   - Tests that least-annotated strategy balances workload
   - Verifies that max-diversity strategy prioritizes disagreement

4. **Completion Scenarios**
   - Tests behavior when all items have reached max annotations
   - Verifies that new users get no assignments when work is complete

### Edge Cases

1. **Empty Dataset**
   - Tests behavior with no items
   - Verifies proper error handling

2. **Single Item Dataset**
   - Tests behavior with only one item
   - Verifies proper assignment and completion

3. **Zero Max Annotations**
   - Tests behavior when max_annotations_per_item is 0
   - Verifies proper handling of edge case

4. **Large Dataset**
   - Tests with many items and annotators
   - Verifies scalability and performance

## Test Structure

### Integration Tests (`TestAssignmentStrategies`)

These tests require a running server and test the full workflow:

```python
def test_random_assignment_strategy(self, server_url):
    """
    Test random assignment strategy:
    1. Create dataset with 5 items, max 2 annotations per item
    2. Create 8 annotators (more than needed)
    3. Verify random distribution
    4. Verify completion when all items have max annotations
    """
```

### Mocked Tests (`TestAssignmentStrategiesMocked`)

These tests use mocked HTTP responses for CI/CD pipelines:

```python
@patch('requests.post')
@patch('requests.get')
def test_random_assignment_mocked(self, mock_get, mock_post):
    """Test random assignment strategy with mocked responses."""
```

## Configuration

### Dataset Configuration

Each test creates a dataset with specific configuration:

```python
dataset_config = {
    "items": {
        "item_1": {"text": "Test item 1"},
        "item_2": {"text": "Test item 2"},
        # ... more items
    },
    "max_annotations_per_item": 2,
    "assignment_strategy": "random"
}
```

### User Configuration

Users are created with specific parameters:

```python
users_data = {
    "users": [
        {
            "username": "test_user_1",
            "initial_phase": "ANNOTATION",
            "assign_items": True
        }
        # ... more users
    ]
}
```

## Running the Tests

### All Assignment Strategy Tests

```bash
python -m pytest tests/test_assignment_strategies.py -v
```

### Specific Strategy Tests

```bash
# Random assignment only
python -m pytest tests/test_assignment_strategies.py::TestAssignmentStrategies::test_random_assignment_strategy -v

# Fixed order assignment only
python -m pytest tests/test_assignment_strategies.py::TestAssignmentStrategies::test_fixed_order_assignment_strategy -v
```

### Mocked Tests Only (for CI/CD)

```bash
python -m pytest tests/test_assignment_strategies.py::TestAssignmentStrategiesMocked -v
```

## Test Routes

The tests use the following test routes:

### `/test/create_dataset` (POST)
Creates a test dataset with specified configuration.

**Request:**
```json
{
    "items": {
        "item_1": {"text": "Test item 1"},
        "item_2": {"text": "Test item 2"}
    },
    "max_annotations_per_item": 2,
    "assignment_strategy": "random"
}
```

**Response:**
```json
{
    "status": "created",
    "summary": {
        "created": 2,
        "max_annotations_per_item": 2,
        "assignment_strategy": "random"
    },
    "items": ["item_1", "item_2"]
}
```

### `/test/submit_annotation` (POST)
Submits an annotation for testing purposes.

**Request:**
```json
{
    "instance_id": "item_1",
    "annotations": {
        "sentiment": {"label": "positive"}
    },
    "username": "test_user_1"
}
```

**Response:**
```json
{
    "status": "submitted",
    "instance_id": "item_1",
    "annotations": {
        "sentiment": {"label": "positive"}
    },
    "username": "test_user_1"
}
```

## Implementation Details

### Assignment Strategy Logic

The assignment strategies are implemented in `potato/item_state_management.py`:

```python
def assign_instances_to_user(self, user_state: UserState) -> int:
    if self.assignment_strategy == AssignmentStrategy.RANDOM:
        # Random assignment logic
    elif self.assignment_strategy == AssignmentStrategy.FIXED_ORDER:
        # Fixed order assignment logic
    elif self.assignment_strategy == AssignmentStrategy.LEAST_ANNOTATED:
        # Least-annotated assignment logic
    elif self.assignment_strategy == AssignmentStrategy.MAX_DIVERSITY:
        # Max-diversity assignment logic
```

### Disagreement Score Calculation

For max-diversity strategy, disagreement is calculated as:

```python
def _calculate_disagreement_score(self, instance_id: str) -> float:
    # Get all annotations for this item
    # Calculate ratio of unique annotations to total annotations
    # Higher ratio = more disagreement
    disagreement_score = len(unique_annotations) / total_annotations
    return disagreement_score
```

## Expected Behaviors

### Random Assignment
- Items should be distributed randomly across annotators
- Distribution should be roughly even over many runs
- No predictable pattern in assignment order

### Fixed Order Assignment
- Items should be assigned in the exact order they appear in the dataset
- First round: item_1, item_2, item_3, item_4
- Second round: item_1, item_2, item_3, item_4 (if max_annotations_per_item > 1)

### Least-Annotated Assignment
- Items with fewer annotations should be prioritized
- Distribution should be more balanced than random
- All items should reach similar annotation counts

### Max-Diversity Assignment
- Items with conflicting annotations should be prioritized
- Items with agreement should be deprioritized
- Focus on items that need more annotation due to disagreement

### Completion Behavior
- When all items have reached max_annotations_per_item, new users should get no assignments
- System should properly track completion state
- No infinite assignment loops

## Troubleshooting

### Common Issues

1. **Circular Import Errors**
   - Fixed by using lazy imports in `_calculate_disagreement_score`
   - Ensure proper import structure

2. **Server Not Running**
   - Integration tests require a running server
   - Use mocked tests for CI/CD environments

3. **Configuration Issues**
   - Ensure debug mode is enabled for test routes
   - Verify assignment strategy names match enum values

### Debug Mode

All test routes require debug mode to be enabled:

```python
if not config.get("debug", False):
    return jsonify({
        "error": "Test routes only available in debug mode"
    }), 403
```

## Future Enhancements

### Planned Improvements

1. **Active Learning Implementation**
   - Implement proper active learning strategy
   - Add machine learning model integration
   - Test uncertainty sampling

2. **LLM Confidence Implementation**
   - Implement LLM confidence-based assignment
   - Add LLM API integration
   - Test confidence scoring

3. **Performance Optimization**
   - Optimize assignment algorithms for large datasets
   - Add caching for disagreement scores
   - Implement batch assignment

4. **Additional Strategies**
   - User performance-based assignment
   - Item difficulty-based assignment
   - Time-based assignment

### Test Enhancements

1. **Load Testing**
   - Test with thousands of items and users
   - Measure assignment performance
   - Test memory usage

2. **Concurrency Testing**
   - Test simultaneous assignment requests
   - Verify thread safety
   - Test race condition handling

3. **Integration Testing**
   - Test with real annotation workflows
   - Test with different annotation types
   - Test with survey flow integration