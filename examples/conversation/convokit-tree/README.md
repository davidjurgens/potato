# Two views of one conversation

A branching **tree** and a flat **thread** of the same conversation, annotated
together.

## Get the data

```bash
./setup_data.sh
```

## Run

```bash
python potato/flask_server.py start examples/conversation/convokit-tree/config.yaml -p 8000
```

## What it demonstrates

A reply tree and a reading order answer different questions, so this task shows
both and gives each its own job:

| Field | Display | Carries |
|---|---|---|
| `conversation_tree` | `conversation_tree` | `branch_role` — where the thread turns |
| `conversation` | `dialogue` | `hostility` per turn, plus `evidence` spans |

The two views agree because they share ids: the importer sets each turn's
`turn_id` **and** each tree node's `id` to the same ConvoKit utterance id, so a
label applied in either view refers to the same utterance and exports to the same
place.

The tree is deliberately not a span target — collapsing a subtree changes the
rendered text, so span offsets could not be stable. Spans live on the flat view.

A conversation with several roots (a real occurrence, when a reply points outside
the thread) is wrapped in a synthetic root node so it still renders as one tree.
That wrapper is flagged and gets no annotation widgets: it is not an utterance,
and a value stored against it could never be exported back.

See [conversation tree annotation](../../../docs/annotation-types/structured/conversation_tree_annotation.md).
