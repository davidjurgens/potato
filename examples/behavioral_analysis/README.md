# Behavioral Data Analysis Examples

This directory contains examples and tools for analyzing behavioral tracking data collected by Potato's interaction tracking system.

## Contents

- **`analyze_behavioral_data.ipynb`**: Jupyter notebook with comprehensive analysis examples
- **`example_behavioral_data.json`**: Sample behavioral data for testing and learning

## Quick Start

1. Install required dependencies:
   ```bash
   pip install pandas numpy matplotlib seaborn jupyter
   ```

2. Start Jupyter:
   ```bash
   jupyter notebook analyze_behavioral_data.ipynb
   ```

3. Run the cells to see analysis examples

## Using Your Own Data

To analyze data from your Potato annotation project:

```python
from pathlib import Path
import json

# Load from annotation output directory
output_dir = Path('path/to/annotation_output')
behavioral_data = {}

for user_dir in output_dir.iterdir():
    if user_dir.is_dir():
        state_file = user_dir / 'user_state.json'
        if state_file.exists():
            with open(state_file) as f:
                user_state = json.load(f)
            user_id = user_state.get('user_id')
            behavioral = user_state.get('instance_id_to_behavioral_data', {})
            if behavioral:
                behavioral_data[user_id] = behavioral

print(f"Loaded data for {len(behavioral_data)} users")
```

## What's Tracked

- **Interactions**: Clicks, focus changes, keyboard shortcuts, navigation
- **AI Assistance**: Request/response timing, acceptance rates
- **Annotation Changes**: All modifications with timestamps
- **Timing**: Session duration, focus time by element
- **Scroll Depth**: How far users scrolled

## Analysis Capabilities

The notebook demonstrates:

1. **Basic Statistics**: Time, interactions, changes per user
2. **Time Analysis**: Distribution and outliers
3. **AI Usage Analysis**: Accept rates, decision times
4. **Interaction Patterns**: What users click on
5. **Quality Detection**: Finding suspicious annotators
6. **Focus Analysis**: Where attention is spent
7. **Change Patterns**: How users modify annotations
8. **Report Generation**: Summary reports for stakeholders

## See Also

- [Behavioral Tracking Documentation](../../docs/behavioral_tracking.md)
- [Admin Dashboard](../../docs/admin_dashboard.md) - Real-time monitoring
- [Quality Control](../../docs/quality_control.md) - Automated quality checks
