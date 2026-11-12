# Conversations Gone Awry (ConvoKit)

Annotate Wikipedia talk-page threads for derailment — the task behind Cornell's
[Conversations Gone Awry](https://convokit.cornell.edu/documentation/awry.html)
corpus (Zhang et al., ACL 2018).

## Get the data

The corpus is downloaded on demand rather than committed:

```bash
./setup_data.sh
```

Equivalently, from the repository root:

```bash
potato convokit conversations-gone-awry-corpus \
    --unit conversation --max-conversations 200 \
    --promote-meta split,page_title \
    -o examples/conversation/convokit-awry/data/awry.jsonl
```

## Run

```bash
python potato/flask_server.py start examples/conversation/convokit-awry/config.yaml -p 8000
```

## Export the annotations back to ConvoKit

```bash
python -m potato.export --config examples/conversation/convokit-awry/config.yaml \
    --format convokit -o /tmp/awry-annotations
```

That writes `info.<field>.jsonl` overlays keyed by real ConvoKit ids:

```json
{"id": "146743638.12667.12652", "value": {"alice": ["personal_attack"]}}
```

Copy them into the corpus directory and load them:

```python
from convokit import Corpus, download
corpus = Corpus(filename=download("conversations-gone-awry-corpus"))
corpus.load_info("utterance", ["potato_turn_problems"])
```

## What it demonstrates

- A ConvoKit corpus imported straight into a Potato task.
- Reply threading: Wikipedia talk pages branch, and the display indents by depth.
- The corpus's own `toxicity` scores shown as per-turn chips, so the annotator
  sees the automatic signal while making a human judgement.
- Per-comment annotation keyed by **real ConvoKit utterance ids**, which is what
  lets `python -m potato.export --format convokit` write the results back into
  utterance metadata.

See [docs/integrations/convokit.md](../../../docs/integrations/convokit.md).
