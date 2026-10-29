"""The deliberate wrong 'highlight' suggestion must be a label name.

With dict labels, random.choice(schema['labels']) put the whole label entry
into the SuggestedResponse.
"""

from unittest.mock import MagicMock, patch


def test_random_highlight_suggestion_is_a_name():
    from potato.flask_server import get_label_suggestions
    item = MagicMock()
    item.get_data.return_value = {"label_suggestions": {"q": "Yes"}}
    config = {"annotation_schemes": [{
        "name": "q", "annotation_type": "radio", "label_suggestions": "highlight",
        "labels": [{"name": "Yes", "color": "#0a0"}, {"name": "No"}]}]}
    with patch("potato.flask_server.random.randrange", return_value=2), \
            patch("potato.flask_server.random.choice", side_effect=lambda seq: seq[-1]):
        out = get_label_suggestions(item, config, [])
    assert [(s.name, s.label) for s in out] == [("q", "No")]
