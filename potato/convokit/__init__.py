"""
ConvoKit corpus support for Potato.

`ConvoKit <https://convokit.cornell.edu/>`_ (Cornell) is the standard toolkit for
conversational analysis: 40-odd downloadable corpora (Conversations Gone Awry,
Switchboard, Wikipedia Politeness, Supreme Court, Friends, Reddit, ...) and a
library of transformers that work by *adding metadata* to utterances,
conversations, and speakers. It analyzes conversations well but has no annotation
interface. Potato has the annotation interface. This package is the bridge.

.. note::

   This is ``potato.convokit`` — it is **not** the ``convokit`` package on PyPI,
   and it does not import it. That package pulls in spacy, torch, scikit-learn,
   and pymongo; Potato's boot path deliberately stays free of the ML stack. The
   corpus format is small and stable, so this package reads and writes it with
   the standard library alone. Do not "fix" the name by aliasing the two.

The round trip::

    potato convokit conversations-gone-awry-corpus -o data/awry.jsonl
    potato start config.yaml -p 8000            # annotate
    python -m potato.export --config config.yaml --format convokit -o out/

The linchpin is ``turn_id``. Each Potato turn carries the real ConvoKit utterance
id as its ``turn_id``, which the turn-level annotation framework
(:mod:`potato.server_utils.turn_annotations`) already uses as its storage key. So
per-turn annotations come back keyed by genuine utterance ids, and exporting them
into ConvoKit metadata is a direct mapping rather than a reconciliation.
"""

from .reader import (
    BIN_DELIM_L,
    BIN_DELIM_R,
    DEFAULT_DROPPED_META,
    Conversation,
    Corpus,
    ConvoKitReadError,
    Utterance,
    iter_utterance_lines,
    read_corpus,
    resolve_corpus_dir,
)
from .schema import CorpusIndex

__all__ = [
    "BIN_DELIM_L",
    "BIN_DELIM_R",
    "DEFAULT_DROPPED_META",
    "Conversation",
    "Corpus",
    "ConvoKitReadError",
    "CorpusIndex",
    "Utterance",
    "iter_utterance_lines",
    "read_corpus",
    "resolve_corpus_dir",
]
