# Annotation telemetry

Records **how** a drawn annotation was produced — timing, zoom, revision, and
AI-suggestion accept latency — without recording a single coordinate.

```bash
python potato/flask_server.py start examples/advanced/annotation-telemetry/config.yaml -p 8000
```

## What to try

1. Draw a few boxes quickly without zooming.
2. Navigate to the next image, zoom in, and draw carefully — undoing once or
   twice.
3. Read the rollup:

```bash
curl -H 'X-API-Key: demo_admin_key' \
     http://localhost:8000/admin/api/annotation_process | python -m json.tool
```

The two sessions should differ in `shape_interval_median_ms`, `max_zoom`,
`zoomed_fraction` and `revision_ratio`. With enough fast shapes the first will
pick up the `hasty` flag — and, because another flag fired, `never_zoomed`
alongside it.

## The signal this exists for

The flags above are supporting context. The one that carries real weight is
**AI-accept latency**, which needs an AI endpoint configured (see
`examples/image/image-ai-detection/`). Accept a run of suggestions without
looking at them and `rubber_stamping` fires.

That is the failure no amount of geometry inspection can catch: pre-labelling
that is accepted wholesale produces a dataset that agrees with itself, and every
quality measure — including inter-annotator agreement — looks *better*, not
worse.

## What is not recorded

No coordinates, ever. There is no field in the event record a coordinate could
go in. A stream reconstructs the process; it cannot reconstruct the annotation.

## Reading the output honestly

Every flag here is a screening signal for deciding what to look at. Fast is not
the same as careless, and an annotator whose suggestions are genuinely good will
look exactly like one who never checked them — so check the suggestions before
the annotator.

Full documentation: [`docs/advanced/annotation_telemetry.md`](../../../docs/advanced/annotation_telemetry.md)
