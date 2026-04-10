# Potato Documentation

**Potato** (POrtable Text Annotation TOol) is a **fully free** data annotation tool supporting a wide range of features throughout your entire annotation pipeline.

---

## Getting Started

- [Quick Start](quick-start.md) - Get running in 5 minutes
- [Installation & Usage](usage.md) - Detailed setup guide
- [Configuration Reference](configuration.md) - Complete config options
- [What's New in v2](new_features_v2.md) - Latest features and improvements
- [Comparison with Other Tools](comparison.md) - How Potato compares to alternatives

## Annotation Schemas

- **[Choosing the Right Annotation Type](choosing_annotation_types.md)** - Decision guide for selecting the best schema for your task
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
- [Soft Label](soft_label.md) - Probability distribution across labels via constrained sliders
- [Confidence Annotation](confidence_annotation.md) - Pair any annotation with an explicit confidence rating
- [Constant Sum](constant_sum.md) - Allocate a fixed budget of points across categories
- [Semantic Differential](semantic_differential.md) - Bipolar adjective scales measuring connotative meaning
- [Ranking](ranking.md) - Drag-and-drop ordering of items by preference
- [Range Slider](range_slider.md) - Dual-thumb slider for selecting an acceptable min-max range
- [Hierarchical Multi-Label Selection](hierarchical_multiselect.md) - Select labels from an expandable tree taxonomy
- [Visual Analog Scale (VAS)](vas.md) - Continuous analog scale for fine-grained magnitude estimation
- [Extractive QA](extractive_qa.md) - SQuAD-style answer span highlighting
- [Rubric Evaluation](rubric_eval.md) - Multi-criteria rubric grid for LLM evaluation
- [Text Edit / Post-Edit](text_edit.md) - Inline text editing with diff tracking
- [Error Span (MQM)](error_span.md) - Error annotation with typed severity and quality scoring
- [Card Sorting](card_sort.md) - Drag-and-drop grouping of items into categories
- [Conjoint Analysis](conjoint.md) - Discrete choice between multi-attribute profiles
- [Pairwise Comparison](pairwise_annotation.md) - Binary or scale-based A/B comparisons
- [Multi-Dimensional Pairwise](multi_dimensional_pairwise.md) - Compare items on multiple axes simultaneously
- [Best-Worst Scaling](bws.md) - Select best and worst from tuples
- [Dialogue Annotation](dialogue_annotation.md) - Multi-turn conversation annotation
- [Text Annotation](text_annotation.md) - Free-text input and rationale annotation
- [Event Annotation](event_annotation.md) - N-ary event structures with triggers and arguments
- [Trajectory Evaluation](trajectory_eval.md) - Per-step error annotation for agent traces

## Workflow & Quality

- [Annotation Navigation](annotation_navigation.md) - Navigation tools and status indicators
- [Task Assignment](task_assignment.md) - Assignment strategies and configuration
- [Diversity Ordering](diversity_ordering.md) - Embedding-based clustering for diverse item presentation
- [Training Phase](training_phase.md) - Annotator training and qualification
- [Quality Control](quality_control.md) - Attention checks and gold standards
- [Adjudication](adjudication.md) - Multi-annotator disagreement resolution
- [MACE](mace.md) - Multi-Annotator Competence Estimation via variational inference
- [Iterative BWS](iterative_bws.md) - Adaptive Best-Worst Scaling for fine-grained ordinal rankings
- [Category Assignment](category_assignment.md) - Category-based item assignment
- [Surveyflow](surveyflow.md) - Pre/post annotation surveys
- [Annotation Filtering](annotation_filtering.md) - Filter data based on prior annotations
- [Survey Instruments](survey_instruments.md) - 55 pre-built validated psychological instruments

## Agent Evaluation

- **[Coding Agent Annotation](coding_agent_annotation.md)** - Evaluate agentic coding systems (Claude Code, SWE-Agent, Aider) with diff rendering, PRM annotation, and code review
- [Agent Traces](agent_traces.md) - Evaluate AI agent traces and trajectories
- [Live Agent Interaction](live_agent.md) - Observe and interact with a live AI agent in real time
- [Web Agent Annotation](web_agent_annotation.md) - Review and create web agent browsing traces

## Solo Mode

- [Solo Mode](solo_mode.md) - Human-LLM collaborative annotation workflow
- [Solo Mode Advanced Features](solo_mode_advanced.md) - Edge case rules, labeling functions, confidence routing
- [Solo Mode Developer Guide](solo_mode_developer_guide.md) - Architecture and extension points

## AI & Intelligence

- [AI Support](ai_support.md) - AI-powered label suggestions
- [Active Learning](active_learning_guide.md) - ML-based prioritization
- [Active Learning Strategies](active_learning_strategies.md) - Query strategies reference (BADGE, BALD, hybrid, cold-start)
- [ICL Labeling](icl_labeling.md) - In-context learning for labeling
- [Visual AI Support](visual_ai_support.md) - YOLO and vision LLM support for image/video annotation
- [Chat Support](chat_support.md) - LLM-powered sidebar for annotator assistance
- [Option Highlighting](option_highlighting.md) - AI-assisted highlighting of likely annotation options
- [Embedding Visualization](embedding_visualization.md) - UMAP-based instance similarity dashboard

## Authentication & User Management

- [Users & Collaboration](user_and_collaboration.md) - User registration, access control, and collaboration
- [Password Management](password_management.md) - Password security, reset flows, database backend, and shared credentials
- [Passwordless Login](passwordless_login.md) - Authentication without passwords
- [SSO & OAuth Authentication](sso_authentication.md) - Google, GitHub, and institutional SSO login

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
- [HuggingFace Hub Export](huggingface_export.md) - Push annotations to HuggingFace Hub
- [HuggingFace Datasets Integration](datasets_integration.md) - Load annotations as DatasetDict or DataFrame
- [Remote Data Sources](remote_data_sources.md) - Load data from S3, Google Drive, Dropbox, URLs, and databases
- [Data Directory](data_directory.md) - Load data from a directory with optional live watching

## UI & Customization

- [UI Configuration](ui_configuration.md) - Interface customization
- [Layout Customization](layout_customization.md) - Custom CSS layouts and styling
- [Form Layout](form_layout.md) - Grid and column layout for annotation forms
- [Form Layout Advanced](form_layout_advanced.md) - Styling, alignment, and padding options
- [Multilingual](multilingual.md) - Localization and RTL support

## Integrations

- [Webhooks](webhooks.md) - Outgoing webhook notifications for annotation events
- [HuggingFace Spaces](huggingface_spaces.md) - Deploy Potato on HuggingFace Spaces
- [LangChain Integration](langchain_integration.md) - Send LangChain agent traces to Potato

## Tools & Utilities

- [Preview CLI](preview_cli.md) - Preview configs without running server
- [Migration CLI](migration_cli.md) - Upgrade v1 configs to v2
- [Debugging Guide](debugging_guide.md) - Debug flags and troubleshooting
- [Simulator](simulator.md) - Annotation simulation tool
- [API Reference](api_reference.md) - REST API endpoints documentation

## Productivity Features

- [Productivity](productivity.md) - Tooltips, shortcuts, and highlights

## Release Notes

- [v2.4.4](releasenotes/v2.4.4.md) - Span Annotation Fixes & UX Improvements
- [v2.4.3](releasenotes/v2.4.3.md) - Coding Agent Annotation, Localization & Stability
- [v2.4.1](releasenotes/v2.4.1.md) - Bug Fixes
- [v2.4.0](releasenotes/v2.4.0.md) - Agent Evaluation, AI-Assisted Annotation & Enterprise Integration
- [v2.3.0](releasenotes/v2.3.0.md) - Solo Mode, Agent Workflows & Security Hardening
- [v2.2.0](releasenotes/v2.2.0.md) - Comprehensive Annotation & Export Platform
- [v2.1.0](releasenotes/v2.1.0.md) - Adjudication & Multi-Modal Annotation
- [v2.0.0](releasenotes/v2.0.0.md) - Backend Refactor

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
| Set up SSO/OAuth login | [SSO Authentication](sso_authentication.md) |
| Reset a user's password | [Password Management](password_management.md) |
| Use a database for user storage | [Password Management](password_management.md#database-authentication-backend) |
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
| Evaluate AI agent traces | [Agent Traces](agent_traces.md) |
| Use Solo Mode for collaborative annotation | [Solo Mode](solo_mode.md) |
| Export annotations to Parquet | [Export Formats](export_formats.md#parquet) |
| Export to COCO/YOLO/CoNLL | [Export Formats](export_formats.md) |
| Push annotations to HuggingFace Hub | [HuggingFace Export](huggingface_export.md) |
| Deploy on HuggingFace Spaces | [HuggingFace Spaces](huggingface_spaces.md) |
| Set up webhook notifications | [Webhooks](webhooks.md) |
| Use LLM chat assistant for annotators | [Chat Support](chat_support.md) |
| Evaluate coding agents | [Coding Agent Annotation](coding_agent_annotation.md) |
| Review web agent traces | [Web Agent Annotation](web_agent_annotation.md) |
| Load data from S3/GDrive/Dropbox | [Remote Data Sources](remote_data_sources.md) |
| Use pre-built survey instruments | [Survey Instruments](survey_instruments.md) |
| Set up multilingual interface | [Multilingual](multilingual.md) |
| Resolve annotator disagreements | [Adjudication](adjudication.md) |
| Browse the REST API | [API Reference](api_reference.md) |

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
- `agent-traces/` - Agent trace evaluation examples (RAG, GUI agents, comparisons)
- `custom-layouts/` - Sophisticated custom layout examples
