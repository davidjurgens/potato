# Potato on HuggingFace

Potato has a growing presence on the HuggingFace Hub: **live demo Spaces** you can try in the
browser, **sample annotation datasets**, and guides for deploying your own. This page is the
index.

- 🥔 **Website:** [www.potatoannotator.com](https://www.potatoannotator.com)
- 🗂️ **Collection (all demos):** [Potato Annotation Demos](https://huggingface.co/collections/Blablablab/potato-annotation-demos-6a3753d95427d61a91ecf4fd)
- 🤗 **Live demo:** [Blablablab/agent-trace-evaluation](https://huggingface.co/spaces/Blablablab/agent-trace-evaluation)
- 📚 **Deploy your own Space:** [deployment guide](../../deployment/huggingface-spaces/deploy.md)
- 🤖 **Use HF models for AI features:** [Using HuggingFace Models](../ai-intelligence/huggingface_models.md)
- 📤 **Export annotations to the Hub:** [HuggingFace Hub Export](huggingface_export.md)

> The full catalog of demo Spaces is rolling out under the
> [`Blablablab`](https://huggingface.co/Blablablab) org and grouped in a HuggingFace
> **Collection**. Each demo is generated from a project in [`examples/`](../../examples/) via the
> [Spaces catalog tooling](../../deployment/huggingface-spaces/deploy_spaces.md) — adding a new
> one is a single manifest entry.

## Running any demo

On HuggingFace free CPU-basic hardware, an org can keep ~3 Spaces running at once, so a
curated set of flagships stays live (auto-waking when you open them) while the rest are
deployed but paused. **Any demo can be run on demand:** open its Space and click
**⋮ → Duplicate this Space** to launch your own copy on free hardware (the data and config
come with it — edit them to make it yours).

Every demo Space links back to **[www.potatoannotator.com](https://www.potatoannotator.com)**
from both its landing card and the in-app footer.

## Demo catalog

Every entry below is a self-contained, one-click annotation demo (log in with any username).

### Text classification (9)
- **sentiment-analysis** — Single-choice radio labeling with sequential keybindings.
- **multi-label** — Checkbox multi-select labeling for overlapping categories.
- **likert-scales** — Likert-scale rating for agreement / intensity judgments.
- **slider-rating** — Continuous slider scoring for fine-grained judgments.
- **best-worst-scaling** — Best-worst scaling for robust relative ranking.
- **llm-preference** — Pairwise preference judgments over LLM responses (RLHF-style).
- **pairwise-comparison** — A/B comparison of two items side by side.
- **ranking** — Drag-to-rank ordering of candidate items.
- **survey** — Multi-question survey with mixed input types.

### Span & structure (6)
- **ner-span** — Highlight-and-label text spans for NER / extraction.
- **coreference** — Link coreferent mentions across a document.
- **entity-linking** — Link entity spans to a knowledge-base catalog.
- **dependency-tree** — Annotate syntactic dependency arcs between tokens.
- **multi-span** — Span annotation across multiple text fields.
- **event-annotation** — Mark event triggers and arguments in text.

### Agent & GenAI evaluation (20+)
- **agent-trace-evaluation** — Evaluate agent traces: success, efficiency, side effects, hallucination spans.
- **agent-comparison** / **multi-dim-comparison** — Compare two trajectories, overall or per dimension.
- **anthropic-evaluation** / **openai-evaluation** — Annotate Claude / OpenAI agent traces.
- **coding-agent-evaluation** / **-comparison** / **-prm** / **-review** — Evaluate, compare, process-reward, and review coding agents.
- **swebench-evaluation** — Annotate SWE-bench attempts and patches.
- **multi-agent-evaluation** — Evaluate multi-agent interactions.
- **complex-annotation** — Rich multi-schema annotation over complex traces.
- **continuous-eval** — Continuous / streaming evaluation of agent runs.
- **trajectory-evaluation** / **trajectory-correction** — Step quality + edit traces for SFT/DPO.
- **rag-evaluation** — Retrieval relevance, faithfulness, citation accuracy.
- **visual-agent-evaluation** / **web-agent-review** — Screenshot-based GUI/web agent review with overlays.
- **triage-queue** — Signal-based queue for prioritizing traces to review.
- **judge-alignment** — Measure LLM-judge agreement with human annotations.

  _Live/ingestion variants (`live-agent-evaluation`, `live-coding-agent`, `web-agent-creation`,
  `langchain-integration`) are available to run locally; they deploy as Spaces only where they
  render from bundled static data._

### Multimodal (10)
- **image-classification** · **image-bbox** · **image-ai-detection** — Classify, draw boxes, real-vs-AI.
- **pdf-annotation** · **pdf-bbox** — Annotate and box PDF documents.
- **audio-annotation** · **audio-classification** — Waveform segment labeling and clip classification.
- **video-annotation** · **video-classification** — Temporal segments and whole-clip labels.
- **multimodal** — Combine media + text fields in one task.

### Advanced workflows (6)
- **qda-mode** — Codebook-driven qualitative coding with memos and cases.
- **codebook** — Shared evolving codebook across annotators.
- **adjudication** — Resolve multi-annotator disagreements.
- **quality-control** — Attention checks and gold-standard items.
- **conditional-logic** — Branching questions that adapt to prior answers.
- **mace** — Annotator competence estimation with MACE.

### AI-assisted (5)
_These showcase LLM features and need an endpoint — wire to the HF Inference API
([guide](../ai-intelligence/huggingface_models.md)) before deploying._
- **solo-mode** — LLM auto-labels while you calibrate (human-in-the-loop).
- **judge-calibration** — Calibrate an LLM judge against blind human labels.
- **ai-hints** — LLM label suggestions inline in the annotation UI.
- **span-ai-keywords** — LLM-suggested keyword spans to accept/reject.
- **llm-chat** — Evaluate a live LLM chat conversation.

### Domain layouts & showcase (4)
- **content-moderation** · **medical-review** · **dialogue-qa** — Custom domain layouts.
- **all-annotation-types** — Every schema type in a single task.

## Deploying the catalog

See the [Spaces deployment runbook](../../deployment/huggingface-spaces/deploy_spaces.md):

```bash
python deployment/huggingface-spaces/build_space.py --list          # see all demos
python deployment/huggingface-spaces/build_space.py agent-trace-evaluation
python deployment/huggingface-spaces/deploy_space.py agent-trace-evaluation Blablablab
```

## Related

- [Deploy Potato on HuggingFace Spaces](huggingface_spaces.md)
- [HuggingFace Hub Export](huggingface_export.md) · [Datasets Integration](datasets_integration.md)
- [Using HuggingFace Models](../ai-intelligence/huggingface_models.md)
