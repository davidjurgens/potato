"""
Grounding evaluation: which region of an image a piece of language refers to.

An item is an image plus a list of **referring expressions** — "the man in the
red shirt", "the leftmost cup" — and the annotator's job is to say, for each
one, where it points.

## Why the expressions are a list on the item, not one per item

RefCOCO-style data has several expressions per image, and they are answered
against the same picture. Splitting them into one item each would make the
annotator re-load and re-read the image for every phrase, and would destroy
the comparison that matters most — "the leftmost cup" and "the cup behind the
kettle" only mean anything next to each other.

## "Not present in the image" is a first-class answer

The hardest thing to measure about a vision-language model is what it does when
asked about something that is not there, and the only way to measure it is for
the annotator to be able to say so. Without that control, an expression with no
region is ambiguous between "I judged there is no referent" and "I did not get
to this one" — which support opposite conclusions about a model that also
produced nothing.

So each expression carries three states, and the interface distinguishes them:
answered with a region, answered as absent, and not answered. The same
reasoning as `clean` in the rollout schema, for the same reason.

## Pointing and grounding share this schema

Molmo-style models emit points rather than boxes, and the annotation for that
is a `landmark`. It is the same task — "where is the thing this phrase names" —
so it is the same schema with `region_type: point`; only the scoring differs,
and that lives in `potato/grounding/metrics.py`.
"""

import json
import logging

from .identifier_utils import escape_html_content, safe_generate_layout

logger = logging.getLogger(__name__)

#: Where the phrases to ground come from.
#:
#: `field` reads a list off the item — the RefCOCO shape, where the expressions
#: are given. `spans` lets the annotator select them out of a caption, which is
#: what hallucination localization needs: the phrases are not known in advance
#: because they are whatever the model happened to say.
VALID_EXPRESSION_SOURCES = ("field", "spans")

#: What an annotator draws for each expression. `box` is the RefCOCO
#: convention; `point` is what pointing models emit; `mask` and `polygon` are
#: for tasks where a box is too coarse to be an answer.
VALID_REGION_TYPES = ("box", "polygon", "mask", "point")

#: The drawing tool each region type needs, in image_annotation's vocabulary.
REGION_TOOLS = {
    "box": "bbox",
    "polygon": "polygon",
    "mask": "brush",
    "point": "landmark",
}

#: How a judged prediction can be scored, when the schema is used to review a
#: model's output rather than to create ground truth.
DEFAULT_VERDICTS = [
    {"name": "correct", "description": "Points at the right thing"},
    {"name": "wrong_object", "description": "Points at something else in the image"},
    {"name": "partial", "description": "Overlaps the right thing but is badly placed"},
    {"name": "not_present", "description": "Nothing in the image matches this phrase"},
]


def generate_grounding_eval_layout(annotation_scheme):
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _generate_internal(annotation_scheme):
    schema_name = annotation_scheme.get("name", "grounding")
    escaped_name = escape_html_content(schema_name)
    description = escape_html_content(
        annotation_scheme.get("description", "Mark what each phrase refers to"))

    region_type = str(annotation_scheme.get("region_type", "box")).lower()
    if region_type not in VALID_REGION_TYPES:
        raise ValueError(
            f"Invalid region_type {region_type!r} in schema {schema_name!r}. "
            f"Valid region types are: {list(VALID_REGION_TYPES)}")

    expression_source = str(
        annotation_scheme.get("expression_source", "field")).lower()
    if expression_source not in VALID_EXPRESSION_SOURCES:
        raise ValueError(
            f"Invalid expression_source {expression_source!r} in schema "
            f"{schema_name!r}. Valid sources are: "
            f"{list(VALID_EXPRESSION_SOURCES)}")

    expressions_field = annotation_scheme.get("expressions_field", "expressions")
    caption_field = annotation_scheme.get("caption_field", "caption")
    predictions_field = annotation_scheme.get("predictions_field", "")
    label_name = annotation_scheme.get("label", "referent")

    review_mode = bool(predictions_field)
    verdicts = annotation_scheme.get("verdicts") or DEFAULT_VERDICTS

    config = {
        "schemaName": schema_name,
        "regionType": region_type,
        "tool": REGION_TOOLS[region_type],
        "expressionSource": expression_source,
        "expressionsField": expressions_field,
        "captionField": caption_field,
        "predictionsField": predictions_field,
        "reviewMode": review_mode,
        "label": label_name,
        "verdicts": [v.get("name") if isinstance(v, dict) else str(v)
                     for v in verdicts],
        # Refusing to advance with expressions unanswered. Off by default: a
        # long expression list is legitimately worked through over several
        # sittings, and a hard gate on a 30-phrase image is an obstacle rather
        # than a safeguard.
        "requireAll": bool(annotation_scheme.get("require_all", False)),
    }

    caption_html = ""
    if expression_source == "spans":
        caption_html = f"""
        <!-- The text being grounded. Phrases are selected out of it rather
             than given in advance, because in hallucination localization the
             phrases are whatever the model happened to say. -->
        <div class="grounding-caption-panel">
            <p class="grounding-caption-help">
                Select a phrase in the text below, then mark what it refers to
                on the image — or say it is not present. A phrase you never
                select is not counted either way.
            </p>
            <div class="grounding-caption" id="grounding-caption-{escaped_name}"
                 tabindex="0"
                 aria-label="Generated caption. Select a phrase to ground it."></div>
            <button type="button" class="grounding-add-span-btn"
                    data-schema="{escaped_name}" disabled>
                Ground the selected phrase
            </button>
        </div>"""

    verdict_html = ""
    if review_mode:
        options = "".join(
            f'<option value="{escape_html_content(str(v.get("name") if isinstance(v, dict) else v))}">'
            f'{escape_html_content(str(v.get("name") if isinstance(v, dict) else v))}</option>'
            for v in verdicts)
        verdict_html = f"""
                <div class="grounding-verdict">
                    <label for="grounding-verdict-{escaped_name}">Prediction verdict</label>
                    <select id="grounding-verdict-{escaped_name}"
                            class="grounding-verdict-select">
                        <option value="">— not judged —</option>
                        {options}
                    </select>
                </div>"""

    html = f"""
<div class="grounding-eval-container" data-schema="{escaped_name}"
     data-region-type="{region_type}">
    <fieldset class="grounding-eval-fieldset">
        <legend class="grounding-eval-legend">{description}</legend>

        {caption_html}

        <!-- The expressions. A list rather than one per item: RefCOCO-style
             phrases are answered against the same picture and only mean
             anything next to each other. -->
        <div class="grounding-expressions" role="radiogroup"
             aria-label="Referring expressions. Select one, then mark its region on the image.">
            <ol id="grounding-list-{escaped_name}" class="grounding-list"></ol>
        </div>

        <div class="grounding-controls">
            <button type="button" class="grounding-absent-btn"
                    data-schema="{escaped_name}"
                    aria-describedby="grounding-absent-help-{escaped_name}">
                Not present in the image
            </button>
            <button type="button" class="grounding-clear-btn"
                    data-schema="{escaped_name}">
                Clear this answer
            </button>
            <p id="grounding-absent-help-{escaped_name}" class="grounding-help">
                Use this when nothing in the picture matches the phrase. It is a
                different answer from leaving it blank, and both are recorded.
            </p>
        </div>
        {verdict_html}

        <p class="grounding-progress" id="grounding-progress-{escaped_name}"
           aria-live="polite"></p>
        <span class="grounding-announce sr-only" role="status"
              id="grounding-announce-{escaped_name}"></span>

        <input type="hidden" name="{escaped_name}" id="input-{escaped_name}"
               class="annotation-data-input" value="">
    </fieldset>
</div>

<script>
(function () {{
    var config = {json.dumps(config)};
    function boot() {{
        var container = document.querySelector(
            '.grounding-eval-container[data-schema="{escaped_name}"]');
        if (!container || typeof GroundingEvalManager === 'undefined') return;
        try {{
            var manager = new GroundingEvalManager(container, config);
            container.groundingManager = manager;
            manager.init();
        }} catch (error) {{
            // Attaching before init() would leave a half-built manager that
            // every readiness check accepts. Surfacing the throw is the whole
            // point of this block.
            console.error('Grounding evaluation failed to start:', error);
            container.classList.add('error');
        }}
    }}
    if (document.readyState === 'loading') {{
        document.addEventListener('DOMContentLoaded', boot);
    }} else {{
        boot();
    }}
}})();
</script>
"""
    return html, []
