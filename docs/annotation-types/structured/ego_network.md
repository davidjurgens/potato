# Ego networks

`ego_network` collects a personal (egocentric) network. The respondent, the
ego, names people (alters), answers questions about each of them, says which
of them know each other, and places them on a map. The same scheme works on a
survey page, which is how most personal-network studies run it, and on
annotation items, where a coder records the network a document describes.

One scheme holds an ordered list of stages. Every stage works on the same set
of alters, so a person named in the first name generator appears in every
later stage.

| Stage | What the respondent does |
|---|---|
| `name_generator` | Types names in answer to a prompt, or picks them from a list |
| `name_interpreter` | Answers the same questions about each person (radio, multiselect, number, text) |
| `dyad_census` | Says, for every pair of people, whether they know each other: n(n-1)/2 pairs, one at a time, with a progress bar |
| `sociogram` | Drags people around a canvas and clicks two people to add or remove a line between them |

By default the stages are shown one at a time, with their own Back and Next
buttons and a row of step buttons. `stage_layout: stacked` shows them all on
the page at once.

## Configuration

On a survey page (`surveys/your-network.json`, listed under `phases`):

```yaml
phases:
  order: [your_network, annotation]
  your_network:
    type: prestudy
    file: surveys/your-network.json
  annotation:
    type: annotation
```

The page file holds the scheme, shown here in YAML; the same keys work in
`annotation_schemes`:

```yaml
- annotation_type: ego_network
  name: personal_network
  description: People you talk to
  label_requirement:
    required: true
  stages:
    - type: name_generator
      id: discuss
      title: Important matters
      prompt: >-
        Looking back over the last six months, who are the people you talked
        to about matters that are important to you?
      min_alters: 1
      max_alters: 8
      sets: {discuss: true}
    - type: name_generator
      id: help
      title: Practical help
      prompt: Who would you ask for help if you were ill for a couple of weeks?
      sets: {help: true}
    - type: name_interpreter
      id: about
      title: About each person
      required: true
      questions:
        - name: closeness
          type: radio
          description: How close do you feel to {name}?
          labels:
            - {name: very, text: Very close}
            - {name: somewhat, text: Somewhat close}
            - {name: not, text: Not close}
        - name: years_known
          type: number
          description: About how many years have you known {name}?
          min: 0
          max: 100
          required: false
    - type: dyad_census
      id: know
      prompt: Do {a} and {b} know each other?
    - type: sociogram
      id: map
      rings: 3
```

### Scheme options

| Option | Type | Default | Description |
|---|---|---|---|
| `stages` | list | required | The stages, in order. A `name_generator` must come before any other stage. |
| `stage_layout` | `steps` or `stacked` | `steps` | One stage at a time, or all of them at once. (`layout` is the grid-placement mapping every scheme accepts, so it is not used for this.) |
| `label_requirement` | mapping | none | `{required: true}` makes the page refuse to continue until the network is complete (see [Completeness](#completeness)). |

### Options for every stage

| Option | Type | Default | Description |
|---|---|---|---|
| `type` | string | required | `name_generator`, `name_interpreter`, `dyad_census` or `sociogram` |
| `id` | string | `<type>_<n>` | Stage id: a letter, then letters, digits, `_` or `-`. Recorded in `named_in` for name generators. |
| `title` | string | per type | Shown on the step button and as the stage heading |
| `prompt` | string | per type | The question or instruction for the stage |
| `instructions` | string | none | A paragraph above the prompt |

### `name_generator`

| Option | Type | Default | Description |
|---|---|---|---|
| `min_alters` | integer | `0` | People this stage needs before the respondent can go on |
| `max_alters` | integer | none | Most people this stage accepts |
| `roster` | list | none | Names to pick from instead of typing: strings, or `{id, name}` |
| `roster_field` | string | none | An item field holding the list (annotation items only) |
| `sets` | mapping | none | Attributes given to everyone named in this stage, such as `{support: true}` |
| `placeholder` | string | `First name or nickname` | Placeholder of the name box |

Typing a name already on the list is refused with a message, so one person is
not recorded twice. A later name generator lists the people named earlier
under "Named earlier", and the respondent adds anyone who also belongs there
with one click. The alter keeps one id and records every generator that
named them. Removing a person from the only generator that named them removes
them from the network, with their answers and ties.

### `name_interpreter`

| Option | Type | Default | Description |
|---|---|---|---|
| `questions` | list | required | The questions asked about each person |
| `required` | boolean | `false` | Default `required` for this stage's questions |

Each question has `name` (unique across the scheme), `type` (`radio`,
`multiselect`, `number` or `text`), `description` (`{name}` is replaced by
the person's name), `labels` for radio and multiselect (strings or
`{name, text}`; `name` is what is stored), `required`, and `min`, `max`,
`step` for numbers. The page shows one card per person with every question
on it.

### `dyad_census`

| Option | Type | Default | Description |
|---|---|---|---|
| `prompt` | string | `Do {a} and {b} know each other?` | `{a}` and `{b}` are replaced by the two names |
| `relation` | string | none | Name of the relation, when a study records more than one kind of tie |
| `yes_label`, `no_label` | string | `Yes`, `No` | Answer labels |
| `strength_labels` | list | none | Ask how strong the tie is instead of yes: one button per label, plus `no_label` |
| `strength_variable` | string | `strength` | Tie attribute the strength answer is stored under |

The census shows one pair at a time and moves to the next unanswered pair
after each answer. "All pairs" lists every pair with its answer; clicking one
goes back to it.

### `sociogram`

| Option | Type | Default | Description |
|---|---|---|---|
| `relation` | string | none | The relation the lines record |
| `allow_ties` | boolean | `true` | `false` for a placement-only canvas |
| `rings` | integer, 0 to 6 | `3` | Concentric circles drawn behind the people |

Positions are saved as fractions of the canvas width and height (0 to 1).
A line drawn on the sociogram and a census answer for the same relation are
the same record: drawing a line between two people sets their census answer
to yes, and removing it sets it to no.

## Controls

- **Name generator**: type a name and press Enter or click Add. The × on a
  name removes it.
- **Name interpreter**: click an answer. Number and text answers save after
  a short pause.
- **Dyad census**: click an answer; Previous pair and Next pair move without
  answering.
- **Sociogram**: drag a person to move them. Click one person, then another,
  to add a line between them, or to remove the line if there is one.
- **Keyboard**: every control is a button or a text box reachable with Tab.
  On the sociogram, Tab moves between people, Enter selects one and opens a
  list of everyone else to add or remove ties, arrow keys move the focused
  person (Shift moves further), and Escape closes the list. Arrow keys inside
  the widget do not move to the next item.

## Data format

The answer is stored as one JSON string:

```json
{
  "alters": [{"id": "a1", "name": "Ann", "named_in": ["discuss", "help"]},
             {"id": "a2", "name": "Bob", "named_in": ["discuss"]}],
  "attributes": {"a1": {"discuss": true, "help": true, "closeness": "very"}},
  "ties": [["a1", "a2"]],
  "positions": {"a1": [0.42, 0.31], "a2": [0.7, 0.55]},
  "census": {"a1|a2": true},
  "tie_attributes": {}
}
```

Alter ids are `a1`, `a2`, ... in the order people were named; a deleted id is
not reused. A tie is `[a, b]`, or `[a, b, relation]` when the stage names a
relation. Census and tie-attribute keys are `"a|b"` or `"a|b|relation"`.

## Export

```bash
python -m potato.export --config config.yaml --format ego_network --output out/
```

| File | Contents |
|---|---|
| `egos.csv` | One row per network (participant and item, or participant and survey page): `network_size`, `n_ties`, `possible_ties` (n(n-1)/2), `density` (ties / possible ties), `isolates`, `components`, `relations`, and `complete` with `incomplete_reason` checked against the scheme's own rules |
| `alters.csv` | One row per alter: `alter_id`, `named_in`, `x`, `y`, `degree`, and one `attr_<name>` column per attribute (multiselect answers joined with `\|`) |
| `edges.csv` | One row per tie: `source_alter`, `target_alter`, `relation` (`tie` when unnamed), and `tie_<name>` columns such as `tie_strength` |
| `graphml/<user>__<item>.graphml` | One GraphML file per network: alters as nodes with their attributes as node data, ties as undirected edges |

The ego is not a node in these files. Density, components and degree are
computed over alter-alter ties; two people tied on two relations count as
one connected pair.

### Alter names

The names respondents type identify people who have not agreed to take part
in the study. The `ego_network` export leaves them out and writes the
pseudonymous ids only. To include them:

```bash
python -m potato.export --config config.yaml --format ego_network --output out/ \
    --option export_names=true
```

The names are still in the raw output (`annotation_output/`) and in the
general exports (`csv`, `jsonl`, ...), which write the stored JSON as it is.
Ask respondents for first names or nicknames, and handle those files as
identifiable data.

## Completeness

With `label_requirement: {required: true}` the page will not continue while
any of these is true, and says which:

- a name generator has fewer than `min_alters` people;
- a required name interpreter question is unanswered for someone;
- a dyad census has unanswered pairs.

Inside the widget, Next stays on a name generator until it has `min_alters`
people, whether or not the scheme is required.

## Example

`examples/advanced/ego-network/` runs the scheme twice: as a survey page
before the task (the participant's own network), and as the annotation task
(coders record the network each interview excerpt describes).

```bash
python potato/flask_server.py start examples/advanced/ego-network/config.yaml -p 8000
```

## Troubleshooting

- **"`layout` is the grid-placement mapping..."**: write `stage_layout: stacked`,
  not `layout: stacked`.
- **"comes before any name_generator stage"**: put a name generator first.
- **"name ... is used by another question"**: answers are stored per person
  by question name, so every question in the scheme needs its own name.
- **A label list of `[Yes, No]` is refused**: YAML reads unquoted Yes and No as
  true and false. Quote them.
- **The roster is empty on an item**: `roster_field` names an item field that
  holds a list of names (or `{id, name}` objects). The page falls back to typed
  names when the field is missing.

## Related

- [Coming from Network Canvas](../../guides/coming-from-network-canvas.md)
- [Export formats](../../data-export/export_formats.md)
- [Conditional logic](../../configuration/conditional_logic.md)
