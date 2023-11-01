"""
Pure Display Layout
"""


def generate_pure_display_layout(annotation_scheme, generate_llm_query=False):
    if generate_llm_query:
        raise NotImplementedError("LLM query is not supported for pure display layout.")
    schematic = "<Strong>%s</Strong> %s" % (
        annotation_scheme["description"],
        "<br>".join(annotation_scheme["labels"]),
    )

    return schematic, None
