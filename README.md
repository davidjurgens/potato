# Potato: The Portable Text Annotation Tool

[![Documentation](https://img.shields.io/badge/docs-readthedocs-blue)](https://potato-annotation.readthedocs.io/)
[![PyPI](https://img.shields.io/pypi/v/potato-annotation)](https://pypi.org/project/potato-annotation/)
[![License](https://img.shields.io/badge/license-Polyform%20Shield-green)](LICENSE)
[![Paper](https://img.shields.io/badge/paper-EMNLP%202022-orange)](https://aclanthology.org/2022.emnlp-demos.33/)

<p align="center">
<img src="https://github.com/davidjurgens/potato/raw/master/docs/img/potato-goal.png" width="600" height="280">
</p>

**Potato** is a lightweight, configuration-driven annotation tool for NLP research. Go from zero to annotating in minutes—no coding required.

## Why Potato?

| Feature | Potato | Other Tools |
|---------|--------|-------------|
| Setup time | Minutes (YAML config) | Hours/days (custom code) |
| Coding required | None | Often extensive |
| Self-hosted | Yes (full data control) | Often cloud-only |
| AI assistance | Built-in LLM support | Rarely available |
| Cost | Free for research | Often paid |

---

## Key Features

### Multi-Modal Annotation
Potato supports annotation across multiple data types:

| Modality | Features |
|----------|----------|
| **Text** | Classification, span labeling, pairwise comparison, free-form responses |
| **Audio** | Waveform visualization, segment labeling, playback controls ([docs](docs/audio_annotation.md)) |
| **Video** | Frame-by-frame annotation, temporal segments, playback sync ([docs](docs/video_annotation.md)) |
| **Images** | Region labeling, classification, comparison tasks |
| **Dialogue** | Turn-level annotation, conversation threading |

### Annotation Schemes
- **Classification**: Radio buttons, checkboxes, Likert scales
- **Span Annotation**: Highlight and label text spans with keyboard shortcuts
- **Pairwise Comparison**: Side-by-side comparisons, best-worst scaling
- **Free Text**: Text boxes with validation and character limits

### AI-Powered Assistance
- **Label Suggestions**: LLM-powered pre-annotations to speed up work
- **Active Learning**: Prioritize uncertain instances for efficient labeling
- **Multiple Backends**: OpenAI, Anthropic, Ollama, vLLM, and more

### Quality Control
- **Attention Checks**: Automatically inserted validation questions
- **Gold Standards**: Track annotator accuracy against known answers
- **Inter-Annotator Agreement**: Built-in Krippendorff's alpha calculation
- **Time Tracking**: Monitor annotation speed per instance

### Productivity
- **Keyboard Shortcuts**: Full keyboard navigation and labeling
- **Dynamic Highlighting**: Smart keyword highlighting based on labels
- **Tooltips**: Hover descriptions for complex label schemes
- **Progress Tracking**: Real-time completion statistics

### Deployment Options
- **Local Development**: Single command startup
- **Team Annotation**: Multi-user with authentication
- **Crowdsourcing**: Prolific and MTurk integration
- **Enterprise**: MySQL backend for large-scale deployments

---

## Quick Start

### Option 1: Install from PyPI (Recommended)

```bash
pip install potato-annotation

# List available templates
potato list all

# Get a template project
potato get sentiment_analysis

# Start annotating
potato start sentiment_analysis
```

### Option 2: Run from Source

```bash
git clone https://github.com/davidjurgens/potato.git
cd potato
pip install -r requirements.txt

# Start a simple annotation task
python potato/flask_server.py start project-hub/simple_examples/configs/simple-check-box.yaml -p 8000
```

Then open [http://localhost:8000](http://localhost:8000) in your browser.

---

## Documentation

| Topic | Description |
|-------|-------------|
| [Getting Started](https://potato-annotation.readthedocs.io/en/latest/usage/) | Installation and first project setup |
| [Configuration Guide](https://potato-annotation.readthedocs.io/en/latest/schemas_and_templates/) | YAML configuration options |
| [Annotation Schemas](https://potato-annotation.readthedocs.io/en/latest/schemas_and_templates/) | Radio, checkbox, span, likert, and more |
| [Data Formats](https://potato-annotation.readthedocs.io/en/latest/data_format/) | Input/output data specifications |
| [AI Support](docs/ai_support.md) | LLM integration for label suggestions |
| [Quality Control](docs/quality_control.md) | Attention checks and gold standards |
| [Active Learning](docs/active_learning_guide.md) | ML-based instance prioritization |
| [Admin Dashboard](docs/admin_dashboard.md) | Monitoring and analytics |
| [Crowdsourcing](https://potato-annotation.readthedocs.io/en/latest/crowdsourcing/) | Prolific and MTurk setup |
| [User Simulator](docs/simulator.md) | Testing and load simulation |

---

## Example Projects

Ready-to-use annotation setups in [`project-hub/`](project-hub/):

| Project | Description | Config |
|---------|-------------|--------|
| [Sentiment Analysis](project-hub/sentiment_analysis/) | Document-level sentiment classification | Radio buttons |
| [Dialogue Analysis](project-hub/dialogue_analysis/) | Span labeling in conversations | Span annotation |
| [Summarization Eval](project-hub/summarization_evaluation/) | Compare and rate summaries | Likert + pairwise |
| [Question Answering](project-hub/question_answering/) | Extract answer spans | Span + checkbox |
| [Simple Examples](project-hub/simple_examples/) | Minimal configs for each schema type | Various |

**More examples**: Browse the [Potato Showcase](https://github.com/davidjurgens/potato-showcase/) for a gallery of real-world annotation configurations and interfaces.

See [all example projects](https://potato-annotation.readthedocs.io/en/latest/example-projects/) in the documentation.

---

## What's New in v2.0

- **AI Support**: Integrated LLM assistance with OpenAI, Anthropic, Gemini, Ollama, vLLM
- **Audio Annotation**: Waveform-based segmentation with Peaks.js
- **Video Annotation**: Frame-by-frame labeling with playback controls
- **Active Learning**: Uncertainty sampling for efficient annotation
- **Training Phase**: Practice annotations with feedback
- **Quality Control**: Attention checks, gold standards, agreement metrics
- **User Simulator**: Automated testing with configurable annotator behaviors
- **Database Backend**: MySQL support for large-scale deployments
- **Debug Mode**: Skip to specific phases, selective logging

See [CHANGELOG.md](CHANGELOG.md) for full release history.

---

## Architecture

```
potato/
├── flask_server.py      # Main application server
├── routes.py            # HTTP endpoints
├── templates/           # Jinja2 HTML templates
├── static/              # JavaScript, CSS
├── server_utils/
│   └── schemas/         # Annotation type implementations
├── ai/                  # LLM endpoint integrations
├── simulator/           # User simulation for testing
└── quality_control.py   # QC validation logic

project-hub/             # Example annotation projects
tests/                   # Test suite
docs/                    # Documentation
```

---

## Development

```bash
# Run tests
pytest tests/ -v

# Run specific test categories
pytest tests/unit/ -v        # Unit tests
pytest tests/simulator/ -v   # Simulator tests
pytest tests/server/ -v      # Integration tests

# Run with coverage
pytest --cov=potato --cov-report=html
```

---

## Support

- **Issues**: [GitHub Issues](https://github.com/davidjurgens/potato/issues)
- **Questions**: pedropei@umich.edu or jurgens@umich.edu
- **Documentation**: [potato-annotation.readthedocs.io](https://potato-annotation.readthedocs.io/)

---

## License

Potato is dual-licensed under [Polyform Shield](LICENSE) for non-commercial use. Commercial licensing is available—contact jurgens@umich.edu for details.

<details>
<summary>License FAQ</summary>

| Use Case | Allowed? |
|----------|----------|
| Academic research | Yes |
| Internal company annotation | Yes |
| Fork for personal development | Yes |
| Integration in open-source pipelines | Yes |
| Commercial annotation service | Contact us |
| Competing annotation platform | Contact us |

</details>

---

## Citation

```bibtex
@inproceedings{pei2022potato,
  title={POTATO: The Portable Text Annotation Tool},
  author={Pei, Jiaxin and Ananthasubramaniam, Aparna and Wang, Xingyao and Zhou, Naitian and Dedeloudis, Apostolos and Sargent, Jackson and Jurgens, David},
  booktitle={Proceedings of the 2022 Conference on Empirical Methods in Natural Language Processing: System Demonstrations},
  year={2022}
}
```
