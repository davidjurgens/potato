"""A free-text box must be named for assistive technology.

With the default label the generator emits no <label>, and the fieldset's
legend names the group, not the field, so a screen reader announced the
agent-trace "Additional notes" box as a bare "edit text".
"""

from bs4 import BeautifulSoup

from potato.server_utils.schemas.textbox import generate_textbox_layout


def _field(**extra):
    scheme = {"annotation_type": "text", "name": "notes",
              "description": "Additional notes or observations", **extra}
    html, _ = generate_textbox_layout(scheme)
    soup = BeautifulSoup(html, "html.parser")
    return soup, soup.select_one(".shadcn-textbox-input")


def _accessible_name(soup, field):
    if field.get("aria-label"):
        return field["aria-label"]
    label = soup.find("label", attrs={"for": field.get("id")})
    return label.get_text(strip=True) if label else ""


def test_single_line_box_is_named_after_the_question():
    soup, field = _field()
    assert _accessible_name(soup, field) == "Additional notes or observations"


def test_textarea_is_named_after_the_question():
    soup, field = _field(multiline=True)
    assert field.name == "textarea"
    assert _accessible_name(soup, field) == "Additional notes or observations"


def test_a_visible_label_is_not_overridden():
    soup, field = _field(labels=["Reason"])
    assert not field.get("aria-label")
    assert _accessible_name(soup, field) == "Reason"


def test_the_name_is_escaped():
    soup, field = _field(description='Say "why" <b>here</b>')
    assert _accessible_name(soup, field) == 'Say "why" <b>here</b>'
    assert not soup.find("b")
