# Potato: The Portable Annotation Tool

[![Documentation](https://img.shields.io/badge/docs-readthedocs-blue)](https://potatoannotator.readthedocs.io/)
[![PyPI](https://img.shields.io/pypi/v/potato-annotation)](https://pypi.org/project/potato-annotation/)
[![License](https://img.shields.io/badge/license-Polyform%20Shield-green)](LICENSE)
[![Paper](https://img.shields.io/badge/paper-EMNLP%202022-orange)](https://aclanthology.org/2022.emnlp-demos.33/)
[![Live Demo](https://img.shields.io/badge/demo-HuggingFace%20Spaces-yellow)](https://huggingface.co/spaces/Blablablab/potato)

**Potato** is a free, self-hosted annotation platform for NLP, Agentic, and GenAI research. Annotate text, audio, video, images, documents, agent traces, and more — configured entirely through YAML. No coding required.

**[Try the live demo on HuggingFace Spaces](https://huggingface.co/spaces/Blablablab/potato)** — no installation needed.

---

## Quick Start

```bash
pip install potato-annotation
potato start examples/classification/single-choice/config.yaml -p 8000
```

Or run from source:

```bash
git clone https://github.com/davidjurgens/potato.git
cd potato && pip install -r requirements.txt
python potato/flask_server.py start examples/classification/single-choice/config.yaml -p 8000
```

Open [http://localhost:8000](http://localhost:8000) and start annotating. Browse the [`examples/`](examples/) directory for ready-to-use templates.

---

## What Can You Annotate?

Potato handles the full spectrum of annotation tasks — from traditional NLP labeling to evaluating the latest AI agent systems.

### Data Types

| Modality | Capabilities |
|----------|-------------|
| **Text** | Classification, span labeling, entity linking, coreference, pairwise comparison ([docs](docs/annotation-types/schemas_and_templates.md)) |
| **Agent Traces** | Step-by-step evaluation of LLM agents, tool calls, ReAct chains, and multi-agent systems ([docs](docs/agent-evaluation/agent_traces.md)) |
| **Web Agents** | Screenshot-based review with SVG click/scroll overlays, or live browsing with automatic trace recording ([docs](docs/agent-evaluation/web_agent_annotation.md)) |
| **RAG Pipelines** | Retrieval relevance, answer faithfulness, citation accuracy, hallucination detection |
| **Audio** | Waveform visualization, segment labeling, ELAN-style tiered annotation ([docs](docs/annotation-types/multimedia/audio_annotation.md)) |
| **Video** | Frame-by-frame labeling, temporal segments, playback sync ([docs](docs/annotation-types/multimedia/video_annotation.md)) |
| **Images** | Bounding boxes, polygons, landmarks, classification ([docs](docs/annotation-types/multimedia/image_annotation.md)) |
| **Dialogue** | Turn-level annotation, conversation trees, interactive chat evaluation |
| **Documents** | PDF, Word, Markdown, code, and spreadsheets with coordinate mapping ([docs](docs/annotation-types/format_support.md)) |

### Annotation Schemes

| Scheme | Use Case |
|--------|----------|
| Radio / Checkbox / Likert | Classification, multi-label, rating scales |
| Span annotation | NER, highlighting, hallucination marking |
| Pairwise comparison | A/B testing, best-worst scaling |
| Per-step ratings | Evaluate individual agent actions or dialogue turns |
| Free text | Open-ended responses with validation |
| Triage | Rapid accept/reject/skip curation ([docs](docs/annotation-types/triage.md)) |
| Conditional logic | Adaptive forms that respond to prior answers ([docs](docs/configuration/conditional_logic.md)) |

---

## Agent & LLM Evaluation

Potato provides purpose-built tooling for evaluating AI agents at every level of granularity.

### Trace Formats

Import traces from any major agent framework with the built-in converter:

```bash
python -m potato.trace_converter --input traces.json --input-format openai --output data.jsonl
```

Supported formats: **OpenAI**, **Anthropic/Claude**, **ReAct**, **LangChain**, **LangFuse**, **WebArena**, **SWE-bench**, **OpenTelemetry**, **CrewAI/AutoGen/LangGraph**, **MCP**, **Aider**, **Claude Code**, **ATIF**, **SWE-Agent**, and **Web Agent**. Auto-detection is available with `--auto-detect`.

### Evaluation Levels

| Level | What You Annotate | Example |
|-------|------------------|---------|
| **Trajectory** | Overall task success, efficiency, safety | "Did the agent complete the task?" |
| **Step** | Individual action correctness, reasoning quality | Per-turn Likert ratings on each agent step |
| **Span** | Specific text segments within agent output | Highlight hallucinated claims, factual errors |
| **Comparison** | Side-by-side A/B agent evaluation | "Which agent performed better?" |

### Web Agent Viewer

An interactive viewer for GUI agent traces — navigate step-by-step through screenshots with SVG overlays showing clicks, bounding boxes, mouse paths, and scroll actions. Annotators rate each step with inline controls while a filmstrip bar provides quick navigation.

### Ready-to-Use Agent Examples

| Example | What It Evaluates |
|---------|-------------------|
| [agent-trace-evaluation](examples/agent-traces/agent-trace-evaluation/) | Text agent traces with MAST error taxonomy + hallucination spans |
| [visual-agent-evaluation](examples/agent-traces/visual-agent-evaluation/) | GUI agents with screenshot grounding accuracy |
| [agent-comparison](examples/agent-traces/agent-comparison/) | Side-by-side A/B agent comparison |
| [rag-evaluation](examples/agent-traces/rag-evaluation/) | RAG retrieval relevance and citation accuracy |
| [openai-evaluation](examples/agent-traces/openai-evaluation/) | OpenAI Chat API traces with tool calls |
| [anthropic-evaluation](examples/agent-traces/anthropic-evaluation/) | Claude messages with tool_use blocks |
| [swebench-evaluation](examples/agent-traces/swebench-evaluation/) | Coding agents with patch correctness ratings |
| [multi-agent-evaluation](examples/agent-traces/multi-agent-evaluation/) | Multi-agent coordination (CrewAI, AutoGen, LangGraph) |
| [web-agent-review](examples/agent-traces/web-agent-review/) | Pre-recorded web traces with step-by-step overlay viewer |
| [web-agent-creation](examples/agent-traces/web-agent-creation/) | Live web browsing with automatic trace recording |

---

## AI-Powered Annotation

### LLM Label Suggestions

Integrate any LLM provider to pre-annotate instances and suggest labels. Annotators review and correct — dramatically faster than labeling from scratch.

Supported backends: **OpenAI**, **Anthropic**, **Ollama**, **vLLM**, **Gemini**, **HuggingFace**, **OpenRouter**

### Active Learning

Potato reorders your annotation queue based on model uncertainty so annotators label the most informative instances first. Supports uncertainty sampling, BADGE, BALD, diversity, and hybrid strategies ([docs](docs/ai-intelligence/active_learning_guide.md)).

### Solo Mode

A human-LLM collaborative workflow where the system learns from annotator feedback and progressively transitions to autonomous LLM labeling as agreement improves ([docs](docs/solo-mode/solo_mode.md)).

### Chat Assistant

An LLM-powered sidebar where annotators can ask questions about difficult instances. The AI provides guidance informed by your task description and annotation guidelines — helping annotators think through decisions without auto-labeling ([docs](docs/ai-intelligence/chat_support.md)).

---

## Quality Control & Workflows

### Quality Assurance

| Feature | Description |
|---------|-------------|
| Attention checks | Automatically inserted known-answer items to verify engagement |
| Gold standards | Track annotator accuracy against expert labels |
| Inter-annotator agreement | Krippendorff's alpha (general) and Cohen's kappa (step-level agent evaluation) |
| Training phase | Practice annotations with feedback before the real task |
| Behavioral tracking | Timing, click patterns, and annotation change history |

### Annotation Workflows

| Workflow | Description |
|----------|-------------|
| **Multi-annotator** | Multiple annotators per item with overlap control and agreement metrics |
| **Adjudication** | Expert review of annotator disagreements to produce gold labels ([docs](docs/administration/admin_dashboard.md)) |
| **Solo mode** | Human-LLM collaboration with progressive automation ([docs](docs/solo-mode/solo_mode.md)) |
| **Crowdsourcing** | Prolific and MTurk integration with platform-specific auth ([docs](docs/deployment/crowdsourcing.md)) |
| **Triage** | Rapid accept/reject/skip for data curation ([docs](docs/annotation-types/triage.md)) |

---

## Authentication & Deployment

Potato supports multiple authentication methods, from passwordless quick-start to enterprise SSO:

| Method | Use Case |
|--------|----------|
| **In-memory** | Local development, quick studies |
| **Password + file persistence** | Team annotation with shared credential files ([docs](docs/auth-users/password_management.md)) |
| **Database** | Production deployments with SQLite or PostgreSQL ([docs](docs/auth-users/password_management.md#database-authentication-backend)) |
| **OAuth / SSO** | Google, GitHub, or institutional OIDC login ([docs](docs/auth-users/sso_authentication.md)) |
| **Clerk** | Managed authentication via Clerk.com ([docs](docs/auth-users/sso_authentication.md)) |
| **Passwordless** | Low-stakes tasks where ease of access matters ([docs](docs/auth-users/passwordless_login.md)) |

Passwords are hashed with per-user PBKDF2-SHA256 salts. Admins can reset passwords via CLI (`potato reset-password`) or REST API. Self-service token-based reset is also available.

---

## Example Projects

Ready-to-use templates organized by type in [`examples/`](examples/):

| Category | Examples |
|----------|----------|
| [Classification](examples/classification/) | Radio, checkbox, Likert, slider, pairwise comparison |
| [Span](examples/span/) | NER, span linking, coreference, entity linking |
| [Agent Traces](examples/agent-traces/) | LLM agents, web agents, RAG, multi-agent, code agents |
| [Audio](examples/audio/) | Waveform annotation, classification, ELAN-style tiered |
| [Video](examples/video/) | Frame-level labeling, temporal segments |
| [Image](examples/image/) | Bounding boxes, PDF/document annotation |
| [Advanced](examples/advanced/) | Solo mode, adjudication, quality control, conditional logic |
| [AI-Assisted](examples/ai-assisted/) | LLM suggestions, Ollama integration |
| [Custom Layouts](examples/custom-layouts/) | Content moderation, dialogue QA, medical review |

### Research Showcase

The **[Potato Showcase](https://github.com/davidjurgens/potato-showcase/)** contains annotation projects from published research — sentiment analysis, dialogue evaluation, summarization, and more.

---

## Documentation

| Topic | Link |
|-------|------|
| Quick Start | [docs/quick-start.md](docs/quick-start.md) |
| Configuration Reference | [docs/configuration/configuration.md](docs/configuration/configuration.md) |
| Schema Gallery | [docs/annotation-types/schemas_and_templates.md](docs/annotation-types/schemas_and_templates.md) |
| Agent Trace Evaluation | [docs/agent-evaluation/agent_traces.md](docs/agent-evaluation/agent_traces.md) |
| Web Agent Annotation | [docs/agent-evaluation/web_agent_annotation.md](docs/agent-evaluation/web_agent_annotation.md) |
| AI Support | [docs/ai-intelligence/ai_support.md](docs/ai-intelligence/ai_support.md) |
| Active Learning | [docs/ai-intelligence/active_learning_guide.md](docs/ai-intelligence/active_learning_guide.md) |
| Solo Mode | [docs/solo-mode/solo_mode.md](docs/solo-mode/solo_mode.md) |
| Quality Control | [docs/workflow/quality_control.md](docs/workflow/quality_control.md) |
| Password Management | [docs/auth-users/password_management.md](docs/auth-users/password_management.md) |
| SSO & OAuth | [docs/auth-users/sso_authentication.md](docs/auth-users/sso_authentication.md) |
| Admin Dashboard | [docs/administration/admin_dashboard.md](docs/administration/admin_dashboard.md) |
| Crowdsourcing | [docs/deployment/crowdsourcing.md](docs/deployment/crowdsourcing.md) |
| Export Formats | [docs/data-export/export_formats.md](docs/data-export/export_formats.md) |
| Full Documentation Index | [docs/index.md](docs/index.md) |

---

## Development

```bash
# Run tests
pytest tests/ -v

# By category
pytest tests/unit/ -v        # Unit tests (fast)
pytest tests/server/ -v      # Integration tests
pytest tests/selenium/ -v    # Browser tests

# With coverage
pytest --cov=potato --cov-report=html
```

---

## Support

- **Issues**: [GitHub Issues](https://github.com/davidjurgens/potato/issues)
- **Questions**: jurgens@umich.edu
- **Docs**: [potatoannotator.readthedocs.io](https://potatoannotator.readthedocs.io/)

---

## License

Potato is licensed under [Polyform Shield](LICENSE). Non-commercial applications can use Potato however they want. Commercial applications can use Potato to annotate all they want, but cannot integrate Potato into a commercial product.

<details>
<summary>License FAQ</summary>

| Use Case | Allowed? |
|----------|----------|
| Academic research | Yes |
| Company annotation | Yes |
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
