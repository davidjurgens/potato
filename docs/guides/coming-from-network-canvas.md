# Coming from Network Canvas

Potato reads a Network Canvas protocol and turns it into survey pages. Ego
forms become pages of ordinary questions, and the network stages (name
generators, alter forms, bins, censuses, sociograms) become one
[`ego_network`](../annotation-types/structured/ego_network.md) question per
node type. Use it to run a personal-network interview as a web survey, or in
front of an annotation task.

## Export from Network Canvas

In Architect, save the protocol. The `.netcanvas` file is a zip holding
`protocol.json` and an `assets/` folder; Potato reads either the
`.netcanvas` file or a bare `protocol.json`. Roster files (CSV or JSON network
assets) are read from the zip, or from an `assets/` folder beside a bare
`protocol.json`.

## Import

```bash
potato import -i my-study.netcanvas -o my-study/
python potato/flask_server.py start my-study/config.yaml -p 8000
```

`--input-format network_canvas` (or `netcanvas`) skips detection. Protocols
with translations import in English (`en-US`) unless you pass
`--survey-language`, for example `--survey-language es`.

## Stages and their Potato equivalents

| Network Canvas | Potato |
|---|---|
| `EgoForm` | A survey page; the introduction panel becomes a heading |
| `Information` (text items) | A `pure_display` page, Markdown reduced to plain text |
| `NameGenerator`, `NameGeneratorQuickAdd` | `name_generator` stages, one per prompt |
| `NameGeneratorRoster` | `name_generator` with a `roster` read from the protocol's CSV or JSON asset |
| `additionalAttributes` on a prompt | `sets` on that name generator |
| Extra fields on the add-person form | A `name_interpreter` stage right after the name generator |
| `AlterForm` | `name_interpreter` |
| `OrdinalBin`, `CategoricalBin` | `name_interpreter` with one radio question per prompt |
| `DyadCensus`, `OneToManyDyadCensus` | `dyad_census`, with `relation` from the edge type |
| `TieStrengthCensus` | `dyad_census` with `strength_labels` from the edge variable's options and `no_label` from `negativeLabel` |
| `Sociogram` | `sociogram`; `concentricCircles` becomes `rings`; a prompt without `edges.create` is placement only |
| `minNodes`, `maxNodes` | `min_alters` (first prompt), `max_alters` (each prompt) |

Ego variables become questions by type:

| Codebook type (component) | Potato question |
|---|---|
| `text` (`Text`, `TextArea`) | `text`, a text area for `TextArea` |
| `number` | `number`; `minValue` and `maxValue` become `min` and `max` |
| `categorical` | `multiselect` (`radio` for a `RadioGroup`) |
| `ordinal` | horizontal `radio` (`LikertScale`) or `radio` (`RadioGroup`) |
| `boolean` | `radio` with the variable's two labels, or Yes and No |
| `scalar` (`VisualAnalogScale`) | `vas` from 0 to 1 with the min and max labels |
| `validation.required` | `label_requirement: {required: true}` |

Option values are kept as the stored answers (`true`/`false` for booleans),
so exports carry the same codes as the protocol.

### Skip logic

Skip logic on ego variables becomes page rules. `SHOW` becomes the page's
`show_when`; `SKIP` becomes its negation. `SKIP` with a destination hides every
page between the stage and the destination. When the destination is a
`FinishSession` stage, the rule becomes `exit_when` on the page before, with
the finish screen's text as the message, so a participant who declines consent
leaves the study there. A filter's `join: OR` becomes an `any` group, and
the operators map as follows:

| Operator | Display logic |
|---|---|
| `EXACTLY`, `NOT` | `equals`, `not_equals` (for multi-select: every listed option and no others) |
| `GREATER_THAN`, `GREATER_THAN_OR_EQUAL`, `LESS_THAN`, `LESS_THAN_OR_EQUAL` | `gt`, `gte`, `lt`, `lte` |
| `INCLUDES`, `EXCLUDES` | single choice: `equals`, `not_equals` on the listed values; multi-select: `contains`, `not_contains` on every listed value |
| `CONTAINS`, `DOES NOT CONTAIN` | `contains`, `not_contains` (text) |
| `EXISTS`, `NOT_EXISTS` | `not_empty`, `empty` |
| `OPTIONS_GREATER_THAN`, `OPTIONS_LESS_THAN`, `OPTIONS_EQUALS`, `OPTIONS_NOT_EQUALS` | `count_gt`, `count_lt`, `count_equals`, and its negation |

## Differences from Network Canvas

- **Page order.** All network stages for one node type share one page, placed
  where the first of them was. A network stage that came after other pages
  (an ego form between two name generators, for example) now comes before
  them; the import warns about each one. An `Information` stage directly
  before such a network stage becomes that stage's instructions inside the
  network page.
- **Bins.** Dragging each person into a bin becomes one choice per person.
  The stored values are the same.
- **Several prompts on a stage** become several stages, each with its own
  step button.
- **Already mentioned.** Later name generators list everyone named earlier;
  the respondent adds a person to the current prompt with one click instead of
  dragging them from a side panel.

## Not imported

Each of these is listed in `IMPORT_REPORT.md`:

- skip logic and stage filters that test node or edge data (only ego
  variables can be tested on a Potato page), and skip logic on a network
  stage (the stages inside one `ego_network` question are not skipped one by
  one);
- `AlterEdgeForm`, `Narrative`, `Geospatial`, `FamilyPedigree`,
  `NarrativePedigree`, `NetworkComposer`, `Anonymisation` and
  `LanguageChooser` stages (`FinishSession` is dropped unless it is a skip
  destination, since Potato has its own end page);
- `datetime` variables (date pickers);
- image, audio and video items, sociogram background images and
  highlighting;
- side panels showing external data, and roster assets missing from the file
  (the name generator then takes typed names);
- validation rules other than `required`, `minValue` and `maxValue`, such as
  `minSelected` and `unique`;
- interviewer notes (`interviewScript`), which are never shown to
  participants.

## Data

Potato keeps answers on the server that runs the study, in
`annotation_output/`. The names
respondents type are stored there as typed. The `ego_network` export writes
pseudonymous alter ids only unless you ask for names; see
[Alter names](../annotation-types/structured/ego_network.md#alter-names).

## Related

- [Ego networks](../annotation-types/structured/ego_network.md)
- [Importing surveys](../tools/survey_import.md)
- [Conditional logic](../configuration/conditional_logic.md)
