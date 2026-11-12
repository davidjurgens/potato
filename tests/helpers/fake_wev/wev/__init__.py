"""A stand-in for the wev package (OpenJev), for openjev-finetune's tests.

``load`` returns a model that answers "positive" when the text says "good";
``wev.cli train`` records what it was given and prints wev's log lines.
"""


class _Model:
    def predict(self, state, questions, model=None):
        text = state["text"] if isinstance(state, dict) else str(state)
        answers = {}
        for qid, q in questions.items():
            keys = list(q["criteria"])
            pick = keys[0] if "good" in text else keys[-1]
            probs = {k: (0.8 if k == pick else 0.2 / max(1, len(keys) - 1))
                     for k in keys}
            answers[qid] = {"type": "choice", "choice": pick,
                            "probabilities": probs, "confidence": 0.5}
        return {"model": "fake", "answers": answers, "usage": {}}


def load(path, device=None):
    return _Model()
