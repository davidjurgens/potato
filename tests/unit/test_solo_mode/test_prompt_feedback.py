""""Get Feedback": LLM critique of the annotation prompt (advisory only,
never mutates the prompt or codebook) — prompt_feedback.py."""

from potato.solo_mode.prompt_feedback import get_prompt_feedback


class FakeEndpoint:
    def __init__(self, response):
        self.response = response
        self.prompts = []

    def query(self, prompt):
        self.prompts.append(prompt)
        return self.response


def test_returns_parsed_feedback_items():
    endpoint = FakeEndpoint({
        "feedback": [
            {"issue": "Categories overlap", "suggestion": "Add an "
             "exclusion rule", "severity": "high"},
            {"issue": "Vague wording", "suggestion": "Define 'urgent'",
             "severity": "low"},
        ],
    })
    result = get_prompt_feedback("Label the text as urgent or not.",
                                  endpoint)
    assert len(result) == 2
    assert result[0]["issue"] == "Categories overlap"
    assert result[0]["severity"] == "high"


def test_empty_prompt_never_calls_endpoint():
    endpoint = FakeEndpoint({"feedback": []})
    assert get_prompt_feedback("   ", endpoint) == []
    assert endpoint.prompts == []


def test_endpoint_failure_returns_empty_list():
    class BrokenEndpoint:
        def query(self, prompt):
            raise RuntimeError("boom")

    assert get_prompt_feedback("Some prompt", BrokenEndpoint()) == []


def test_malformed_response_returns_empty_list():
    endpoint = FakeEndpoint("not json at all")
    assert get_prompt_feedback("Some prompt", endpoint) == []


def test_examples_are_included_in_the_sent_prompt():
    endpoint = FakeEndpoint({"feedback": []})
    get_prompt_feedback(
        "Some prompt", endpoint,
        examples=[{"text": "ugh this is broken", "llm_label": "negative",
                    "confidence": 0.4, "reasoning": "unclear sarcasm"}])
    assert "ugh this is broken" in endpoint.prompts[0]
    assert "unclear sarcasm" in endpoint.prompts[0]


def test_non_dict_feedback_items_are_dropped():
    endpoint = FakeEndpoint({"feedback": ["not a dict", {"issue": "ok"}]})
    result = get_prompt_feedback("Some prompt", endpoint)
    assert len(result) == 1
    assert result[0]["issue"] == "ok"
