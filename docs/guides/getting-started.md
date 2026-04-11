# Getting Started Guide

This guide walks you through setting up your first annotation project with Potato.

## Installation

```bash
pip install potato-annotation
```

Or install from source:

```bash
git clone https://github.com/davidjurgens/potato.git
cd potato && pip install -r requirements.txt
```

For full installation details, see [Installation & Usage](../deployment/usage.md).

## Your First Annotation Task

The fastest way to get started:

```bash
pip install potato-annotation
potato start examples/classification/single-choice/config.yaml -p 8000
```

Open [http://localhost:8000](http://localhost:8000) and you're ready to annotate. Browse the `examples/` directory for ready-to-use templates.

For the step-by-step walkthrough, see [Quick Start](../quick-start.md).

## Understanding Configuration

Every Potato project is defined by a YAML configuration file. Key sections:

| Section | Purpose |
|---------|---------|
| `data_files` | Input data paths |
| `annotation_schemes` | Define annotation types and labels |
| `item_properties` | Map data fields (id_key, text_key) |
| `task_dir` | Output directory for annotations |

See [Configuration Reference](../configuration/configuration.md) for all options, and [Data Format](../configuration/data_format.md) for input/output specifications.

## Choosing an Annotation Type

Potato supports 30+ annotation types. Start with the decision guide:

- **[Choosing the Right Annotation Type](../annotation-types/choosing_annotation_types.md)** - Interactive decision tree
- **[Schema Gallery](../annotation-types/schemas_and_templates.md)** - Visual gallery of all types with examples

Common starting points:
- **Radio buttons** for single-choice classification
- **Checkboxes** for multi-label tasks
- **Likert scales** for rating tasks
- **Span annotation** for NER and text highlighting

## Setting Up Workflows

Potato supports multi-phase workflows: consent, instructions, training, annotation, and post-study surveys.

- [Multi-Phase Workflows](../workflow/surveyflow.md) - Configure phase progression
- [Training Phase](../workflow/training_phase.md) - Practice annotations before the real task

## Exporting Results

After annotation, export in multiple formats:

- [Export Formats](../data-export/export_formats.md) - JSON, CSV, COCO, YOLO, CoNLL, Parquet
- [HuggingFace Export](../data-export/huggingface_export.md) - Push directly to HuggingFace Hub

## Next Steps

- [Administrator Guide](admin-guide.md) - Managing annotators and quality control
- [Developer Guide](developer-guide.md) - Extending Potato and API integration
- [AI-Assisted Annotation Guide](ai-assisted-annotation-guide.md) - Speed up annotation with LLMs
- [Agent Evaluation Guide](agent-evaluation-guide.md) - Evaluate AI agent systems
- [Crowdsourcing Guide](crowdsourcing-guide.md) - Run tasks on Prolific and MTurk
