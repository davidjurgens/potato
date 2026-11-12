"""
Survey-experiment question designs for sensitive questions.

``list_experiment`` (the item count technique): a list of statements and the
question "How many of these apply to you?". Participants in the treatment
condition also see the sensitive statement; the difference between the mean
counts of the two groups estimates how common it is, without anyone saying
which statements apply to them.

.. code-block:: yaml

    conditions:
      factors: {list_group: [control, treatment]}
    annotation_schemes:
      - annotation_type: list_experiment
        name: lists
        description: How many of these statements are true for you?
        items: [I own a bicycle., I have been to a concert this year., I read a newspaper daily.]
        sensitive_item: I have driven after drinking in the last year.
        treatment: {factor: list_group, level: treatment}

``randomized_response`` (Warner 1965 and its successors): the participant
uses a private randomizer, so a "yes" does not reveal their own answer, and
the prevalence is estimated from the known randomization probabilities.

* ``method: forced_response``: with probability ``p_truth`` answer the
  question truthfully, with ``p_yes`` answer yes, with ``p_no`` answer no.
* ``method: crosswise`` (Yu, Tian & Tang 2008): two statements, the
  sensitive one and a non-sensitive one with known prevalence
  ``nonsensitive_prevalence``; the participant says only whether both or
  neither are true, or exactly one.

Both are stored like their underlying question (a number, or the chosen
option), and the ``survey_experiments`` export computes the estimates.
"""

from .survey_experiment_common import CROSSWISE_LABELS, DEFAULT_P, DEFAULT_RANDOMIZER  # noqa: F401
from .list_experiment import generate_list_experiment_layout  # noqa: F401
from .randomized_response import generate_randomized_response_layout  # noqa: F401
