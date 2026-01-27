# Training Phase Documentation

The training phase is an optional component of the annotation workflow that allows administrators to provide users with practice questions and feedback before they begin the main annotation task. This helps ensure annotation quality and user understanding of the task requirements.

## Overview

The training phase provides:
- **Practice Questions**: Users answer questions with known correct answers
- **Immediate Feedback**: Users receive feedback on their answers with explanations
- **Retry Functionality**: Users can retry incorrect answers until they get them right
- **Progress Tracking**: Administrators can monitor training completion and performance
- **Quality Assurance**: Only users who pass training can proceed to annotation

## Configuration

### Basic Training Configuration

To enable the training phase, add a `training` section to your YAML configuration:

```yaml
training:
  enabled: true
  data_file: "training_data.json"
  annotation_schemes: ["sentiment", "topic"]
  passing_criteria:
    min_correct: 3
    require_all_correct: false
  allow_retry: true
  failure_action: "retry"  # or "advance"
```

### Configuration Options

| Option | Type | Required | Default | Description |
|--------|------|----------|---------|-------------|
| `enabled` | boolean | Yes | false | Whether to enable the training phase |
| `data_file` | string | Yes* | - | Path to training data file (required if enabled) |
| `annotation_schemes` | list | No | All schemes | Which annotation schemes to use in training |
| `passing_criteria.min_correct` | integer | No | 3 | Minimum correct answers required to pass |
| `passing_criteria.require_all_correct` | boolean | No | false | Whether all questions must be correct |
| `passing_criteria.max_mistakes` | integer | No | -1 | Maximum total mistakes before failure (-1 = unlimited) |
| `passing_criteria.max_mistakes_per_question` | integer | No | -1 | Maximum mistakes per question before failure (-1 = unlimited) |
| `allow_retry` | boolean | No | true | Whether to allow retrying incorrect answers |
| `failure_action` | string | No | "move_to_done" | Action when user fails ("move_to_done" or "advance") |

### Training Strategies

Potato supports multiple training strategies that can be combined:

1. **Minimum Correct**: User must get at least N answers correct to pass
   ```yaml
   passing_criteria:
     min_correct: 3
   ```

2. **Require All Correct**: User must answer every question correctly
   ```yaml
   passing_criteria:
     require_all_correct: true
   ```

3. **Maximum Mistakes**: User is kicked out after N total mistakes
   ```yaml
   passing_criteria:
     max_mistakes: 5  # Fail after 5 wrong answers total
   ```

4. **Maximum Mistakes Per Question**: User is kicked out after N mistakes on any single question
   ```yaml
   passing_criteria:
     max_mistakes_per_question: 2  # Fail after 2 wrong answers on same question
   ```

5. **Allow Retry**: Let users retry incorrect answers
   ```yaml
   allow_retry: true
   ```

These can be combined for complex qualification requirements. For example:
```yaml
passing_criteria:
  min_correct: 3           # Need 3 correct
  max_mistakes: 5          # But no more than 5 total mistakes
  max_mistakes_per_question: 2  # And no more than 2 per question
```

### Phase Integration

Add the training phase to your workflow by including it in the phases order:

```yaml
phases:
  order: ["consent", "instructions", "training", "annotation"]
  consent:
    type: "consent"
    file: "consent.json"
  instructions:
    type: "instructions"
    file: "instructions.json"
  training:
    type: "training"
    file: "training.json"
```

## Training Data Format

Training data is stored in a JSON file with the following structure:

```json
{
  "training_instances": [
    {
      "id": "train_1",
      "text": "This is a positive sentiment text.",
      "correct_answers": {
        "sentiment": "positive",
        "topic": "emotion"
      },
      "explanation": "This text expresses positive emotions and opinions."
    },
    {
      "id": "train_2",
      "text": "This is a negative sentiment text.",
      "correct_answers": {
        "sentiment": "negative",
        "topic": "emotion"
      },
      "explanation": "This text expresses negative emotions and opinions."
    }
  ]
}
```

### Training Instance Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | Yes | Unique identifier for the training instance |
| `text` | string | Yes | The text to be annotated |
| `correct_answers` | object | Yes | Map of schema names to correct values |
| `explanation` | string | No | Explanation shown when user answers incorrectly |

### Correct Answers Format

The `correct_answers` field should match your annotation schemes:

```json
{
  "sentiment": "positive",           // Radio button selection
  "topic": ["emotion", "personal"],  // Multi-select options
  "rating": 4,                      // Numeric rating
  "text_field": "example response"  // Text input
}
```

## User Experience

### Training Interface

Users see a dedicated training interface with:
- Clear indication they're in the training phase
- The training question text
- Annotation forms matching the main task
- Submit button to answer the question

### Feedback System

After submitting an answer, users receive:

**Correct Answers:**
- Green feedback message: "Correct! Moving to next question."
- Automatic progression to the next question
- No retry option needed

**Incorrect Answers:**
- Red feedback message with explanation
- Option to retry the question (if enabled)
- Clear explanation of why their answer was wrong

### Progress Tracking

Users can see their progress through:
- Current question number
- Total questions remaining
- Training completion status

## Admin Monitoring

### Dashboard Statistics

The admin dashboard shows training statistics for each user:

- **Training Completed**: Whether the user has passed training
- **Correct Answers**: Number of correct answers given
- **Total Attempts**: Total number of attempts across all questions
- **Pass Rate**: Percentage of correct answers
- **Current Question**: Which question the user is currently on
- **Total Questions**: Total number of training questions

### API Endpoints

Training statistics are available through the admin API:

```bash
# Get all annotators with training stats
GET /admin/api/annotators

# Get specific user state including training
GET /admin/user_state/{user_id}
```

### Example API Response

```json
{
  "annotators": [
    {
      "user_id": "user123",
      "phase": "TRAINING",
      "training_completed": false,
      "training_correct_answers": 2,
      "training_total_attempts": 3,
      "training_pass_rate": 66.67,
      "training_current_question": 2,
      "training_total_questions": 5
    }
  ]
}
```

## Best Practices

### Designing Training Questions

1. **Start Simple**: Begin with straightforward examples
2. **Cover All Cases**: Include examples for each possible answer
3. **Clear Explanations**: Provide helpful explanations for incorrect answers
4. **Realistic Examples**: Use examples similar to the actual annotation task
5. **Appropriate Difficulty**: Set reasonable passing criteria

### Configuration Recommendations

1. **Enable Retries**: Allow users to learn from mistakes
2. **Set Reasonable Criteria**: Don't require 100% accuracy unless necessary
3. **Use Explanations**: Help users understand why answers are correct/incorrect
4. **Monitor Performance**: Use admin dashboard to track training effectiveness

### Training Data Guidelines

1. **Consistent Format**: Ensure training data matches your annotation schemes
2. **Clear Examples**: Use unambiguous examples with obvious correct answers
3. **Comprehensive Coverage**: Include examples for all possible annotation values
4. **Helpful Explanations**: Provide explanations that help users understand the task

## Troubleshooting

### Common Issues

**Training not appearing:**
- Check that `training.enabled` is set to `true`
- Verify the training phase is in the phases order
- Ensure the training data file exists and is valid

**Training data not loading:**
- Check the `data_file` path is correct
- Verify the JSON format is valid
- Ensure annotation schemes match between config and training data

**Users stuck in training:**
- Check passing criteria are reasonable
- Verify training data has correct answers
- Monitor admin dashboard for training progress

**Feedback not showing:**
- Check `allow_retry` setting
- Verify explanations are provided in training data
- Ensure training template is properly configured

### Debugging

Use the admin dashboard to:
- Monitor user training progress
- Check training statistics
- Verify training data loading
- Track user phase progression

## Example Configurations

### Basic Sentiment Training

```yaml
training:
  enabled: true
  data_file: "sentiment_training.json"
  annotation_schemes: ["sentiment"]
  passing_criteria:
    min_correct: 2
    require_all_correct: false
  allow_retry: true
  failure_action: "retry"
```

### Advanced Multi-Scheme Training

```yaml
training:
  enabled: true
  data_file: "advanced_training.json"
  annotation_schemes: ["sentiment", "topic", "confidence"]
  passing_criteria:
    min_correct: 5
    require_all_correct: false
  allow_retry: true
  failure_action: "retry"
```

### Strict Training (No Retries)

```yaml
training:
  enabled: true
  data_file: "strict_training.json"
  annotation_schemes: ["sentiment"]
  passing_criteria:
    min_correct: 3
    require_all_correct: true
  allow_retry: false
  failure_action: "advance"
```

## Integration with Existing Workflows

The training phase integrates seamlessly with existing annotation workflows:

1. **Phase Progression**: Users automatically advance through phases
2. **State Persistence**: Training progress is saved and restored
3. **Admin Monitoring**: Training stats appear in existing admin interfaces
4. **Template System**: Uses existing template and styling systems
5. **Authentication**: Works with existing authentication systems

## Performance Considerations

- Training data is loaded once at server startup
- Training state is stored in memory (same as other user state)
- No additional database requirements
- Minimal performance impact on existing functionality

## Security

- Training data is validated against annotation schemes
- User training state is isolated per user
- Admin access controls apply to training statistics
- No sensitive data exposure through training interface