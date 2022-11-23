"""
Pure Display Layout
"""


def generate_pure_display_layout(annotation_scheme):
    schematic = "<Strong>%s</Strong> %s" % (
        annotation_scheme["description"],
        "<br>".join(annotation_scheme["labels"]),
    )

    return schematic, None
