"""Two scheme options that were documented and did nothing, or failed.

multirate ``randomize_order`` shuffled the rating scale's names and then looked
for rows with those names, so the rows never moved and the scale was recorded
as the order shown.

select ``use_predefined_labels`` (every example of it has no ``labels``) was
refused by validation with "labels cannot be empty".
"""

import json

import pytest

from potato.server_utils.config_module import (
    ConfigValidationError,
    validate_single_annotation_scheme,
)
from potato.server_utils.presentation_order import presentation_order

ROWS = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"]
MULTIRATE = {"annotation_type": "multirate", "name": "mr", "description": "Rate",
             "options": ROWS, "labels": ["1", "2", "3"]}


class TestMultirateOrder:
    def test_the_rows_are_what_is_ordered(self):
        assert presentation_order(MULTIRATE, "u", "i1") == ROWS
        shown = [presentation_order(dict(MULTIRATE, randomize_order=True), "u%d" % n, "i1")
                 for n in range(5)]
        assert all(sorted(order) == sorted(ROWS) for order in shown)
        assert len({tuple(order) for order in shown}) > 1

    def test_dict_options_are_ordered_by_name(self):
        scheme = dict(MULTIRATE, options=[{"name": r, "label": r.title()} for r in ROWS],
                      option_randomization=True)
        assert sorted(presentation_order(scheme, "u", "i1")) == sorted(ROWS)

    def test_the_page_shows_the_recorded_order(self):
        from bs4 import BeautifulSoup
        from potato.flask_server import _row_label, randomize_options
        from potato.server_utils.schemas.registry import schema_registry
        scheme = dict(MULTIRATE, randomize_order=True)
        order = presentation_order(scheme, "u", "i1")
        soup = BeautifulSoup(schema_registry.generate(scheme)[0], "html.parser")
        randomize_options(soup, {"Rate": order})
        assert [_row_label(r) for r in soup.find("table").find_all("tr")[1:]] == order

    @pytest.mark.parametrize("arrangement", ["horizontal", "vertical"])
    @pytest.mark.parametrize("columns", [2, 3])
    def test_several_items_per_row_read_in_the_recorded_order(self, columns, arrangement):
        """With num_columns > 1 a row holds several items. Moving whole rows
        left each row's items in configured order."""
        from bs4 import BeautifulSoup
        from potato.flask_server import randomize_options
        from potato.server_utils.schemas.registry import schema_registry
        rows = ROWS + ["eta"]          # 7: the last row or column is short
        scheme = dict(MULTIRATE, options=rows, randomize_order=True,
                      display_config={"num_columns": columns}, arrangement=arrangement)
        order = presentation_order(scheme, "u", "i1")
        soup = BeautifulSoup(schema_registry.generate(scheme)[0], "html.parser")
        randomize_options(soup, {"Rate": order})
        grid = []
        for tr in soup.find("table").find_all("tr")[1:]:
            cells = tr.find_all("td", recursive=False)
            slots = [cells[i:i + 4] for i in range(0, len(cells), 4)]   # label + 3 ratings
            row = []
            for slot in slots:
                radios = [c.find("input") for c in slot[1:] if c.find("input")]
                if radios:
                    # The ratings moved with their item's label cell.
                    assert {r["label_name"] for r in radios} == {slot[0].get_text(strip=True)}
                row.append(slot[0].get_text(strip=True) if radios else None)
            grid.append(row)
        if arrangement == "vertical":
            read = [grid[r][c] for c in range(columns) for r in range(len(grid))]
        else:
            read = [name for row in grid for name in row]
        assert [name for name in read if name] == order

    def test_rows_from_item_data_warn_once_and_record_nothing(self, caplog):
        from potato.server_utils import presentation_order as po
        po._warned_unorderable.clear()
        scheme = {"annotation_type": "multirate", "name": "dyn", "description": "Rate",
                  "options_from_data": "rows", "labels": ["1", "2"], "randomize_order": True}
        with caplog.at_level("WARNING"):
            assert presentation_order(scheme, "u", "i1") is None
            assert presentation_order(scheme, "u", "i2") is None
        warned = [r for r in caplog.records if "NOT randomized" in r.getMessage()]
        assert len(warned) == 1 and "'rows' field" in warned[0].getMessage()


class TestSelectPredefinedLabels:
    def test_a_built_in_list_is_not_randomized_and_says_so(self, caplog):
        """Even with a `labels` list beside it, which the page does not show."""
        from potato.server_utils import presentation_order as po
        po._warned_unorderable.clear()
        scheme = {"annotation_type": "select", "name": "where", "description": "?",
                  "use_predefined_labels": "country", "labels": ["a", "b", "c"],
                  "option_randomization": True}
        with caplog.at_level("WARNING"):
            assert presentation_order(scheme, "u", "i1") is None
        assert any("built-in 'country' list" in r.getMessage() for r in caplog.records)

    @pytest.mark.parametrize("name", ["country", "ethnicity", "religion"])
    def test_each_built_in_list_validates_and_renders(self, name):
        from potato.server_utils.schemas.registry import schema_registry
        scheme = {"annotation_type": "select", "name": "q", "description": "?",
                  "use_predefined_labels": name}
        validate_single_annotation_scheme(scheme, "annotation_schemes[0]")
        html, _ = schema_registry.generate(scheme)
        assert html.count("<option") > 3

    def test_an_unknown_list_is_named(self):
        scheme = {"annotation_type": "select", "name": "q", "description": "?",
                  "use_predefined_labels": "language"}
        with pytest.raises(ConfigValidationError, match="country, ethnicity, religion"):
            validate_single_annotation_scheme(scheme, "annotation_schemes[0]")

    def test_neither_labels_nor_a_list_is_still_refused(self):
        with pytest.raises(ConfigValidationError, match="labels"):
            validate_single_annotation_scheme(
                {"annotation_type": "select", "name": "q", "description": "?"},
                "annotation_schemes[0]")

    def test_the_published_json_schema_agrees(self):
        jsonschema = pytest.importorskip("jsonschema")
        from potato.server_utils.config_schema import build_config_schema
        schema = build_config_schema()
        items = schema["properties"]["annotation_schemes"]

        def valid(scheme):
            return jsonschema.Draft7Validator(items).is_valid([scheme])

        base = {"annotation_type": "select", "name": "q", "description": "?"}
        assert valid(dict(base, use_predefined_labels="country"))
        assert valid(dict(base, labels=["a", "b"]))
        assert not valid(base)

    def test_the_documented_survey_example_loads(self):
        """docs/workflow/surveyflow.md's prescreening.json scheme, verbatim."""
        scheme = json.loads('''{
            "name": "country",
            "annotation_type": "select",
            "description": "Which country do you live in?",
            "use_predefined_labels": "country",
            "label_requirement": {"required": true}
        }''')
        validate_single_annotation_scheme(scheme, "annotation_schemes[0]")


def _country_values():
    import os
    import re
    import potato
    path = os.path.join(os.path.dirname(potato.__file__), "static", "survey_assets",
                        "country_dropdown_list.html")
    with open(path, encoding="utf-8") as handle:
        return re.findall(r'<option\s+value="([^"]+)"', handle.read())


def test_the_country_list_has_current_names_and_no_misspellings():
    """The list had Nambia, Futana, Zaire, Swaziland and Macedonia, and no
    South Sudan, Guinea-Bissau, Micronesia or DR Congo."""
    import html
    values = {html.unescape(v) for v in _country_values()}
    for name in ("Namibia", "Wallis & Futuna Is", "South Sudan", "Guinea-Bissau",
                 "Micronesia", "Democratic Republic of the Congo", "Congo", "Eswatini",
                 "North Macedonia", "Western Sahara", "Åland Islands", "St Martin"):
        assert name in values, name
    for gone in ("Nambia", "Wallis & Futana Is", "Zaire", "Swaziland", "Macedonia"):
        assert gone not in values, gone


def test_each_country_stores_its_name_as_shown():
    """Six values were misspelled ('Afganistan', 'Uraguay', ...) while the
    page showed the right name, so the stored answer differed from what was
    picked. A value may drop a parenthetical, as 'Netherlands' does."""
    import html
    import os
    import re
    import potato
    path = os.path.join(os.path.dirname(potato.__file__), "static", "survey_assets",
                        "country_dropdown_list.html")
    with open(path, encoding="utf-8") as handle:
        options = re.findall(r'<option\s+value="([^"]+)"[^>]*>(.*?)</option>', handle.read(), re.S)
    assert len(options) > 200
    wrong = []
    for value, text in options:
        value, text = html.unescape(value), html.unescape(text.strip())
        if value not in (text, re.sub(r"\s*\(.*\)$", "", text)):
            wrong.append((value, text))
    assert not wrong
