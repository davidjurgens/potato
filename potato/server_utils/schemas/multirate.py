"""
Multirate Layout
"""

import logging
from collections.abc import Mapping

logger = logging.getLogger(__name__)


def generate_multirate_layout(annotation_scheme):
    schematic = (
        '<form action="/action_page.php">'
        + "  <fieldset>"
        + ("  <legend>%s</legend>" % annotation_scheme["description"])
    )

    # TODO: display keyboard shortcuts on the annotation page
    key2label = {}
    label2key = {}

    key_bindings = []

    display_info = (
        annotation_scheme["display_config"] if "display_config" in annotation_scheme else {}
    )

    n_columns = display_info["num_columns"] if "num_columns" in display_info else 1

    schematic += "<table>"

    # Put in the header that has all options
    num_headers = min(len(annotation_scheme["options"]), n_columns)

    ratings = annotation_scheme["labels"]
    schematic += "<tr>"
    for _ in range(num_headers):
        schematic += "<td>&nbsp;</td>"
        for rating in ratings:
            schematic += "<td>&nbsp;%s&nbsp;</td>" % rating
    schematic += "</tr>"
    

    options = annotation_scheme["options"]

    if 'arrangement' in annotation_scheme and annotation_scheme['arrangement'] == 'vertical':
        cols = [[] for _ in range(n_columns)]
        n_rows = len(options) // n_columns 
        if (len(options) % n_columns) > 0:
            n_rows += 1
        wc = 0
        #print('n_rows', n_rows)
        for i, opt in enumerate(options):
            #print(opt)
            if i > 0 and i % n_rows == 0:
                wc += 1
            cols[wc].append(opt)

        #for c in cols[0]:
        #    print(c)
        reordered_options = []
        for r in range(n_rows):
            for c in cols:
                if r < len(c):
                    reordered_options.append(c[r])
        options = reordered_options
            
    
    #schematic += "<tr>"    
    for i, label_data in enumerate(options, 1):

        if (i - 1) % n_columns == 0:
            schematic += "<tr>"
        

        label = label_data if isinstance(label_data, str) else label_data["label"]

        option = label_data if isinstance(label_data, str) else label_data["name"]
        name = annotation_scheme["name"] + ":::" + option
        class_name = annotation_scheme["name"]
        key_value = name

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


        label_content = label
        radio_style = "vertical-align: middle; margin: 0px;"
        schematic += '<td style="text-align:right; vertical-align: middle; margin: 0px;">%s</td>' % label
        for rating in ratings:

            input_name = name # + ':::' + rating
            #print(input_name)
            
            schematic += (
                '<td style="text-align:center;">' +
                '<input name="{name}" type="radio" id="{id}" ' +
                'value="{value}" onclick="onlyOne(this)" style="{radio_style}"/></td>'
            ).format(name=name, tooltip=tooltip, class_name=class_name, id=name+'.'+rating,
                     radio_style=radio_style, value=rating)

        #schematic += "</td>"
        if i % n_columns == 0:
            schematic += "</tr>"


    schematic += "</table>"
    schematic += "  </fieldset>\n</form>\n"

    return schematic, key_bindings
