# Free Lists

A `free_list` scheme asks one question, such as "List all the kinds of fruit
you can think of", and the participant answers by typing items one at a time.
Enter (or the Add button) adds the item to the end of the list. Free listing
is the usual first step in a cultural domain analysis (Weller & Romney 1988):
the items people name, and how early they name them, show what belongs to the
domain and which items are most salient.

The list keeps the order the items were given in. There is no way to reorder
it, because the order is part of the data. An item can be deleted, and the
deletion undone; the item goes back to the same place with its original time.

A free list works on annotation items and on survey phase pages (consent,
prestudy, poststudy).

## Configuration

```yaml
annotation_schemes:
  - annotation_type: free_list
    name: fruit_freelist
    description: List all the kinds of fruit you can think of.
    instructions: >-
      Type one kind of fruit, then press Enter. Keep going until you cannot
      think of any more.
    min_items: 3
    max_items: 60
    normalize: true
    label_requirement:
      required: true
```

On a phase page, put the same entry in the phase's question file:

```yaml
phases:
  order: [freelist, annotation]
  freelist:
    type: prestudy
    file: surveys/freelist.yaml
```

### Options

| Option | Default | Description |
|---|---|---|
| `description` | (required) | The prompt, shown as the question heading |
| `instructions` | none | Text shown under the prompt |
| `min_items` | none | The list is incomplete until it has this many items |
| `max_items` | none | The entry box is disabled once the list has this many items |
| `time_limit_s` | none | A countdown in seconds. The participant presses Start; when the time runs out the list is locked |
| `allow_duplicates` | `false` | When false, an item that is already on the list (ignoring case and spaces) is refused with a message |
| `normalize` | `false` | `true`, or a list of `lowercase` and `trim`. Applied by the `cultural_domain` export, never to what is stored |
| `placeholder` | "Type an item, then press Enter" | Placeholder text in the entry box |
| `label_requirement` | none | `required: true` blocks Next until the list is complete |

A list is complete when it has at least one item (or `min_items` items). A
timed list is complete once its time is up, however many items it has; before
Start it is incomplete.

### Timing

`timings_ms[i]` is the time from the start of the list to the moment item `i`
was added. An untimed list starts on the first focus of the entry box. A timed
list starts with the Start button, and the entry box is disabled until then.

The clock runs only while the page is showing. When the participant moves to
another item, or the browser tab is hidden, it stops; on coming back it
resumes from the saved `elapsed_ms`. A timed list saves its elapsed time every
five seconds, so leaving the page does not give back more than that.

## Using it

- Type an item and press Enter, or press Add.
- The × button on an item deletes it. "Undo delete" puts back the most
  recently deleted item; pressing it again restores the one before.
- With a time limit, the remaining time is shown next to the Start button and
  turns red in the last ten seconds. When it reaches 0:00 the list is saved
  and cannot be changed.

## Stored data

One hidden input holds JSON:

```json
{"items": ["apple", "banana", "mango"],
 "timings_ms": [2140, 5310, 9870],
 "elapsed_ms": 12020,
 "time_up": false,
 "started": true}
```

`items` is what the participant typed, with runs of spaces collapsed and the
ends trimmed. Case is kept.

## Export

`python -m potato.export --format cultural_domain` writes
`freelist_items.csv` (one row per item: user, normalized item, what was typed,
rank, list length, time) and `salience.csv` (per item: frequency, percentage
of informants, mean rank, Smith's S and Sutrop's cognitive salience index).
Normalization and a synonym table are applied before counting. See
[Cultural domain analysis](../../guides/cultural-domain-analysis.md).

The page enforces `max_items` and a 200-character limit per item, but the
server stores the list as it was sent. The export uses at most `max_items`
items of a list (300 when `max_items` is not set) and the first 200
characters of each item, and it warns about every list it cut.

## Troubleshooting

- **Next stays disabled.** The scheme is required and the list has fewer
  than `min_items` items, or a timed list has not been started.
- **"Already on your list".** The item matches one on the list after
  lowercasing and collapsing spaces. Set `allow_duplicates: true` to accept
  repeats; the export still counts an item once per list.
- **Items differ only by case or plural in the export.** Set `normalize:
  true` on the scheme (or `--option normalize=true`) and give a synonyms file
  for plurals and spelling variants.

## Example

`examples/advanced/cultural-domain/` has a free list on a prestudy page:

```bash
python potato/flask_server.py start examples/advanced/cultural-domain/config.yaml -p 8000
```

## Related

- [Triad tests](triad_test.md)
- [Card sorting](../structured/card_sort.md) (pile sorts)
- [Cultural domain analysis](../../guides/cultural-domain-analysis.md)
