# AI-Assisted Annotation Guide

This guide covers all the ways Potato uses AI and machine learning to speed up annotation.

## AI Label Suggestions

Integrate any LLM provider to pre-annotate instances with suggested labels. Annotators review and correct rather than labeling from scratch.

Supported providers: OpenAI, Anthropic, Ollama, vLLM, Gemini, HuggingFace, OpenRouter

```yaml
ai_support:
  enabled: true
  endpoint_type: openai
  ai_config:
    model: gpt-4o-mini
    api_key: ${OPENAI_API_KEY}
```

See **[AI Support](../ai-intelligence/ai_support.md)** for full configuration.

## Visual AI Support

Use YOLO object detection and vision LLMs for image and video annotation tasks:

See **[Visual AI Support](../ai-intelligence/visual_ai_support.md)**.

## Chat Assistant

An LLM-powered sidebar where annotators ask questions about difficult instances. The AI provides guidance informed by your task description without auto-labeling:

See **[Chat Support](../ai-intelligence/chat_support.md)**.

## Active Learning

Automatically reorder the annotation queue based on model uncertainty, so annotators label the most informative instances first:

- **[Active Learning Guide](../ai-intelligence/active_learning_guide.md)** - Setup and configuration
- **[Active Learning Strategies](../ai-intelligence/active_learning_strategies.md)** - Query strategies reference (uncertainty, BADGE, BALD, diversity, hybrid)

```yaml
active_learning:
  enabled: true
  schema_names: ["sentiment"]
  query_strategy: "hybrid"
  hybrid_weights:
    uncertainty: 0.7
    diversity: 0.3
```

## In-Context Learning

Use few-shot examples from existing annotations to improve LLM labeling accuracy:

See **[ICL Labeling](../ai-intelligence/icl_labeling.md)**.

## Option Highlighting

AI-assisted highlighting of likely annotation options to draw annotator attention:

See **[Option Highlighting](../ai-intelligence/option_highlighting.md)**.

## Solo Mode (Human-LLM Collaboration)

A workflow where the system learns from annotator feedback and progressively transitions to autonomous LLM labeling as agreement improves:

- **[Solo Mode](../solo-mode/solo_mode.md)** - Overview and setup
- **[Solo Mode Advanced](../solo-mode/solo_mode_advanced.md)** - Edge case rules, labeling functions, confidence routing
- **[Solo Mode Developer Guide](../solo-mode/solo_mode_developer_guide.md)** - Architecture and extension points

## Embedding Visualization

UMAP-based dashboard for visualizing instance similarity and exploring annotation patterns:

See **[Embedding Visualization](../advanced/embedding_visualization.md)**.

## AI Architecture

For developers extending the AI integration:

See **[AI Integration Internals](../ai-intelligence/ai_integration_internals.md)**.
