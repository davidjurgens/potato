"""
Number Layout
"""
import logging

logger = logging.getLogger(__name__)


def generate_number_layout(annotation_scheme):
    # '<div style="border:1px solid black; border-radius: 25px;">' + \
    schematic = (
        '<form action="/action_page.php">'
        + "  <fieldset>"
        + ("  <legend>%s</legend>" % annotation_scheme["description"])
    )

    # TODO: display keyboard shortcuts on the annotation page
    key2label = {}
    label2key = {}

    # TODO: decide whether text boxes need labels
    label = "text_box"

    name = annotation_scheme["name"] + ":::" + label
    class_name = annotation_scheme["name"]
    key_value = name

    # Technically, text boxes don't have these but we define it anyway
    key_bindings = []

    display_info = (
        annotation_scheme["display_config"] if "display_config" in annotation_scheme else {}
    )

    # TODO: pull this out into a separate method that does some sanity checks
    custom_css = '""'
    if "custom_css" in display_info:
        custom_css = '"'
        for k, v in display_info["custom_css"].items():
            custom_css += k + ":" + v + ";"
        custom_css += '"'

    tooltip = ""
    if False:
        if "tooltip" in annotation_scheme:
            tooltip_text = annotation_scheme["tooltip"]
            # print('direct: ', tooltip_text)
        elif "tooltip_file" in annotation_scheme:
            with open(annotation_scheme["tooltip_file"], "rt") as f:
                lines = f.readlines()
            tooltip_text = "".join(lines)
            # print('file: ', tooltip_text)
        if len(tooltip_text) > 0:
            tooltip = (
                'data-toggle="tooltip" data-html="true" data-placement="top" title="%s"'
                % tooltip_text
            )
        if "key_value" in label_data:
            key_value = label_data["key_value"]
            if key_value in key2label:
                logger.warning("Keyboard input conflict: %s" % key_value)
                quit()
            key2label[key_value] = label
            label2key[label] = key_value

    label_content = label

    # add shortkey to the label so that the annotators will know how to use it
    # when the shortkey is "None", this will not displayed as we do not allow short key for None category
    # if label in label2key and label2key[label] != 'None':
    if label in label2key:
        label_content = label_content + " [" + label2key[label].upper() + "]"

    # setting up label validation for each label, if "required" is True, the annotators will be asked to finish the current instance to proceed
    validation = ""
    label_requirement = (
        annotation_scheme["label_requirement"] if "label_requirement" in annotation_scheme else None
    )
    if label_requirement and "required" in label_requirement and label_requirement["required"]:
        validation = "required"

    schematic += (
        '  <input class="%s" style=%s type="number" id="%s" name="%s" validation="%s">'
        + '  <label for="%s" %s></label><br/>'
    ) % (class_name, custom_css, name, name, validation, name, tooltip)

    # schematic += '  </fieldset>\n</form></div>\n'
    schematic += "  </fieldset>\n</form>\n"

    return schematic, key_bindings
