# Triad Tests

A `triad_test` scheme shows the items of a domain three at a time and asks
which one is most different. The answers give an item-by-item similarity
matrix: in a triad whose odd item is C, the other two items are judged
similar (Weller & Romney 1988).

All the triads of one scheme are answered on one item or phase page, one
triad at a time, with a progress line ("Triad 3 of 13 · 2 answered").
Choosing an item moves on to the next unanswered triad. Previous and Next
revisit any triad, and choosing again replaces the answer.

## Configuration

The domain comes from the config:

```yaml
annotation_schemes:
  - annotation_type: triad_test
    name: triads
    description: Triads
    labels: [apple, banana, cherry, grape, lemon, lime, mango]
```

or from a list in each item:

```yaml
annotation_schemes:
  - annotation_type: triad_test
    name: triads
    description: Triads
    items_field: items
```

```json
{"id": "fruit", "text": "Fruit", "items": ["apple", "banana", "cherry", "grape", "lemon", "lime", "mango", "orange", "pear"]}
```

A phase page has no item, so a triad test on a phase page needs `labels`.

### Options

| Option | Default | Description |
|---|---|---|
| `labels` | none | The domain: a list of names (or `{name: ...}` entries). Give this or `items_field` |
| `items_field` | `items` | The item field holding the domain, when `labels` is not given |
| `design` | `auto` | `auto`, `complete`, `steiner` or `sample` (see below) |
| `max_triads` | none | The most triads to ask. With `sample`, exactly this many |
| `question` | "Which is most different?" | The question above each triad |
| `instructions` | none | Text shown under the heading |
| `label_requirement` | none | `required: true` blocks Next until every triad is answered |

A domain needs at least 3 items and may have at most 60.

### Designs

| `design` | Triads | When `auto` uses it |
|---|---|---|
| `complete` | every one of the C(n, 3) triads | while there are at most 20 (n ≤ 6), and `max_triads` allows it |
| `steiner` | n(n − 1)/6 triads; every pair of items appears together in exactly one | when n is 1 or 3 mod 6 (7, 9, 13, 15, 19, 21, ...) and `max_triads` allows it |
| `sample` | `max_triads` triads, or without it, enough for every pair to appear at least once | otherwise |

`steiner` is a balanced incomplete block design with λ = 1 (a Steiner triple
system), built with Bose's construction for n = 6t + 3 and Skolem's for
n = 6t + 1. It does not exist for other n; asking for it there gives a
validation error when the domain is in `labels`, and falls back to `sample`
for an `items_field` domain.

`sample` picks triads one at a time: each step takes the unused triad whose
pairs have appeared least so far, then whose items have appeared least, with
ties broken by a seeded shuffle. Without `max_triads` it stops when every
pair has appeared once. In tests over domain sizes 4 to 30 and 30 seeds each,
no pair then appeared more than twice. The algorithm does not guarantee this. With a fixed
`max_triads`, pair counts are kept close to even but are not guaranteed
equal: they can differ by two.

| n | `auto` design | triads |
|---|---|---|
| 5 | complete | 10 |
| 6 | complete | 20 |
| 7 | steiner | 7 |
| 8 | sample | 11 |
| 9 | steiner | 12 |
| 10 | sample | 17 or 18, depending on the seed |
| 13 | steiner | 26 |

The design depends only on the domain (and the scheme name, which seeds the
sample), so every participant answers the same triads. The order of the
triads and the position of the items within each triad are shuffled per
participant, item and scheme. The shuffle is seeded, so a reload shows the
same sequence.

## Using it

- Click an item, or press 1, 2 or 3 while the triad has focus (Tab into it,
  or click once).
- "← Previous triad" and "Next triad →" move through the sequence. The bar
  shows how many triads are answered.
- When all are answered, the page says so.

## Stored data

One hidden input holds JSON:

```json
{"design": "steiner",
 "triads": [["lime", "grape", "orange", "grape"],
            ["banana", "apple", "lime", null]]}
```

Each triad lists its three items in the positions they were shown (left to
right, or top to bottom on a phone), then the item chosen as most different,
or `null` while unanswered. Once a triad test has an answer, the stored
triads are what the page shows on a later visit, so the record always says
what this participant saw.

## Export

`python -m potato.export --format cultural_domain` writes
`triads_answers.csv` (one row per answered triad) and
`triads_similarity_<scheme>[_<item>].csv`, the item-by-item matrix of
"times judged similar / times shown together". See
[Cultural domain analysis](../../guides/cultural-domain-analysis.md).

## Troubleshooting

- **"The triads for this item could not be built".** The item has no list
  under `items_field`, or the list has fewer than three different entries.
- **Fewer triads than expected.** With `auto`, a domain of 7, 9, 13, ... items
  gets a Steiner system, which asks each pair once. Set `design: complete` to
  ask every triad.
- **Keys do nothing.** The 1/2/3 keys act only while focus is inside the
  triad widget.

## Example

`examples/advanced/cultural-domain/` has a triad test on two items, nine
fruits (12 triads) and seven vegetables (7 triads):

```bash
python potato/flask_server.py start examples/advanced/cultural-domain/config.yaml -p 8000
```

## Related

- [Free lists](free_list.md)
- [Card sorting](../structured/card_sort.md) (pile sorts)
- [Cultural domain analysis](../../guides/cultural-domain-analysis.md)
