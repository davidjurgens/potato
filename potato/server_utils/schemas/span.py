"""
Span Layout
"""

import logging
from collections.abc import Mapping
from potato.server_utils.config_module import config

logger = logging.getLogger(__name__)


SPAN_COLOR_PALETTE = [
    "(230, 25, 75)",
    "(60, 180, 75)",
    "(255, 225, 25)",
    "(0, 130, 200)",
    "(245, 130, 48)",
    "(145, 30, 180)",
    "(70, 240, 240)",
    "(240, 50, 230)",
    "(210, 245, 60)",
    "(250, 190, 212)",
    "(0, 128, 128)",
    "(220, 190, 255)",
    "(170, 110, 40)",
    "(255, 250, 200)",
    "(128, 0, 0)",
    "(170, 255, 195)",
    "(128, 128, 0)",
    "(255, 215, 180)",
    "(0, 0, 128)",
    "(128, 128, 128)",
    "(255, 255, 255)",
    "(0, 0, 0)",
]


def get_span_color(span_label):
    """
    Returns the color of a span with this label as a string with an RGB triple
    in parentheses, or None if the span is unmapped.
    """
    if "ui" not in config or "spans" not in config["ui"]:
        return None
    span_ui = config["ui"]["spans"]

    if "span_colors" not in span_ui:
        return None

    if span_label in span_ui["span_colors"]:
        return span_ui["span_colors"][span_label]
    else:
        return None


def set_span_color(span_label, color):
    """
    Sets the color of a span with this label as a string with an RGB triple in parentheses.

    :color: a string containing an RGB triple in parentheses
    """
    if "ui" not in config:
        ui = {}
        config["ui"] = ui
    else:
        ui = config["ui"]

    if "spans" not in ui:
        span_ui = {}
        ui["spans"] = span_ui
    else:
        span_ui = ui["spans"]

    if "span_colors" not in span_ui:
        span_colors = {}
        span_ui["span_colors"] = span_colors
    else:
        span_colors = span_ui["span_colors"]

    span_colors[span_label] = color


def render_span_annotations(text, span_annotations):
    """    
    Retuns a modified version of the text with span annotation overlays inserted
    into the text.

    :text: some instance to be annotated
    :span_annotations: annotations already made by the user that need to be
       re-inserted into the text
    """
    # This code is synchronized with the javascript function
    # surroundSelection(selectionLabel) function in base_template.html which
    # wraps any labeled text with a <div> element indicating its label. We
    # replicate this code here (in python).
    #
    # This synchrony also means that any changes to the UI code for rendering
    # need to be updated here too.

    # We need to go in reverse order to make the string update in the right
    # places, so make sure things are ordered in reverse of start

    rev_order_sa = sorted(span_annotations, key=lambda d: d["start"], reverse=True)

    ann_wrapper = (
        '<span class="span_container" selection_label="{annotation}" '
        + 'style="background-color:rgb{bg_color};">'
        + "{span}"
        + '<div class="span_label" '
        + 'style="background-color:white;border:2px solid rgb{color};">'
        + "{annotation}</div></span>"
    )
    for a in rev_order_sa:

        # Spans are colored according to their order in the list and we need to
        # retrofit the color
        color = get_span_color(a["annotation"])
        # The color is an RGB triple like (1,2,3) and we want the background for
        # the text to be somewhat transparent so we switch to RGBA for bg
        bg_color = color.replace(")", ",0.25)")

        ann = ann_wrapper.format(
            annotation=a["annotation"], span=a["span"], color=color, bg_color=bg_color
        )
        text = text[: a["start"]] + ann + text[a["end"] :]

    return text


def generate_span_layout(annotation_scheme, horizontal=False):
    """
    Renders a span annotation option selection in the annotation panel and
    returns the HTML code
    """
    # when horizontal is specified in the annotation_scheme, set horizontal = True
    if "horizontal" in annotation_scheme and annotation_scheme["horizontal"]:
        horizontal = True

    schematic = (
        '<form action="/action_page.php">'
        + "  <fieldset>"
        + ("  <legend>%s</legend>" % annotation_scheme["description"])
    )

    # TODO: display keyboard shortcuts on the annotation page
    key2label = {}
    label2key = {}
    key_bindings = []

    # setting up label validation for each label, if "required" is True, the annotators will be asked to finish the current instance to proceed
    validation = ""
    label_requirement = (
        annotation_scheme["label_requirement"] if "label_requirement" in annotation_scheme else None
    )
    if label_requirement and ("required" in label_requirement) and label_requirement["required"]:
        validation = "required"

    for i, label_data in enumerate(annotation_scheme["labels"], 1):

        label = label_data if isinstance(label_data, str) else label_data["name"]

        name = annotation_scheme["name"] + ":::" + label
        class_name = annotation_scheme["name"]
        key_value = name

        span_color = get_span_color(label)
        if span_color is None:
            span_color = SPAN_COLOR_PALETTE[(i - 1) % len(SPAN_COLOR_PALETTE)]
            set_span_color(label, span_color)

        # For better or worse, we need to cache these label-color pairings
        # somewhere so that we can render them in the colored instances later in
        # render_span_annotations(). The config object seems like a reasonable
        # place to do since it's global and the colors are persistent
        config["ui"]

        tooltip = ""
        if isinstance(label_data, Mapping):
            tooltip_text = ""
            if "tooltip" in label_data:
                tooltip_text = label_data["tooltip"]
                # print('direct: ', tooltip_text)
            elif "tooltip_file" in label_data:
                with open(label_data["tooltip_file"], "rt") as f:
                    lines = f.readlines()
                tooltip_text = "".join(lines)
                # print('file: ', tooltip_text)
            if len(tooltip_text) > 0:
                tooltip = (
                    'data-toggle="tooltip" data-html="true" data-placement="top" title="%s"'
                    % tooltip_text
                )

            # Bind the keys
            if "key_value" in label_data:
                key_value = label_data["key_value"]
                if key_value in key2label:
                    logger.warning("Keyboard input conflict: %s" % key_value)
                    quit()
                key2label[key_value] = label
                label2key[label] = key_value
                key_bindings.append((key_value, class_name + ": " + label))
            # print(key_value)

        if (
            "sequential_key_binding" in annotation_scheme
            and annotation_scheme["sequential_key_binding"]
            and len(annotation_scheme["labels"]) <= 10
        ):
            key_value = str(i % 10)
            key2label[key_value] = label
            label2key[label] = key_value
            key_bindings.append((key_value, class_name + ": " + label))

        if "displaying_score" in annotation_scheme and annotation_scheme["displaying_score"]:
            label_content = label_data["key_value"] + "." + label
        else:
            label_content = label

        # Check the first radio
        if i == 1:
            is_checked = 'xchecked="checked"'
        else:
            is_checked = ""

        # TODO: add support for horizontal layout
        br_label = "<br/>"
        if horizontal:
            br_label = ""

        # We want to mark that this input isn't actually an annotation (unlike,
        # say, checkboxes) so we prefix the name with span_label so that the
        # answer ingestion code in update_annotation_state() can skip over which
        # radio was checked as being annotations that need saving (while the
        # spans themselves are saved)
        name_with_span = "span_label:::" + name

        schematic += (
            '      <input class="{class_name}" for_span="{for_span}" type="checkbox" id="{name}" name="{name_with_span}" '
            + ' value="{key_value}" {is_checked} '
            + "onclick=\"onlyOne(this); changeSpanLabel(this, '{label_content}', '{span_color}');\" validation=\"{validation}\">"
            + '  <label for="{name}" {tooltip}>'
            + '<span style="background-color:rgb{bg_color};">{label_content}</span></label>{br_label}'
        ).format(
            class_name=class_name,
            for_span = True,
            name=name,
            key_value=key_value,
            label_content=label_content,
            validation=validation,
            tooltip=tooltip,
            br_label=br_label,
            is_checked=is_checked,
            name_with_span=name_with_span,
            bg_color=span_color.replace(")", ",0.25)"),
            span_color=span_color,
        )

    # allow annotators to choose bad_text label
    bad_text_schematic = ""
    if "label_content" in annotation_scheme.get("bad_text_label", {}):
        name = annotation_scheme["name"] + ":::" + "bad_text"
        bad_text_schematic = (
            (
                    ' <input class="{class_name}" for_span="{for_span}" type="checkbox" id="{id}" name="{name}" value="{value}" onclick="onlyOne(this)" validation="{validation}">'
                    + ' {line_break} <label for="{label_for}" {label_args}>{label_text}</label>'
            )
        ).format(
            class_name=annotation_scheme["name"],
            for_span=True,
            id=name,
            name=name,
            value=0,
            validation=validation,
            line_break="",
            label_for=name,
            label_args="",
            label_text=annotation_scheme["bad_text_label"]["label_content"],
        )
        if (
                "sequential_key_binding" in annotation_scheme
                and annotation_scheme["sequential_key_binding"]
                and len(annotation_scheme["labels"]) <= 10
        ):
            key_bindings.append(
                (0, class_name + ": " + annotation_scheme["bad_text_label"]["label_content"])
            )

    schematic += bad_text_schematic

    schematic += "  </fieldset>\n</form>\n"
    return schematic, key_bindings
