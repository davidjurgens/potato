# ConvoKit

[ConvoKit](https://convokit.cornell.edu/) is Cornell's toolkit for conversational
analysis: forty-odd downloadable corpora (Conversations Gone Awry, Switchboard,
Wikipedia Politeness, Supreme Court, Friends, Reddit, CANDOR) and a library of
transformers — politeness strategies, prompt types, coordination, forecasting —
that work by *adding metadata* to utterances, conversations, and speakers.

ConvoKit analyzes conversations. It has no annotation interface. Potato has one.
This integration joins them in both directions:

```
ConvoKit corpus  ──▶  potato convokit  ──▶  Potato task  ──▶  export  ──▶  ConvoKit metadata
```

Annotations come back keyed by **real ConvoKit utterance ids**, so they drop
straight into an existing corpus and feed the transformers you already use.

!!! note "No `convokit` dependency"
    Potato reads and writes the corpus format directly with the standard library.
    You do **not** need the `convokit` package installed. (It pulls in spacy,
    torch, scikit-learn, and pymongo; Potato's startup path deliberately stays
    clear of the ML stack.) If you do have it installed, Potato shares its cache
    directory, so neither tool downloads a corpus the other already has.

---

## Quick start

```bash
# 1. Import a corpus (downloads and caches it on first run)
potato convokit conversations-gone-awry-corpus -o data/awry.jsonl

# 2. Annotate
potato start config.yaml -p 8000

# 3. Export annotations back into ConvoKit metadata
python -m potato.export --config config.yaml --format convokit -o out/
```

To see what a corpus contains before committing to it:

```bash
potato convokit conversations-gone-awry-corpus --dry-run
```

```text
corpus:         conversations-gone-awry-corpus (version 6)
key format:     modern
read:           30021 utterances, 4188 conversations, 8069 speakers
items:          4188 (conversation unit), 30021 turns total
max reply depth: 12
dropped meta:   parsed
dangling reply-to: 1204 (treated as thread roots)
```

`--dry-run` is also the quickest answer to "why is my thread flat" — if
`max reply depth` is 0, the corpus has no `reply-to` structure to render.

---

## Getting a corpus

Pass a corpus **name**, a **directory**, or a **`.zip`**:

```bash
potato convokit friends-corpus -o data/friends.jsonl          # downloaded
potato convokit ~/corpora/my-corpus -o data/mine.jsonl        # local directory
potato convokit ./exported-corpus.zip -o data/mine.jsonl      # archive
```

A path that exists on disk always wins over a manifest name, so a local directory
is never shadowed by a download.

List everything available:

```bash
potato convokit --list-corpora
```

### Where corpora are cached

In order of precedence:

1. `--data-dir`
2. `$CONVOKIT_DATA_DIR`
3. `data_directory` in `~/.convokit/config.yml` (ConvoKit's own setting)
4. `~/.convokit/saved-corpora`

### Dynamically-named corpora are not supported

`subreddit-<name>`, `wikiconv-<lang>-<year>`, and `supreme-<year>` have URLs that
ConvoKit computes from sharded index files rather than listing in its manifest.
Potato does not reimplement that. Fetch them with ConvoKit and point Potato at the
result:

```python
from convokit import download
print(download("subreddit-Cornell"))   # prints the extracted path
```

```bash
potato convokit /path/to/subreddit-Cornell -o data/cornell.jsonl
```

### Security notes

Downloads are forced to HTTPS, restricted to Cornell's corpus host and GitHub,
size-capped (`--max-download-bytes`), and streamed to a temporary file that is
renamed only on success. Archives are checked for path traversal, absolute member
paths, symlinks, and zip bombs before extraction.

ConvoKit publishes no checksums, so a download cannot be integrity-verified beyond
HTTPS.

---

## Choosing a granularity

### `--unit conversation` (default)

One Potato item per conversation, carrying every turn. Whole-thread schemes judge
the conversation; `turn_level` schemes judge individual comments.

```bash
potato convokit conversations-gone-awry-corpus \
    --unit conversation --promote-meta split -o data/awry.jsonl
```

```json
{
  "id": "convo:146743638.12652.12652",
  "conversation": [
    {"turn_id": "146743638.12652.12652", "speaker": "Sirex98",
     "text": "== WP:COMMONNAME ==", "reply_to": null, "timestamp": 1185295934.0,
     "depth": 0, "index": 0, "meta": {"toxicity": 0.0}}
  ],
  "conversation_tree": {"id": "146743638.12652.12652", "children": [...]},
  "text": "Sirex98: == WP:COMMONNAME ==\n...",
  "convo_meta": {"page_title": "User talk:2005", "split": "train"},
  "speakers": {"Sirex98": {}},
  "split": "train",
  "_convokit": {"corpus": "conversations-gone-awry-corpus", "unit": "conversation",
                "conversation_id": "146743638.12652.12652",
                "utterance_ids": ["146743638.12652.12652", "..."]}
}
```

### `--unit utterance`

One item per utterance, with surrounding turns for context. Right for corpora
where each utterance is an independent judgement — the politeness corpora,
per-comment toxicity.

```bash
potato convokit wikipedia-politeness-corpus \
    --unit utterance --context-window 0 -o data/politeness.jsonl
```

The focus turn is flagged `is_focus: true` and named in `focus_turn_id`;
`text` is the focus utterance alone.

| Flag | Effect |
|---|---|
| `--context-window K` | K turns of preceding context (default 2) |
| `--context-after K` | K turns of following context (defaults to `--context-window`) |
| `--context-mode ancestors` | Walk the reply chain upward — correct for threaded corpora |
| `--context-mode linear` | Take chronologically adjacent turns |
| `--context-mode auto` | *(default)* Detect which of the two the corpus is |

`auto` inspects the corpus: if every `reply_to` points at the immediately
preceding utterance — as in Switchboard or the movie corpus, where the field
expresses sequence rather than threading — it uses `linear`; otherwise
`ancestors`.

---

## The `turn_id` contract

**Every turn carries the real ConvoKit utterance id as its `turn_id`.**

This is the whole basis of the round trip. Potato's
[turn-level annotation framework](../agent-evaluation/turn_level_annotation.md)
stores per-turn values keyed by `turn_id`, so a stored annotation looks like:

```json
{"v": 1, "schema_type": "multiselect",
 "turns": {"146743638.12667.12652": {"speaker": "Sirex98",
                                     "values": ["personal_attack"]}}}
```

Those keys are genuine utterance ids, so exporting them into ConvoKit metadata is
a direct lookup rather than a reconciliation against positions that may have
shifted. Nodes in the `conversation_tree` field use the same ids, so a threaded
tree view and a flat dialogue view of the same conversation annotate the same
turns.

---

## Rendering threads

ConvoKit conversations are reply-to **trees** — Wikipedia talk pages and Reddit
threads genuinely branch. Turn on threading in the display:

```yaml
instance_display:
  fields:
    - key: conversation
      type: dialogue
      label: "Thread"
      display_options:
        indent_replies: true
        show_reply_lines: true
        show_timestamps: true
        timestamp_format: absolute
        turn_meta_fields: [toxicity]     # show the corpus's own scores
```

Threading is general Potato functionality and is documented in full under
[dialogue annotation](../annotation-types/structured/dialogue_annotation.md) —
nothing about it is ConvoKit-specific, and it works on any data whose turns name
what they reply to.

---

## Metadata handling

| Kind | Default | Why |
|---|---|---|
| Ordinary metadata | kept | Rendered as per-turn chips or `convo_meta` |
| `parsed` | **dropped** | spacy dependency parses; hundreds of lines *per utterance* |
| `vectors`, `embeddings` | **dropped** | Bookkeeping with no inline value |
| Binary (`-bin.p` pickles) | **skipped** | Unpickling downloaded data executes arbitrary code |
| `info.<field>.jsonl` | **not loaded** | Opt in with `--load-info` |

```bash
potato convokit wikipedia-politeness-corpus --keep-meta parsed        # keep it
potato convokit wikipedia-politeness-corpus --load-binary-meta        # unpickle
potato convokit conversations-gone-awry-corpus --load-info my_scores  # overlay
```

!!! warning "`--load-binary-meta` unpickles data you downloaded"
    `pickle.load` on a file fetched from the internet executes arbitrary code.
    The flag exists because some corpora keep genuinely useful annotations there
    — `wikipedia-politeness-corpus` stores its per-annotator ratings as a binary
    field — but only use it on a corpus you trust.

Everything dropped or skipped is reported by `--dry-run`, recorded in each item's
`_convokit` provenance, and repeated in the header of a generated config. An
import is never quietly lossy.

### Promoting metadata to item fields

`--promote-meta` lifts scalar metadata to top-level item keys, where
`item_properties`, filters, and keyword highlighting can reach it:

```bash
potato convokit conversations-gone-awry-corpus --promote-meta split,page_title
```

### Filtering

```bash
potato convokit conversations-gone-awry-corpus --split train
potato convokit conversations-gone-awry-corpus --filter convo.verified=true
potato convokit switchboard-corpus --filter utt.tag=sd
potato convokit reddit-corpus-small --max-conversations 500 --sample 100 --seed 7
```

---

## Generating a starter config

```bash
potato convokit conversations-gone-awry-corpus \
    -o data/awry.jsonl --emit-config config.yaml
```

The generated schemes mirror metadata the corpus already carries — a good
starting point for re-annotation, adjudication, or an agreement study, and
explicitly *not* a finished task. Conversation metadata becomes instance-level
schemes; utterance metadata becomes `turn_level` schemes bound to the dialogue
field.

Field shapes come from **sampling real values**, not from `index.json`, because
that index is unreliable: in `conversations-gone-awry-corpus` the field
`toxicity` is typed `<class 'int'>` while its values are floats like `0.078`.

| Observed values | Suggested scheme |
|---|---|
| booleans | `radio` (true/false) |
| ≤5 distinct strings | `radio` |
| 6–12 distinct strings | `select` |
| >12 distinct strings | skipped, with a comment giving the count |
| numbers | `slider` over the observed range |
| nested / binary | skipped, with a comment saying why |

---

## Exporting back to ConvoKit

```bash
python -m potato.export --config config.yaml --format convokit -o out/
```

### Overlay mode (default)

Writes `info.<field>.jsonl` files that drop into an existing corpus directory:

```json
{"id": "146743638.12667.12652", "value": ["personal_attack"]}
```

```python
from convokit import Corpus, download
corpus = Corpus(filename=download("conversations-gone-awry-corpus"))
corpus.load_info("utterance", ["potato_turn_problems"])
```

Nothing about the original corpus is rewritten.

### Corpus mode

```bash
python -m potato.export --config config.yaml --format convokit \
    --options '{"mode": "corpus"}' -o out/
```

Writes a complete corpus directory — `utterances.jsonl`, `speakers.json`,
`conversations.json`, `corpus.json`, `index.json` — with annotations merged into
metadata. Binary metadata skipped on import is never re-emitted; the fields
involved are recorded in `corpus.json` so the export is not mistaken for a
faithful copy.

### Where annotations land

| Potato | ConvoKit |
|---|---|
| Instance scheme, `--unit conversation` | Conversation metadata |
| Instance scheme, `--unit utterance` | Utterance metadata |
| `turn_level` scheme | Utterance metadata, keyed by `turn_id` |
| Span annotation | Utterance metadata, split per utterance |

Multiple annotators are preserved in every mode. By default
`potato_<scheme>` is `{user_id: value}` — what an agreement study wants — with an
aggregate available via the `aggregate` option, which moves the per-annotator
dict to `potato_<scheme>_raw` rather than discarding it.

Field names are prefixed `potato_` (not `potato.`) because ConvoKit's MongoDB
backend rejects `.` in document keys.

---

## Format compatibility

Potato reads every variant of the corpus format found in the wild:

| Variation | Handling |
|---|---|
| `reply-to` (hyphen, what dumps write) | Accepted |
| `reply_to` (underscore, Reddit-derived corpora) | Accepted |
| `user` / `root` / `users.json` (pre-rename corpora) | Detected and mapped |
| `index.json` values as strings *or* lists | Normalized |
| `{"meta": ..., "vectors": ...}` *or* bare metadata dicts | Both unwrapped |
| Missing `speakers.json` / `index.json` / `corpus.json` | Tolerated, with a warning |
| Dangling `reply_to`, reply cycles, duplicate ids | Repaired, counted, reported |

`wikipedia-politeness-corpus` is still shipped in the pre-rename format and is
used as a test fixture precisely for that reason.

---

## Limitations

| Limitation | Detail |
|---|---|
| Memory | `utterances.jsonl` streams, but `conversations.json` and `speakers.json` must be parsed whole. `reddit-corpus` will not fit comfortably. `--max-conversations` bounds item generation, not that load. |
| Vectors | `vect_info.*.npy` is never read or written. |
| Dynamic corpus names | Not supported; see above. |
| Speaker-level annotation | Speaker metadata is read-only context; Potato annotates conversations and utterances. |
| Checksums | Not published upstream; downloads are HTTPS-only but not verified. |

---

## Related

- [Dialogue annotation](../annotation-types/structured/dialogue_annotation.md) — the threaded display in full
- [Conversation tree annotation](../annotation-types/structured/conversation_tree_annotation.md) — the branching view
- [Turn-level annotation](../agent-evaluation/turn_level_annotation.md) — per-comment schemes
- [Export formats](../data-export/export_formats.md) — the `convokit` exporter
- Examples: `examples/conversation/convokit-awry/`, `examples/conversation/threaded-forum/`
