# Potato on HuggingFace

Potato has a presence on the HuggingFace Hub: a small set of **live demo Spaces** you can try in
the browser, a wider catalog of deployed-but-paused ones, **sample annotation datasets**, and
guides for deploying your own. This page is the index.

- **Website:** [www.potatoannotator.com](https://www.potatoannotator.com)
- **Collection (all demos):** [Potato Annotation Demos](https://huggingface.co/collections/Blablablab/potato-annotation-demos-6a3753d95427d61a91ecf4fd)
- **Live demo:** [Blablablab/video-annotation](https://huggingface.co/spaces/Blablablab/video-annotation)
- **Deploy your own Space:** [deployment guide](huggingface_spaces.md)
- 🤖 **Use HF models for AI features:** [Using HuggingFace Models](../ai-intelligence/huggingface_models.md)
- 📤 **Export annotations to the Hub:** [HuggingFace Hub Export](huggingface_export.md)

> The demo Spaces live under the [`Blablablab`](https://huggingface.co/Blablablab) org and are
> grouped in a HuggingFace **Collection**. Each one is generated from a project in
> [`examples/`](https://github.com/davidjurgens/potato/tree/master/examples/) via the
> [Spaces catalog tooling](huggingface_spaces.md) — adding a new one is a single manifest
> entry. Every example in the repo runs locally whether or not it has a Space.

## Running a demo

HuggingFace caps a free CPU-basic organization at **three Spaces running at once**, and the
48-hour idle-sleep timer cannot be shortened on free hardware. A demo someone opens holds one
of those three slots for two days after its last visit. Three demos are therefore kept live and
the rest of the catalog is paused.

The three are marked **· live** below. They were picked from search traffic to
potatoannotator.com:

| Demo | Why |
|---|---|
| [video-annotation](https://huggingface.co/spaces/Blablablab/video-annotation) | Video action and temporal segmentation is the most-searched topic on the site |
| [agent-comparison](https://huggingface.co/spaces/Blablablab/agent-comparison) | LLM and agent evaluation is the second |
| [image-bbox](https://huggingface.co/spaces/Blablablab/image-bbox) | Image region annotation is the third |

Search demand concentrates in video, agents and images, so a traffic-led pick of three leaves
no text demo live. Span and classification annotation are in the catalog below but paused; run
one of them locally to try it.

Every other demo is deployed but **paused**. A paused Space does not wake when you open it;
only its owner can restart it. The rest of the catalog below is an index of what Potato
supports, and those Space pages will not open.

Any of them runs locally from the example it was generated from. This needs no HuggingFace
account and has no concurrency limit:

```bash
pip install potato-annotation
python potato/flask_server.py start examples/video/video-annotation/config.yaml -p 8000
```

> **"Duplicate this Space" no longer works on a free account.** HuggingFace now requires PRO
> for personal accounts, or Team/Enterprise for organizations, to create *or duplicate* a
> Gradio or Docker Space. Potato demos are Docker Spaces. Running the example locally, as
> above, is the free path.

## Demo catalog

Generated from `deployment/huggingface-spaces/spaces_manifest.yaml`. Entries marked
**· live** are the ones kept reachable; the rest are deployed but paused.
`python deployment/huggingface-spaces/audit_spaces.py` reports the current state.

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

### Span & structure (5)
- **ner-span** — Highlight-and-label text spans for NER / extraction.
- **coreference** — Link coreferent mentions across a document.
- **entity-linking** — Link entity spans to a knowledge-base catalog.
- **dependency-tree** — Annotate syntactic dependency arcs between tokens.
- **multi-span** — Span annotation across multiple text fields.

### Agent & GenAI evaluation (5)
- **agent-comparison** **· live** — Side-by-side comparison of two agent trajectories.
- **anthropic-evaluation** — Annotate Claude/Anthropic agent traces.
- **openai-evaluation** — Annotate OpenAI agent / tool-use traces.
- **rag-evaluation** — Rate retrieval relevance, faithfulness, citation accuracy.
- **web-agent-review** — Review web-agent runs with screenshot + click/scroll overlays.

### Multimodal (5)
- **image-bbox** **· live** — Draw labeled bounding boxes on images.
- **audio-classification** — Classify audio clips (emotion / event / speaker).
- **video-annotation** **· live** — Video player with temporal segment labeling.
- **video-classification** — Whole-clip video classification.
- **multimodal** — Combine media + text fields in one task.

### Advanced workflows (5)
- **codebook** — Shared evolving codebook across annotators.
- **adjudication** — Resolve multi-annotator disagreements.
- **quality-control** — Attention checks and gold-standard items.
- **conditional-logic** — Branching questions that adapt to prior answers.
- **mace** — Annotator competence estimation with MACE.

### Showcase (1)
- **all-annotation-types** — Every schema type in a single task.

### AI-assisted (5)
- **solo-mode** — LLM auto-labels while you calibrate; human-in-the-loop.
- **judge-calibration** — Calibrate an LLM judge against blind human labels.
- **ai-hints** — LLM label suggestions inline in the annotation UI.
- **span-ai-keywords** — LLM-suggested keyword spans to accept/reject.
- **llm-chat** — Evaluate a live LLM chat conversation.

### Domain layouts (3)
- **content-moderation** — Custom moderation layout with policy categories.
- **medical-review** — Domain layout for clinical text review.
- **dialogue-qa** — Turn-level dialogue question-answering layout.
## Deploying the catalog

See the [Spaces deployment runbook](huggingface_spaces.md):

```bash
python deployment/huggingface-spaces/build_space.py --list          # see all demos
python deployment/huggingface-spaces/build_space.py video-annotation
python deployment/huggingface-spaces/deploy_space.py video-annotation Blablablab
```

## Related

- [Deploy Potato on HuggingFace Spaces](huggingface_spaces.md)
- [HuggingFace Hub Export](huggingface_export.md) · [Datasets Integration](datasets_integration.md)
- [Using HuggingFace Models](../ai-intelligence/huggingface_models.md)
