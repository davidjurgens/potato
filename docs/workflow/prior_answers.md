# Prior Answers

Use `prior_answers` to show each annotator their own answer to a survey question on every annotation page.

A typical study asks the participant to define a concept in a prestudy survey. Then the participant labels items against that concept. With `prior_answers`, each annotation page shows a box with the participant's own definition. The participant clicks the box to read the definition again.

Potato reads the answer from the participant's saved state on the server. The box shows the same answer in a different browser or on a different device.

Working example:
[`examples/advanced/prior-answers/`](https://github.com/davidjurgens/potato/tree/master/examples/advanced/prior-answers)

## Configuration

1. Put the question on a survey page. Use a `prestudy`, `consent`, `poststudy` or other survey phase.
2. Add a `prior_answers` list to the config. Add one entry for each question to show.
3. In each entry, set `schema` to the `name` of the question.

Survey page `surveys/definition.json`:

```json
[
  {
    "name": "concept_definition",
    "annotation_type": "text",
    "description": "In your own words, how would you define populism?",
    "multiline": true,
    "label_requirement": {"required": true}
  }
]
```

Config:

```yaml
phases:
  order:
  - definition
  - annotation
  definition:
    type: prestudy
    file: surveys/definition.json

prior_answers:
- schema: concept_definition
  title: Definition
```

Each annotation page now shows a closed box with the label "Definition". The box is above the annotation questions.

## Keys

Each entry in `prior_answers` accepts these keys:

| Key | Type | Default | Description |
|---|---|---|---|
| `schema` | string | (required) | The `name` of a question on a survey page. |
| `title` | string | The question's `description` | The text on the box. |
| `collapsible` | boolean | `true` | `true` shows the answer in a box that opens with a click. `false` always shows the answer. |
| `collapsed_default` | boolean | `true` | `true` closes the box when the page opens. `false` opens it. Potato ignores this key when `collapsible` is `false`. |

## How Potato shows each question type

| Question type | Text in the box |
|---|---|
| `text` with one field | The text that the participant wrote. Line breaks stay. |
| `text` with more than one field | One line for each field, in the form `field: answer`. |
| `radio`, `likert` | The name of the selected label. |
| `select` | The selected option. |
| `multiselect` | The name of each selected label, one on each line. |
| An "Other" free-response field | The free text, on a line after the selected label. |
| `number`, `slider` | The value. |

Potato escapes all answer text as HTML. A participant who types `<b>` sees the characters `<b>`. The browser does not read them as markup.

## Rules

- Potato shows the answer of the participant who opens the page. On a [collaborative session](../advanced/collaborative_sessions.md) page, Potato shows the answer of the viewer, not of the team.
- Potato does not show a box when the participant gave no answer. Thus an optional question that the participant skipped adds no empty box.
- If the participant answers the same question on two survey pages, Potato shows the last answer.
- `schema` must name a question on a survey page. If no survey page has that question, the server does not start. The error message lists the survey questions that it found.
- `schema` must not name an annotation scheme. Use `prior_answers` for survey answers only.

## Related documentation

- [Multi-Phase Workflows](surveyflow.md): survey phases and their question files.
- [Guidelines and Codebooks](annotation_guidelines.md): the `annotation_instructions` box, which shows the same text to all annotators.
- [Conditional Logic](../configuration/conditional_logic.md): show or hide survey questions from earlier answers.
