"""Live Laya check: loads the real convaiinnovations/laya on CPU.

Opt-in (POTATO_LAYA_LIVE=1): the first run downloads ~1.7 GB of weights.
"""

import importlib.util
import os
import time

import pytest

pytestmark = [
    pytest.mark.skipif(importlib.util.find_spec("laya") is None, reason="laya not installed"),
    pytest.mark.skipif(os.environ.get("POTATO_LAYA_LIVE") != "1",
                       reason="set POTATO_LAYA_LIVE=1 to load the real Laya model"),
]

CASES = [
    ("I absolutely loved this movie, it was wonderful from start to finish!", "positive"),
    ("This was the worst meal I have ever had. Disgusting and rude staff.", "negative"),
    ("The meeting is scheduled for 3pm on Tuesday in room 204.", "neutral"),
]


def test_laya_classifies_obvious_sentiment():
    from potato.ai.decision_endpoint import questions_for_scheme
    from potato.ai.laya_endpoint import LayaEndpoint

    ep = LayaEndpoint({"ai_config": {"device": "cpu"}})
    questions = questions_for_scheme(
        {"annotation_type": "radio", "name": "sentiment",
         "description": "What is the sentiment of this text?",
         "labels": ["positive", "negative", "neutral"]},
        "Classify the sentiment expressed by the writer.")

    ep.decide("warm-up", questions)  # load the model outside the timing
    timings = []
    for text, expected in CASES:
        start = time.perf_counter()
        (answer,) = ep.decide(text, questions)
        timings.append(time.perf_counter() - start)
        assert sum(answer.probabilities.values()) == pytest.approx(1.0, abs=1e-3)
        assert 0.0 <= answer.confidence <= 1.0
        assert answer.value == expected, (text, answer)
    print(f"\nlaya CPU latency per question: "
          f"{', '.join(f'{t * 1000:.0f} ms' for t in timings)}")
