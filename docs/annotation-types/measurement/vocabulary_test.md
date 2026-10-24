# Vocabulary Tests (LexTALE)

A lexical decision vocabulary test, such as LexTALE (Lemhöfer & Broersma
2012), asks whether each letter string is a real word. It is a quick check
of proficiency before a study in a second language.

Potato runs it as a radio question with a `lextale` block, and scores it in
the export. The item lists are not included: get them from the test's
authors and use them under their terms.

```yaml
annotation_schemes:
  - annotation_type: radio
    name: lexicality
    description: Is this an existing English word?
    labels: ["yes", "no"]
    horizontal: true
    lextale:
      answer_field: is_word
      word: "yes"
      nonword: "no"
```

```json
{"id": "v1", "text": "lantern", "is_word": "yes"}
{"id": "v2", "text": "brindop", "is_word": "no"}
```

`answer_field` names the item field that says whether the item is a word
(`yes`, `word`, `true` or `1`) or not. That field is never sent to the page.
`word` and `nonword` are the labels that mean "it is a word" and "it is not".

To show each item for a limited time, or record response times, add
[timed trials](../../workflow/timed_trials.md) with keys for the two labels.

## Export

```bash
python -m potato.export --config config.yaml --format lextale --output ./export/
```

`lextale.csv`, one row per participant: words and nonwords answered and
correct, the percentages, and the score: the average of the percentage of
words correct and the percentage of nonwords correct. The score is computed
in the export, not while the study runs, so it cannot decide which pages a
participant sees; to screen on it, export after the test and invite the
participants who qualify to the next study.

## Example

```bash
python potato/flask_server.py start examples/advanced/vocabulary-test/config.yaml -p 8000
```

The eight items in the example are made up and are not the LexTALE list.

## Related

- [Timed trials](../../workflow/timed_trials.md)
- [Self-paced reading](../../workflow/self_paced_reading.md)
