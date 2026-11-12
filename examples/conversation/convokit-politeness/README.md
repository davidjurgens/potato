# Wikipedia Politeness (ConvoKit)

Re-annotate the Stanford Politeness Corpus — requests from Wikipedia talk pages,
originally rated by crowdworkers (Danescu-Niculescu-Mizil et al., ACL 2013).

## Get the data

```bash
./setup_data.sh
```

## Run

```bash
python potato/flask_server.py start examples/conversation/convokit-politeness/config.yaml -p 8000
```

## What it demonstrates

- **The legacy ConvoKit format, end to end.** This corpus still ships with
  `user` instead of `speaker`, `root` instead of `conversation_id`, `users.json`
  instead of `speakers.json`, and an `index.json` whose types are bare strings.
  Potato detects and maps all of it — nothing in `config.yaml` mentions it.
- **Utterance-level items.** Each request is an independent judgement, so items
  are built with `--unit utterance --context-window 0`. Annotations export back
  onto the utterance rather than a conversation.
- **Binary metadata being skipped safely.** The corpus keeps its per-annotator
  ratings in a pickle sidecar. Potato does not unpickle downloaded data by
  default; the field shows as `null` and the omission is reported by `--dry-run`
  and recorded in each item's provenance. `--load-binary-meta` opts in.
- **Adjudication rather than annotation from scratch** — the corpus's own label
  is promoted to `Binary` and shown alongside, and a scheme asks whether you
  agree with it.

See [docs/integrations/convokit.md](../../../docs/integrations/convokit.md).
