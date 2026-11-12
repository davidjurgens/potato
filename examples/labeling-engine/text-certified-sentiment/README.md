# Certified sentiment labels

The labeling engine on a text classification study: 481 product reviews,
labeled positive, negative or neutral.

- **Sources:** Laya, a decision model that scores all three labels in one
  forward pass, then a local LLM (Ollama `llama3.2:3b`). The LLM labels every
  item until the dev labels fix a threshold for Laya, and after that only the
  items Laya is not sure enough about. With the 400-label budget the Laya
  threshold may never be fixed (in our run with Gemma 12B it was not, and
  the LLM delivered all the accepted labels); `potato label status` says how
  many more labels it needs.
- **Contracts:** at most 10% of accepted machine labels wrong, with
  probability 0.9 (`selective_risk`), and each label's prevalence with an
  interval corrected for the machines' errors (`ppi`).
- **People:** a blind random sample of about a third of the reviews, then
  whatever the machines could not label. At most 400 human requests.

## Run it

```bash
pip install 'potato-annotation[decision]'     # Laya
ollama serve && ollama pull llama3.2:3b

# Label everything and draw the blind sample
potato label run examples/labeling-engine/text-certified-sentiment/config.yaml

# Serve the sample to people
python potato/flask_server.py start examples/labeling-engine/text-certified-sentiment/config.yaml -p 8000

# Once the sample is labeled
potato label status examples/labeling-engine/text-certified-sentiment/config.yaml
potato label certificate examples/labeling-engine/text-certified-sentiment/config.yaml
potato label export examples/labeling-engine/text-certified-sentiment/config.yaml
```

The admin dashboard links to the engine's page (`/admin/labeling-engine`),
which shows the contracts, the error-against-coverage curve and the
calibration of each source.

Any OpenAI-compatible server can replace Ollama: set the `llm` source to
`endpoint_type: vllm` with your `base_url`, and `confidence: {method: logprob}`
if the server returns log probabilities. The engine can also use a Jev or
OpenJev server as a decision model: `kind: decision`,
`endpoint_type: systemone`, `base_url` pointing at the server.

## Files

- `config.yaml`: the study
- `data/reviews.jsonl`: the reviews, each with a `gold` label used only to
  check the engine's results (the engine never reads it)

## Results from a test run

These numbers come from a run with the `llm` source pointed at Gemma 12B on
a vLLM server, not the Ollama model in `config.yaml`:

```yaml
    - id: llm
      kind: llm
      endpoint_type: vllm
      model: google/gemma-4-12B-it-qat-w4a16-ct
      base_url: http://localhost:8001/v1
      max_tokens: 200
      confidence:
        method: logprob
```

With `llama3.2:3b` and verbalized confidence the numbers will differ. On
this corpus, with Gemma 12B (logprob confidence) as the last tier, the
accuracy contract was met on 165 human labels and 316 machine labels were
accepted; their error against the gold labels was 7.6%. The prevalence
intervals covered the gold prevalence of every label.

See [the labeling engine docs](../../../docs/labeling-engine/overview.md).
