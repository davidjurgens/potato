# Calibrating an LLM judge on agent traces

The labeling engine as a judge-calibration loop. An LLM judge decides whether
each of 288 agent runs succeeded. People label a blind random sample, half
of it three times each, and the engine checks the judge against them.

- **Source:** a `judge` (Ollama `llama3.1:8b`) that applies a rubric to the
  task, the trace and the final answer, and asks twice with the label order
  swapped. A verdict that flips with the order goes to a person.
- **Contracts:** at most 15% of accepted verdicts wrong (`selective_risk`);
  the judge agrees with people at least as well as a person does, up to
  0.15 (`no_worse_than_human`); and the success rate, with an interval
  (`ppi`).

## Run it

```bash
ollama serve && ollama pull llama3.1:8b

potato label run examples/labeling-engine/agent-trace-judge/config.yaml
python potato/flask_server.py start examples/labeling-engine/agent-trace-judge/config.yaml -p 8000
potato label certify examples/labeling-engine/agent-trace-judge/config.yaml
```

The no-worse-than-human test needs at least three people on each overlap
item, with 30 or more items each.

## Files

- `config.yaml`: the study
- `data/agent-traces.jsonl`: synthetic traces written by an LLM for this
  example, each with a reference outcome used only to check the results

## Results from a test run

These numbers come from a run with the `judge` source pointed at Gemma 12B
on a vLLM server, not the Ollama model in `config.yaml`:

```yaml
    - id: judge
      kind: judge
      endpoint_type: vllm
      model: google/gemma-4-12B-it-qat-w4a16-ct
      base_url: http://localhost:8001/v1
```

The rest of the source (`max_tokens`, `options`) is unchanged. With
`llama3.1:8b` the numbers will differ. With Gemma 12B as the judge, it was right on 80% of traces but gave confidence
1.0 to every verdict, so no threshold could be certified and every
trace went to people. The alternative annotator test was insufficient: the
judge scored 0.82 against the people's 0.93, and there were not yet enough
labels to decide. The engine's success-rate interval,
0.66 [0.57, 0.76], covered the reference value of 0.60; the judge alone
reported 0.76.

See [the labeling engine docs](../../../docs/labeling-engine/overview.md).
