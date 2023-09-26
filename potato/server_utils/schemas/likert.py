"""
Likert Layout
"""

from .radio import generate_radio_layout


def generate_likert_layout(annotation_scheme):

    # If the user specified the more complicated likert layout, default to the
    # radio layout
    if "labels" in annotation_scheme:
        return generate_radio_layout(annotation_scheme, horizontal=False)

    for required in ["size", "min_label", "max_label"]:
        if required not in annotation_scheme:
            raise Exception(
                'Likert scale for "%s" did not include %s' % (annotation_scheme["name"], required)
            )

    schematic = (
        '<div><form action="/action_page.php">'
        + '  <fieldset> <legend>%s</legend> <ul class="likert" style="text-align: center;"> <li> %s </li>'
    ) % (annotation_scheme["description"], annotation_scheme["min_label"])

    key2label = {}
    label2key = {}
    key_bindings = []

    # Setting up label validation for each label, if "required" is True,
    # the annotators will be asked to finish the current instance to proceed
    validation = ""
    label_requirement = annotation_scheme.get("label_requirement")
    if label_requirement and label_requirement.get("required"):
        validation = "required"

    for i in range(1, annotation_scheme["size"] + 1):

        label = "scale_" + str(i)
        name = annotation_scheme["name"] + ":::" + label
        class_name = annotation_scheme["name"]

        key_value = str(i % 10)

        # if the user wants us to add in easy key bindings
        if "sequential_key_binding" in annotation_scheme and annotation_scheme["sequential_key_binding"] == True and annotation_scheme["size"] < 10:
            key2label[key_value] = label
            label2key[label] = key_value
            key_bindings.append((key_value, class_name + ": " + key_value))

        # In the collapsed version of the likert scale, no label is shown.
        label_content = str(i) if annotation_scheme.get("displaying_score") else ""
        tooltip = ""

        # displaying the label content in a different line if it is not empty
        if label_content != "":
            line_break = "<br>"
        else:
            line_break = ""
        # schematic += \
        #        ((' <li><input class="%s" type="radio" id="%s" name="%s" value="%s" onclick="onlyOne(this)">' +
        #         '  <label for="%s" %s>%s</label></li>')
        #         % (class_name, label, name, key_value, name, tooltip, label_content))

        schematic += (
            (
                ' <li><input class="{class_name}" type="radio" id="{id}" name="{name}" value="{value}" onclick="onlyOne(this)" validation="{validation}">'
                + ' {line_break} <label for="{label_for}" {label_args}>{label_text}</label></li>'
            )
        ).format(
            class_name=class_name,
            id=name,
            name=name,
            value=key_value,
            validation=validation,
            line_break=line_break,
            label_for=name,
            label_args=tooltip,
            label_text=" " + label_content,
        )

    # allow annotators to choose bad_text label
    bad_text_schematic = ""
    if "label_content" in annotation_scheme.get("bad_text_label", {}):
        name = annotation_scheme["name"] + ":::" + "bad_text"
        bad_text_schematic = (
            (
                ' <li><input class="{class_name}" type="radio" id="{id}" name="{name}" value="{value}" onclick="onlyOne(this)" validation="{validation}">'
                + ' {line_break} <label for="{label_for}" {label_args}>{label_text}</label></li>'
            )
        ).format(
            class_name=annotation_scheme["name"],
            id=name,
            name=name,
            value=0,
            validation=validation,
            line_break="<br>",
            label_for=name,
            label_args="",
            label_text=annotation_scheme["bad_text_label"]["label_content"],
        )
        if "sequential_key_binding" in annotation_scheme and annotation_scheme["sequential_key_binding"] == True and annotation_scheme["size"] < 10:
            key_bindings.append(
                (0, class_name + ": " + annotation_scheme["bad_text_label"]["label_content"])
            )

    schematic += "  <li>%s</li> %s </ul></fieldset>\n</form></div>\n" % (
        annotation_scheme["max_label"],
        bad_text_schematic,
    )

    return schematic, key_bindings
