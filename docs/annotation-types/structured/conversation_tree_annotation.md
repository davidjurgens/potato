# Conversation Tree Annotation

The tree annotation schema annotates hierarchical conversation structures: chatbot response trees, dialogue systems, branching narratives. Annotators can rate individual nodes, select preferred paths, and compare branches at decision points.

## Overview

Conversation trees are common in:
- **Chatbot evaluation**: Rating quality of multiple response options
- **Dialogue systems**: Selecting preferred conversation paths
- **A/B testing**: Comparing different response strategies
- **Interactive fiction**: Evaluating branching story paths

The tree annotation schema provides tools for navigating and annotating these tree structures.

## Quick Start

```yaml
annotation_schemes:
  - annotation_type: tree_annotation
    name: response_quality
    description: Evaluate the conversation tree
    node_scheme:
      annotation_type: likert
      min_label: "Poor"
      max_label: "Excellent"
      size: 5
    path_selection:
      enabled: true
      description: Select the best response path through the tree
```

## Configuration Options

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `annotation_type` | string | Must be `"tree_annotation"` |
| `name` | string | Unique identifier for this schema |
| `description` | string | Instructions displayed to annotators |

### Optional Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `node_scheme` | object | `{}` | Annotation scheme config for per-node annotation |
| `path_selection.enabled` | boolean | `false` | Enable path selection through the tree |
| `path_selection.description` | string | "Select the best response path" | Instructions for path selection |
| `branch_comparison.enabled` | boolean | `false` | Enable branch comparison mode |

### Display options

Set these under `display_options` on the `conversation_tree` field:

| Option | Default | Description |
|--------|---------|-------------|
| `collapsed_depth` | `2` | Nodes at or below this depth start collapsed |
| `node_style` | `card` | Node rendering style |
| `show_node_ids` | `false` | Show each node's id |
| `max_depth` | `null` | Stop rendering below this depth |
| `show_timestamps` | `false` | Show per-node times |
| `turn_meta_fields` | `null` | Metadata keys to surface per node |
| `meta_key` | `meta` | Where per-node metadata lives |

## Per-node annotation with turn-level schemes

Any [turn-level scheme](../../agent-evaluation/turn_level_annotation.md) can bind
to a tree, attaching a widget to each node:

```yaml
instance_display:
  fields:
    - key: conversation_tree
      type: conversation_tree
      label: "Thread structure"

annotation_schemes:
  - annotation_type: radio
    name: branch_role
    description: "Role"
    labels: [opens, escalates, de_escalates, tangent]
    turn_level: true
    turn_binding:
      field: conversation_tree
```

Values are stored under each node's `id`. That makes the **two-view pattern**
work: render the same conversation as both a tree and a flat `dialogue`, give
each view the schemes it suits, and — because a turn's `turn_id` and a node's
`id` are the same utterance identifier — both refer to the same messages.

```yaml
    - key: conversation_tree      # structure: where the thread turns
      type: conversation_tree
    - key: conversation           # text: what was said, and spans
      type: dialogue
      span_target: true
      display_options:
        indent_replies: true
```

See `examples/conversation/convokit-tree/` for a worked example.

!!! note "The tree is not a span target"
    Collapsing a subtree changes the rendered text, so offsets measured against
    it could not stay stable. Put `span_target: true` on a `dialogue` field
    showing the same conversation instead — spans are scoped to the field, so one
    can still cross messages.

A node flagged `synthetic` — the wrapper Potato adds when a conversation has
several roots, so it still renders as one tree — gets no annotation widgets. It
is not a message, and a value stored against it could not be exported anywhere.

## Example Configurations

### Basic Node Rating

Rate each response in the conversation tree:

```yaml
annotation_schemes:
  - annotation_type: tree_annotation
    name: response_rating
    description: Rate each response in the conversation
    node_scheme:
      annotation_type: likert
      min_label: "Very Bad"
      max_label: "Very Good"
      size: 5
```

### Path Selection

Select the best path through the conversation:

```yaml
annotation_schemes:
  - annotation_type: tree_annotation
    name: best_path
    description: Navigate the conversation tree
    path_selection:
      enabled: true
      description: Click on responses to build the best conversation path
```

### Combined Rating and Path Selection

```yaml
annotation_schemes:
  - annotation_type: tree_annotation
    name: full_eval
    description: Evaluate responses and select the best path
    node_scheme:
      annotation_type: radio
      labels: ["Good", "Acceptable", "Poor"]
    path_selection:
      enabled: true
      description: After rating, select the best overall path
```

### Multi-Criteria Node Rating

Rate nodes on multiple dimensions:

```yaml
annotation_schemes:
  - annotation_type: tree_annotation
    name: multi_criteria
    description: Evaluate each response on multiple criteria
    node_scheme:
      annotation_type: multirate
      options:
        - Relevance
        - Fluency
        - Helpfulness
      labels: ["1", "2", "3", "4", "5"]
```

### Branch Comparison Mode

Compare sibling branches at decision points:

```yaml
annotation_schemes:
  - annotation_type: tree_annotation
    name: branch_compare
    description: Compare response options at each decision point
    branch_comparison:
      enabled: true
    node_scheme:
      annotation_type: radio
      labels: ["Better", "Same", "Worse"]
```

## Data Format

### Input Data

Tree data should be provided in JSON format with a hierarchical structure:

```json
{
  "id": "conv_001",
  "tree": {
    "id": "root",
    "role": "user",
    "content": "Hello, I need help with my order",
    "children": [
      {
        "id": "resp_a",
        "role": "assistant",
        "content": "I'd be happy to help! Can you provide your order number?",
        "children": [
          {
            "id": "user_2",
            "role": "user",
            "content": "It's ORDER-12345",
            "children": []
          }
        ]
      },
      {
        "id": "resp_b",
        "role": "assistant",
        "content": "Sure, what seems to be the problem?",
        "children": []
      }
    ]
  }
}
```

### Configuration for Tree Data

```yaml
item_properties:
  id_key: id
  tree_key: tree  # Points to the tree structure
```

## User Interface

### Tree Visualization

The conversation tree is displayed visually with:
- **Nodes** representing messages/responses
- **Edges** connecting parent-child relationships
- **Branching points** where multiple responses exist

### Node Selection

Click on any node to:
1. View the full message content
2. Access the annotation panel for that node
3. Add the node to the selected path (if path selection is enabled)

### Node Annotation Panel

Selecting a node opens a panel holding whatever `node_scheme` describes,
rendered through the same registry as a top-level scheme — so any annotation
type works there, with its own tooltips, labels and layout. A close button
dismisses it; the tree above stays where it is.

Answers are kept per node. A node that already has one is marked with a tick in
the tree, so finding the ones still to do does not mean opening each in turn.

`node_scheme` needs a `name`: it becomes the key each answer is stored under.
Without one the scheme is named `<scheme>_node`.

### Path Selection

When path selection is enabled:
- Click nodes to add them to your path
- The selected path is highlighted
- Use "Clear Path" to start over

## Output Format

Tree annotations are saved with both node-level and path-level data. Node
answers are keyed by node id, then by the `name` of the `node_scheme`:

```json
{
  "response_quality": {
    "node_annotations": {
      "resp_a": {
        "rating": 4
      },
      "resp_b": {
        "rating": 2
      },
      "user_2": {
        "rating": 5
      }
    },
    "selected_path": ["root", "resp_a", "user_2"]
  }
}
```

## Use Cases

### Chatbot Response Evaluation

Evaluate quality of chatbot responses:

```yaml
annotation_schemes:
  - annotation_type: tree_annotation
    name: chatbot_eval
    description: Rate each chatbot response
    node_scheme:
      annotation_type: likert
      min_label: "Unhelpful"
      max_label: "Very Helpful"
      size: 5
    path_selection:
      enabled: true
      description: Select the response path you would prefer
```

### Dialogue Policy Comparison

Compare different dialogue strategies:

```yaml
annotation_schemes:
  - annotation_type: tree_annotation
    name: policy_compare
    description: Compare dialogue strategies
    node_scheme:
      annotation_type: multiselect
      labels:
        - "Stays on topic"
        - "Asks clarifying questions"
        - "Provides helpful information"
        - "Uses appropriate tone"
    branch_comparison:
      enabled: true
```

### Story Path Evaluation

Evaluate branching narrative paths:

```yaml
annotation_schemes:
  - annotation_type: tree_annotation
    name: story_eval
    description: Evaluate story branches
    node_scheme:
      annotation_type: multirate
      options:
        - Engagement
        - Coherence
        - Creativity
      labels: ["1", "2", "3", "4", "5"]
    path_selection:
      enabled: true
      description: Select the most engaging story path
```

### Error Analysis

Identify where conversations go wrong:

```yaml
annotation_schemes:
  - annotation_type: tree_annotation
    name: error_analysis
    description: Identify problematic responses
    node_scheme:
      annotation_type: multiselect
      labels:
        - "Factually incorrect"
        - "Off-topic"
        - "Tone inappropriate"
        - "Missing information"
        - "No issues"
```

## Workflow

### Recommended Process

1. **Overview**: First, explore the entire tree to understand the conversation
2. **Node annotation**: Rate or label individual nodes as needed
3. **Path selection**: If enabled, select the preferred path
4. **Review**: Check that all required annotations are complete

### Tips for Annotators

- Start from the root and work down
- Consider the context from parent nodes when rating
- For path selection, imagine you are the user choosing responses
- Use the tree visualization to identify branching points

## Best Practices

1. **Keep node schemes simple**: Complex annotation interfaces on each node can slow annotation

2. **Provide context**: Ensure annotators can see parent messages when rating a response

3. **Consider tree depth**: Very deep trees may benefit from collapsible nodes

4. **Use path selection wisely**: Path selection works best for smaller trees

5. **Train annotators**: Tree navigation requires practice - provide training examples

## Visual Customization

### Tree Layout Options

The tree can be displayed in different layouts:
- **Vertical**: Root at top, branches go down
- **Horizontal**: Root at left, branches go right

Configure in UI settings:

```yaml
ui:
  tree_layout: "vertical"  # or "horizontal"
```

### Node Styling

Nodes can be styled based on:
- Role (user vs. assistant)
- Annotation status (rated vs. unrated)
- Path membership

## Troubleshooting

### Tree Not Displaying

1. Verify `tree_key` in `item_properties` points to correct field
2. Check that tree data is valid JSON
3. Ensure each node has required fields (id, content)

### The node panel opens but is empty

The panel says which:

- *"This tree has no node_scheme, so there is nothing to annotate on a node."*
  The scheme has no `node_scheme` block. Path selection still works.
- *"The node question form could not be loaded."* The page did not load
  `segment-questions.js`. This should not happen; it is worth reporting.

If `node_scheme` names an annotation type that fails to render, the panel shows
that type's own error rather than an empty box.

### Nothing is stored for a tree nobody touched

That is deliberate. Both values start empty, so opening an item and moving on
records nothing — an untouched tree is unanswered rather than answered with an
empty path. Mark `required: true` under `label_requirement` if an answer is
compulsory.

### Path Selection Issues

1. Confirm `path_selection.enabled: true` is set.
2. Nodes are clickable across the whole card; clicking the collapse triangle
   toggles the subtree instead.
3. Clicking a node already on the path takes it off again.

## Related Documentation

- [Schemas and Templates](../schemas_and_templates.md) - Overview of all annotation types
- [Pairwise Comparison](../schemas_and_templates.md) - For simpler A/B comparisons
- [Best-Worst Scaling](../schemas_and_templates.md) - For ranking multiple options
