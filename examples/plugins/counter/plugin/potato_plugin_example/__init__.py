"""
An example Potato plugin.

- ``counter``: an annotation type with - and + buttons around a number, for
  counting things in an item (entities, errors, people in a photo).
- ``word_count``: a display type that shows a text field with its word count.

Install it with ``pip install -e examples/plugins/counter/plugin``, then
list ``counter`` under ``plugins:`` in a config.
"""

from html import escape

from potato.server_utils.displays.base import BaseDisplay
from potato.server_utils.schemas.identifier_utils import (
    generate_element_identifier,
    generate_layout_attributes,
    safe_generate_layout,
)


def register(api):
    api.add_schema(
        "counter", generate_counter_layout,
        optional_fields=["min", "max", "step", "start"],
        description="A number with - and + buttons, for counting things in an item",
    )
    api.add_display("word_count", WordCountDisplay())
    api.add_assets("static", scripts=["counter.js"], styles=["counter.css"])


def generate_counter_layout(annotation_scheme):
    return safe_generate_layout(annotation_scheme, _counter_layout)


def _counter_layout(scheme):
    name = escape(scheme["name"])
    ids = generate_element_identifier(scheme["name"], "count", "counter")
    low, high = int(scheme.get("min", 0)), scheme.get("max")
    step = int(scheme.get("step", 1))
    bounds = f'min="{low}" step="{step}"' + (f' max="{int(high)}"' if high is not None else "")
    html = f"""
    <form id="{name}" class="annotation-form counter-plugin" data-annotation-type="counter"
          data-schema-name="{name}" action="javascript:void(0)"
          data-annotation-id="{escape(str(scheme.get('annotation_id', '')))}"
          {generate_layout_attributes(scheme)}>
      <fieldset schema="{name}">
        <legend>{escape(scheme['description'])}</legend>
        <div class="counter-plugin-row" data-start="{int(scheme.get('start', low))}">
          <button type="button" class="counter-plugin-step" data-delta="-{step}"
                  aria-label="Decrease {name}">&minus;</button>
          <input class="{ids['schema']} annotation-input counter-plugin-value" type="number"
                 id="{ids['id']}" name="{ids['name']}" schema="{ids['schema']}"
                 label_name="{ids['label_name']}" {bounds} aria-label="{name} count">
          <button type="button" class="counter-plugin-step" data-delta="{step}"
                  aria-label="Increase {name}">+</button>
        </div>
      </fieldset>
    </form>
    """
    return html, []


class WordCountDisplay(BaseDisplay):
    name = "word_count"
    description = "Text with its word count"
    optional_fields = {"label": None}

    def render(self, field_config, data):
        text = "" if data is None else str(data)
        words = len(text.split())
        return (f'<div class="word-count-text">{escape(text)}</div>'
                f'<div class="word-count-total">{words} word{"" if words == 1 else "s"}</div>')
