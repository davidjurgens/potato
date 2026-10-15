# Image boxes and a has-person label

The labeling engine on 128 COCO images, with two schemes: boxes around
people, vehicles and animals (`image_annotation`), and whether the image
shows a person (`radio`).

- **Sources:** YOLOv8n for the boxes, and a local vision model (Ollama
  `llava:7b`) for the yes/no question.
- **Contracts:** at most 20% of accepted box sets wrong, where a box set is
  wrong when its matched-IoU distance from a person's exceeds 0.5 (the
  measure the agreement report uses); at most 10% of accepted has-person
  labels wrong; and the share of images with a person, with an interval.

## Run it

```bash
pip install ultralytics
ollama serve && ollama pull llava:7b

potato label run examples/labeling-engine/image-objects-and-people/config.yaml
python potato/flask_server.py start examples/labeling-engine/image-objects-and-people/config.yaml -p 8000
potato label status examples/labeling-engine/image-objects-and-people/config.yaml
```

The first run downloads the YOLOv8n weights (about 6 MB) into this directory.
Images load from cocodataset.org, so the browser and the engine need network
access. That host sends no CORS headers, so the page loads the images without
them: drawing works, region fill and SAM do not (see
[image annotation](../../../docs/annotation-types/multimedia/image_annotation.md)).

## Files

- `config.yaml`: the study
- `data/coco128-objects.jsonl`: image URLs and COCO's boxes (CC BY 4.0),
  grouped into person, vehicle and animal. The boxes are used only to check
  the engine's results.

## Results from a test run

These numbers come from a run with the `vision` source pointed at Gemma 12B
on a vLLM server, not the Ollama model in `config.yaml`:

```yaml
    - id: vision
      kind: vlm
      endpoint_type: openai_vision
      model: google/gemma-4-12B-it-qat-w4a16-ct
      base_url: http://localhost:8001/v1
      schemas: [has_person]
      max_tokens: 200
```

With `llava:7b` the has-person numbers will differ; the YOLOv8n box results
do not depend on it. With Gemma 12B as the vision model, the has-person
contract
was met at 10%. The box contract was not:
YOLOv8n's boxes were wrong on 32% of the dev images at IoU 0.5 (judged
against the dev labels), so the contract stayed insufficient and the engine
sent the boxes to people. A larger detector, or
distillation once people have labeled a few hundred images, is the next step.

See [the labeling engine docs](../../../docs/labeling-engine/overview.md).
