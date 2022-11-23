"""
Textbox Layout
"""


def generate_textbox_layout(annotation_scheme):

    #'<div style="border:1px solid black; border-radius: 25px;">' + \
    schematic = (
        '<form action="/action_page.php">'
        + "  <fieldset>"
        + (
            '  <legend>%s</legend> <ul class="likert" style="text-align: center;">'
            % annotation_scheme["description"]
        )
    )

    # TODO: display keyboard shortcuts on the annotation page
    key2label = {}
    label2key = {}

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

    # supporting multiple textboxes with different labels
    if "labels" not in annotation_scheme or annotation_scheme["labels"] == None:
        labels = ["text_box"]
    else:
        labels = annotation_scheme["labels"]
    for label in labels:
        name = annotation_scheme["name"] + ":::" + label
        class_name = annotation_scheme["name"]
        key_value = name

        # setting up label validation for each label, if "required" is True, the annotators will be asked to finish the current instance to proceed
        validation = ""
        label_requirement = (
            annotation_scheme["label_requirement"]
            if "label_requirement" in annotation_scheme
            else None
        )
        if label_requirement and "required" in label_requirement and label_requirement["required"]:
            validation = "required"

        # set up textarea to allow multiline text input
        if "textarea" in annotation_scheme and annotation_scheme["textarea"]["on"]:
            rows = (
                annotation_scheme["textarea"]["rows"]
                if "rows" in annotation_scheme["textarea"]
                else "3"
            )
            cols = (
                annotation_scheme["textarea"]["cols"]
                if "rows" in annotation_scheme["textarea"]
                else "40"
            )
            schematic += (
                '  <li><label for="%s" %s>%s</label> '
                + '<textarea rows="%s" cols="%s" class="%s" style=%s type="text" id="%s" name="%s" validation="%s"></textarea></li> <br/>'
            ) % (
                name,
                tooltip,
                label if label != "text_box" else "",
                rows,
                cols,
                class_name,
                custom_css,
                name,
                name,
                validation,
            )
        else:
            schematic += (
                '  <li><label for="%s" %s>%s</label> <input class="%s" style=%s type="text" id="%s" name="%s" validation="%s"> </li> <br/>'
            ) % (
                name,
                tooltip,
                label if label != "text_box" else "",
                class_name,
                custom_css,
                name,
                name,
                validation,
            )

        # schematic += '  </fieldset>\n</form></div>\n'
    schematic += " </ul> </fieldset>\n</form>\n"

    """
    tooltip = ''
    if False:
        if 'tooltip' in annotation_scheme:
            tooltip_text = annotation_scheme['tooltip']
            # print('direct: ', tooltip_text)
        elif 'tooltip_file' in annotation_scheme:
            with open(annotation_scheme['tooltip_file'], 'rt') as f:
                lines = f.readlines()
            tooltip_text = ''.join(lines)
            # print('file: ', tooltip_text)
        if len(tooltip_text) > 0:
            tooltip = 'data-toggle="tooltip" data-html="true" data-placement="top" title="%s"' \
                % tooltip_text
        if 'key_value' in label_data:
            key_value = label_data['key_value']
            if key_value in key2label:
                logger.warning(
                    "Keyboard input conflict: %s" % key_value)
                quit()
            key2label[key_value] = label
            label2key[label] = key_value

    
    label_content = label

    #add shortkey to the label so that the annotators will know how to use it
    #when the shortkey is "None", this will not displayed as we do not allow short key for None category
    #if label in label2key and label2key[label] != 'None':
    if label in label2key:
        label_content = label_content + \
            ' [' + label2key[label].upper() + ']'
    """

    return schematic, key_bindings
