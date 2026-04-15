# Crowdsourcing Guide

This guide walks you through running annotation tasks on crowdsourcing platforms like Prolific and Amazon MTurk.

## Platform Setup

- **[Crowdsourcing Guide](../deployment/crowdsourcing.md)** - General setup for Prolific and MTurk integration
- **[MTurk Integration](../deployment/mturk_integration.md)** - Detailed Amazon MTurk HIT setup, payment, and management

## Authentication for Crowd Workers

For crowdsourcing, you typically want low-friction authentication:

- **[Passwordless Login](../auth-users/passwordless_login.md)** - Workers access tasks without passwords (recommended for most crowd tasks)
- **[SSO Authentication](../auth-users/sso_authentication.md)** - Institutional SSO for studies requiring verified identity

Platform-specific authentication (Prolific IDs, MTurk Worker IDs) is handled automatically when using the crowdsourcing integration.

## Quality Assurance for Crowd Tasks

Quality control is especially important with crowd workers:

- **[Quality Control](../workflow/quality_control.md)** - Attention checks and gold standard items to verify engagement
- **[Training Phase](../workflow/training_phase.md)** - Qualification training before the real task (filter unqualified workers)
- **[Adjudication](../administration/adjudication.md)** - Resolve disagreements between multiple annotators
- **[MACE](../advanced/mace.md)** - Statistical estimation of annotator competence and label recovery

## Task Design Best Practices

- **[Choosing Annotation Types](../annotation-types/choosing_annotation_types.md)** - Select appropriate schemas for non-expert annotators
- **[Form Layout](../configuration/form_layout.md)** - Design clear, easy-to-use form layouts
- **[Conditional Logic](../configuration/conditional_logic.md)** - Adaptive forms that simplify complex tasks
- **[Survey Instruments](../advanced/survey_instruments.md)** - 55 pre-built validated instruments for demographic and psychological surveys

## Multi-Phase Workflows

Set up consent, instructions, training, annotation, and post-study surveys:

- **[Multi-Phase Workflows](../workflow/surveyflow.md)** - Configure the full workflow pipeline

## Deployment

- **[Installation & Usage](../deployment/usage.md)** - Server setup and configuration
- **[HuggingFace Spaces](../data-export/huggingface_spaces.md)** - Deploy on HuggingFace Spaces (free hosting)

## Monitoring and Export

- **[Admin Dashboard](../administration/admin_dashboard.md)** - Monitor progress, track completions, detect suspicious activity
- **[Behavioral Tracking](../advanced/behavioral_tracking.md)** - Timing analysis and engagement metrics
- **[Export Formats](../data-export/export_formats.md)** - Export results in multiple formats
