"""A plugin installed only for the test suite (tests/data/plugins/site)."""

from html import escape

from potato.server_utils.displays.base import BaseDisplay
from potato.server_utils.schemas.identifier_utils import generate_element_identifier


def stars_layout(scheme):
    ids = generate_element_identifier(scheme["name"], "stars", "text")
    top = int(scheme.get("max_stars", 5))
    html = (f'<form id="{escape(scheme["name"])}" class="annotation-form" '
            f'data-annotation-type="test_stars" action="javascript:void(0)">'
            f'<fieldset schema="{ids["schema"]}"><legend>{escape(scheme["description"])}</legend>'
            f'<input class="{ids["schema"]} annotation-input" type="number" min="1" max="{top}" '
            f'id="{ids["id"]}" name="{ids["name"]}" schema="{ids["schema"]}" '
            f'label_name="{ids["label_name"]}"></fieldset></form>')
    return html, []


class ShoutDisplay(BaseDisplay):
    name = "test_shout"
    description = "Upper-cases a text field"

    def render(self, field_config, data):
        return f'<div class="test-shout">{escape(str(data)).upper()}</div>'


def register(api):
    api.add_schema("test_stars", stars_layout, optional_fields=["max_stars"],
                   description="Stars, for tests")
    api.add_display("test_shout", ShoutDisplay())
    api.add_assets("static", scripts=["test.js"], styles=["test.css"])


def register_collision(api):
    api.add_schema("test_unique_type", stars_layout)
    api.add_schema("radio", stars_layout)


def register_explodes(api):
    api.add_schema("test_never_registered", stars_layout)
    raise RuntimeError("database not configured")


def register_missing_asset(api):
    api.add_assets("static", scripts=["absent.js"])


def register_twice(api):
    api.add_schema("test_twice_first", stars_layout)
    api.add_schema("test_twice", stars_layout)
    api.add_schema("test_twice", stars_layout)


def register_display_twice(api):
    api.add_display("test_display_twice", ShoutDisplay())
    api.add_display("test_display_twice", ShoutDisplay())
