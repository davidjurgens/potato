# Potato Documentation

**Potato** (POrtable Text Annotation TOol) is a **fully free** data annotation tool supporting a wide range of features throughout your entire annotation pipeline.

---

## Getting Started

- [Quick Start](quick-start.md) - Get running in 5 minutes
- [Installation & Usage](usage.md) - Detailed setup guide
- [Configuration Reference](configuration.md) - Complete config options
- [What's New in v2](new_features_v2.md) - Latest features and improvements

## Annotation Schemas

- [Schema Gallery](schemas_and_templates.md) - All annotation types with examples
- [Instance Display](instance_display.md) - Display images, video, audio, and text separately from annotation collection
- [Conditional Logic](conditional_logic.md) - Show/hide questions based on prior answers
- [Image Annotation](image_annotation.md) - Bounding boxes, polygons, and landmarks
- [Audio Annotation](audio_annotation.md) - Audio segmentation with waveform visualization
- [Video Annotation](video_annotation.md) - Frame-by-frame video labeling
- [Tiered Annotation](tiered_annotation.md) - ELAN-style hierarchical multi-tier annotation
- [Triage](triage.md) - Rapid accept/reject/skip data curation interface
- [Entity Linking](entity_linking.md) - Link spans to external knowledge bases (Wikidata, UMLS)
- [Coreference Annotation](coreference_annotation.md) - Group mentions of the same entity
- [Conversation Tree Annotation](conversation_tree_annotation.md) - Annotate hierarchical conversation structures
- [Format Support](format_support.md) - PDF, Word, code, and spreadsheet annotation
- [Span Linking](span_linking.md) - Relationship linking between text spans

## Workflow & Quality

- [Annotation Navigation](annotation_navigation.md) - Navigation tools and status indicators
- [Task Assignment](task_assignment.md) - Assignment strategies and configuration
- [Diversity Ordering](diversity_ordering.md) - Embedding-based clustering for diverse item presentation
- [Training Phase](training_phase.md) - Annotator training and qualification
- [Quality Control](quality_control.md) - Attention checks and gold standards
- [Category Assignment](category_assignment.md) - Category-based item assignment
- [Surveyflow](surveyflow.md) - Pre/post annotation surveys

## AI & Intelligence

- [AI Support](ai_support.md) - AI-powered label suggestions
- [Active Learning](active_learning_guide.md) - ML-based prioritization
- [ICL Labeling](icl_labeling.md) - In-context learning for labeling

## User Management

- [Users & Collaboration](user_and_collaboration.md) - User settings and access control
- [Passwordless Login](passwordless_login.md) - URL-based authentication

## Crowdsourcing

- [Crowdsourcing Guide](crowdsourcing.md) - Prolific and MTurk integration
- [MTurk Integration](mturk_integration.md) - Detailed Amazon MTurk setup guide

## Administration

- [Admin Dashboard](admin_dashboard.md) - Monitoring and management
- [Behavioral Tracking](behavioral_tracking.md) - User behavior analytics
- [Annotation History](annotation_history.md) - Tracking annotation changes

## Data & Output

- [Data Format](data_format.md) - Input and output data formats
- [Export Formats](export_formats.md) - Export to COCO, YOLO, CoNLL, and more
- [UI Configuration](ui_configuration.md) - Interface customization
- [Layout Customization](layout_customization.md) - Custom CSS layouts and styling

## Tools & Utilities

- [Preview CLI](preview_cli.md) - Preview configs without running server
- [Migration CLI](migration_cli.md) - Upgrade v1 configs to v2
- [Debugging Guide](debugging_guide.md) - Debug flags and troubleshooting
- [Simulator](simulator.md) - Annotation simulation tool

## Productivity Features

- [Productivity](productivity.md) - Tooltips, shortcuts, and highlights

## Contributing

- [Contributing Guide](open-sourcing.md) - How to contribute to Potato

---

## Quick Links

| Task | Documentation |
|------|---------------|
| Set up a basic annotation task | [Quick Start](quick-start.md) |
| Choose an annotation type | [Schema Gallery](schemas_and_templates.md) |
| Display images/video with radio buttons | [Instance Display](instance_display.md) |
| Show/hide questions based on answers | [Conditional Logic](conditional_logic.md) |
| Annotate PDFs, Word docs, or code | [Format Support](format_support.md) |
| Configure for MTurk | [MTurk Integration](mturk_integration.md) |
| Configure for Prolific | [Crowdsourcing Guide](crowdsourcing.md#prolific-integration) |
| Monitor annotation progress | [Admin Dashboard](admin_dashboard.md) |
| Add AI suggestions | [AI Support](ai_support.md) |
| Set up quality control | [Quality Control](quality_control.md) |
| Present items diversely | [Diversity Ordering](diversity_ordering.md) |
| Debug configuration issues | [Debugging Guide](debugging_guide.md) |
| Create custom visual layouts | [Layout Customization](layout_customization.md) |
| Rapidly filter/triage data | [Triage](triage.md) |
| Link entities to knowledge bases | [Entity Linking](entity_linking.md) |
| Annotate coreference chains | [Coreference Annotation](coreference_annotation.md) |
| Annotate conversation trees | [Conversation Tree Annotation](conversation_tree_annotation.md) |
| Navigate efficiently through items | [Annotation Navigation](annotation_navigation.md) |
| Export to COCO/YOLO/CoNLL | [Export Formats](export_formats.md) |

---

## Example Projects

Ready-to-use example configurations are available in the `examples/` directory:

```bash
# Run a simple radio button example
python potato/flask_server.py start examples/classification/single-choice/config.yaml -p 8000

# Run a sophisticated layout example (content moderation, dialogue QA, medical review)
python potato/flask_server.py start examples/custom-layouts/content-moderation/config.yaml -p 8000
```

See the [examples](https://github.com/davidjurgens/potato/tree/main/examples) directory for more examples, including:

- `classification/` - Classification annotation examples (radio, checkbox, likert, etc.)
- `span/` - Span annotation examples (NER, linking, coreference, etc.)
- `image/` - Image annotation examples
- `video/` - Video annotation examples
- `audio/` - Audio annotation examples
- `advanced/` - Advanced features (conditional logic, quality control, etc.)
- `custom-layouts/` - Sophisticated custom layout examples
