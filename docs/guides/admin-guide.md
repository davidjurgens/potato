# Administrator Guide

This guide covers managing annotation campaigns: setting up authentication, monitoring progress, ensuring quality, and exporting results.

## Setting Up Authentication

Choose an authentication method based on your deployment:

| Method | Best For | Guide |
|--------|----------|-------|
| In-memory | Local development | Default, no config needed |
| Password + file | Team annotation | [Password Management](../auth-users/password_management.md) |
| Database | Production deployments | [Password Management](../auth-users/password_management.md#database-authentication-backend) |
| OAuth / SSO | Institutional login | [SSO & OAuth](../auth-users/sso_authentication.md) |
| Passwordless | Low-stakes, easy access | [Passwordless Login](../auth-users/passwordless_login.md) |

For user registration and access control, see [Users & Collaboration](../auth-users/user_and_collaboration.md).

## Quality Control

Ensure annotation quality with multiple strategies:

- **[Quality Control](../workflow/quality_control.md)** - Attention checks, gold standards, and inter-annotator agreement
- **[Training Phase](../workflow/training_phase.md)** - Require annotators to pass practice rounds before the real task
- **[Adjudication](../administration/adjudication.md)** - Expert review of annotator disagreements
- **[MACE](../advanced/mace.md)** - Statistical estimation of annotator competence

## Monitoring Progress

- **[Admin Dashboard](../administration/admin_dashboard.md)** - Real-time monitoring of annotation progress, annotator performance, and suspicious activity detection
- **[Behavioral Tracking](../advanced/behavioral_tracking.md)** - Timing, click patterns, and annotation change history
- **[Annotation History](../administration/annotation_history.md)** - Complete audit trail of all annotation actions
- **[Productivity](../administration/productivity.md)** - Keyboard shortcuts, tooltips, and efficiency features

## Managing Annotators

- **[Task Assignment](../advanced/task_assignment.md)** - Configure how items are distributed to annotators (random, fixed, active learning, diversity-based)
- **[Category Assignment](../advanced/category_assignment.md)** - Match annotators to items by expertise
- **[Diversity Ordering](../workflow/diversity_ordering.md)** - Present diverse items to reduce annotator fatigue

## Data Management

- **[Data Format](../configuration/data_format.md)** - Input data requirements
- **[Data Directory](../configuration/data_directory.md)** - Load data from a directory with live watching
- **[Remote Data Sources](../configuration/remote_data_sources.md)** - Load from S3, Google Drive, Dropbox, or databases
- **[Export Formats](../data-export/export_formats.md)** - Export to JSON, CSV, COCO, YOLO, CoNLL, Parquet
- **[HuggingFace Export](../data-export/huggingface_export.md)** - Push annotations to HuggingFace Hub

## Troubleshooting

- **[Debugging Guide](../tools/debugging_guide.md)** - Debug flags, common errors, and troubleshooting steps
- **[Configuration Reference](../configuration/configuration.md)** - Complete config options with defaults
