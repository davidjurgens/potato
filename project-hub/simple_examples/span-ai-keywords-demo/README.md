# Span Annotation with AI Keywords and Admin Highlights Demo

This example demonstrates all three overlay systems working together in the Potato annotation platform:

## Overlay Types

1. **User Span Annotations** (Filled overlays)
   - Created by selecting text and choosing a label
   - Appear as colored filled boxes with labels and delete buttons
   - Highest z-index - always visible on top

2. **AI Keyword Highlights** (Bordered overlays)
   - Click the "keyword" button to get AI-suggested keywords
   - Appear as bordered boxes matching the label color
   - AI identifies sentiment-bearing words and phrases

3. **Admin Keyword Highlights** (Bordered overlays, dashed)
   - Pre-defined keywords from `data/keywords.tsv`
   - Always visible when the page loads
   - Help guide annotators to relevant content

## Z-Index Layering

The overlays are layered so they don't obscure each other:
- Admin keywords: z-index 100 (bottom)
- AI keywords: z-index 110 (middle)
- User spans: z-index 120 (top)
- Controls/tooltips: z-index 200-300 (always accessible)

## Prerequisites

1. Install Ollama: https://ollama.ai
2. Pull a model: `ollama pull qwen3:0.6b`
3. Ensure Ollama is running: `ollama serve`

## Running the Demo

From within this directory:
```bash
cd project-hub/simple_examples/span-ai-keywords-demo
python ../../../potato/flask_server.py start config.yaml -p 8000
```

Then open http://localhost:8000 in your browser.

## Testing the Overlays

1. **Admin Keywords**: You should see bordered boxes around words like "love", "quality", "keyboard" etc. immediately when the page loads.

2. **AI Keywords**: Click the "keyword" button next to the annotation form to have the AI suggest keywords. These will appear as bordered boxes in colors matching the labels.

3. **User Spans**: Select any text and choose a label to create your own annotation. These appear as filled colored boxes.

## Files

- `config.yaml` - Main configuration with span annotation, AI support, and keyword highlights
- `data/reviews.json` - Sample product reviews for annotation
- `data/keywords.tsv` - Admin-defined keywords with labels and schema
