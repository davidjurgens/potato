# Solo Mode + Codebook Example

This is the one example that turns on **both** halves of the workflow at
once, so you can see them interact:

- **Solo Mode** — an LLM labels each instance in parallel with you.
- **The universal codebook** — the scheme's labels come from the mutable
  project codebook, and each code's structured fields (definition /
  clarification / negative clarification / worked examples) are injected
  into the prompt the LLM is given.

The point of the demo: **edit the codebook and watch the LLM's prompt change.**

## Prerequisites

Ollama, running, with the small model pulled:

```bash
ollama serve            # in one terminal
ollama pull llama3.2:3b
```

## Run

```bash
python potato/flask_server.py start \
  examples/advanced/solo-codebook-example/config.yaml -p 8000
```

Open `http://localhost:8000`, sign in, and walk through Setup → Prompt →
(optionally Edge Cases) → **Annotate**.

## What to try on the Annotate screen

1. **See the LLM label alongside you.** Each instance shows "The LLM
   suggests …" with its confidence and reasoning. You pick your own label;
   disagreements get routed to the resolution screen.

2. **See the prompt the LLM actually gets.** Expand the **"Prompt the LLM
   sees"** panel under the label buttons. It shows the *exact* prompt the
   labeling thread builds — your base prompt **plus** a `## Codebook` block
   rendered from the codebook's structured fields. The badge shows the
   codebook revision the prompt reflects.

3. **Change the codebook and watch the prompt change.** Open the
   **Codebook** tray (button on the right edge). Rename a code, recolor it,
   or — most visibly — change a code's definition/example via the API:

   ```bash
   # find the code id
   curl localhost:8000/api/codebook
   # edit its definition (privileged/open mode)
   curl -X PATCH localhost:8000/api/codebook/<code_id> \
     -H 'Content-Type: application/json' \
     -d '{"definition": "A NEW definition the model will now be told"}'
   ```

   Back on the Annotate screen, hit **Refresh** in the prompt panel: the
   `## Codebook` block now shows your edit and the **revision badge ticks
   up**. The next LLM label for that instance uses the new prompt.

## Where it's stored

- The codebook, its change log, and the revision counter live in
  `project.sqlite` (tables `codes`, `codebook_change`, `codebook_revision`).
- Your answers + the LLM's labels live under `annotations/` and the solo
  state under `solo_state/`.

Inspect the codebook changing as you edit:

```bash
cd examples/advanced/solo-codebook-example
sqlite3 -header -column project.sqlite \
  "SELECT op, actor_kind, new_value, revision FROM codebook_change ORDER BY created_at DESC LIMIT 8"
```

See also the [codebook example](../codebook-example/README.md) (codebook
without an LLM) and the [solo-mode example](../solo-mode/) (LLM without a
codebook).
