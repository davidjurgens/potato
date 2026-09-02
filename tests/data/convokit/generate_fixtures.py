"""
Generate the miniature ConvoKit corpora used by the ConvoKit reader tests.

Run from the repo root::

    python tests/data/convokit/generate_fixtures.py

The generated corpora are committed, so this script exists to document *how* each
fixture is shaped and to regenerate them if the format understanding changes — it
is not run by the test suite.

Each fixture isolates one axis of real-world format variation, all of which was
confirmed against ConvoKit ``master`` and against real downloaded corpora:

``mini-modern``
    The current format: ``speaker`` / ``conversation_id`` / ``reply-to``,
    ``speakers.json``, and an ``index.json`` whose values are **lists**. Carries a
    ``parsed`` blob (dropped by default) and an ``info.extra_score.jsonl`` overlay.

``mini-legacy``
    The same conversations in the pre-rename format: ``user`` / ``root``,
    ``users.json``, ``users-index``, and index values that are **bare strings**.
    ``wikipedia-politeness-corpus`` is still shipped this way.

``mini-bin``
    One field indexed ``["bin"]`` whose values are ``<##bin{N}&&@**>`` markers
    into a pickle sidecar. The pickle holds a plain list of dicts, so it is safe
    to unpickle in tests while still exercising the real code path.

``mini-broken``
    A reply-to cycle, a dangling ``reply_to``, a null timestamp, a duplicate id,
    and no ``speakers.json`` — everything the reader must survive rather than
    crash on.

``mini-underscore``
    Uses ``reply_to`` (underscore) instead of ``reply-to``. Real Reddit-derived
    corpora do this; upstream has an explicit workaround for it.

``mini-modern.zip``
    ``mini-modern`` zipped with the usual single top-level directory, for the
    archive input path.
"""

from __future__ import annotations

import json
import os
import pickle
import shutil
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))

# A tiny Wikipedia-talk-shaped thread: a root, two direct replies, and a reply to
# the first reply. Enough to exercise depth, sibling ordering, and DFS pre-order.
THREAD = [
    # (id, speaker, text, reply_to, timestamp)
    ("c0", "alice", "Should we rename this article?", None, 1000.0),
    ("c1", "bob", "I don't think the current title is common usage.", "c0", 1200.0),
    ("c2", "carol", "Agreed, the sources use the short form.", "c0", 1100.0),
    ("c3", "alice", "Fair enough, let's move it.", "c1", 1300.0),
]

# A second, flat two-turn conversation.
THREAD_2 = [
    ("d0", "dave", "Reverting your edit, see the talk page.", None, 2000.0),
    ("d1", "erin", "That revert was not justified.", "d0", 2100.0),
]

PARSED_BLOB = [
    {"rt": 0, "toks": [{"tok": "Should", "tag": "MD", "dep": "aux", "up": 1, "dn": []}]}
]


def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)


def _fresh(name):
    path = os.path.join(HERE, name)
    if os.path.isdir(path):
        shutil.rmtree(path)
    os.makedirs(path)
    return path


def build_modern():
    d = _fresh("mini-modern")
    rows = []
    for i, (uid, speaker, text, reply_to, ts) in enumerate(THREAD + THREAD_2):
        convo_id = "c0" if uid.startswith("c") else "d0"
        meta = {
            "is_section_header": uid in ("c0", "d0"),
            "toxicity": round(0.05 * i, 4),
            "stance": "support" if i % 2 == 0 else "oppose",
        }
        if uid == "c0":
            # The field that must be dropped by default.
            meta["parsed"] = PARSED_BLOB
        rows.append(
            {
                "id": uid,
                "conversation_id": convo_id,
                "text": text,
                "speaker": speaker,
                "meta": meta,
                "reply-to": reply_to,
                "timestamp": ts,
            }
        )
    _write_jsonl(os.path.join(d, "utterances.jsonl"), rows)

    # Speakers: a mix of the wrapped and bare forms, both of which occur.
    _write_json(
        os.path.join(d, "speakers.json"),
        {
            "alice": {"meta": {"editor_since": 2004}, "vectors": []},
            "bob": {"editor_since": 2011},
            "carol": {"meta": {}, "vectors": []},
            "dave": {},
            # 'erin' is deliberately absent -> reader synthesizes an empty dict.
        },
    )
    _write_json(
        os.path.join(d, "conversations.json"),
        {
            "c0": {
                "meta": {
                    "page_title": "Talk:Example",
                    "derailed": False,
                    "split": "train",
                },
                "vectors": [],
            },
            "d0": {"page_title": "Talk:Another", "derailed": True, "split": "test"},
        },
    )
    _write_json(os.path.join(d, "corpus.json"), {"source": "synthetic", "num_convos": 2})
    # Modern index: values are LISTS.
    _write_json(
        os.path.join(d, "index.json"),
        {
            "utterances-index": {
                "is_section_header": ["<class 'bool'>"],
                "toxicity": ["<class 'float'>"],
                "stance": ["<class 'str'>"],
                "parsed": ["<class 'list'>"],
            },
            "speakers-index": {"editor_since": ["<class 'int'>"]},
            "conversations-index": {
                "page_title": ["<class 'str'>"],
                "derailed": ["<class 'bool'>"],
                "split": ["<class 'str'>"],
            },
            "overall-index": {},
            "version": 3,
        },
    )
    # An overlay, in exactly the shape convokit's load_info expects.
    _write_jsonl(
        os.path.join(d, "info.extra_score.jsonl"),
        [{"id": "c1", "value": 0.9}, {"id": "c3", "value": 0.1}, {"id": "nope", "value": 1}],
    )
    return d


def build_legacy():
    d = _fresh("mini-legacy")
    rows = []
    for uid, speaker, text, reply_to, ts in THREAD:
        rows.append(
            {
                "id": uid,
                "root": "c0",
                "text": text,
                "user": speaker,
                "meta": {"Binary": 1 if uid != "c0" else -1},
                "reply-to": reply_to,
                "timestamp": ts,
            }
        )
    _write_jsonl(os.path.join(d, "utterances.jsonl"), rows)
    _write_json(
        os.path.join(d, "users.json"),
        {"alice": {}, "bob": {}, "carol": {}},
    )
    _write_json(os.path.join(d, "conversations.json"), {"c0": {"page_title": "Talk:Legacy"}})
    _write_json(os.path.join(d, "corpus.json"), {})
    # Legacy index: values are BARE STRINGS, speaker index is 'users-index'.
    _write_json(
        os.path.join(d, "index.json"),
        {
            "utterances-index": {"Binary": "<class 'int'>"},
            "users-index": {},
            "conversations-index": {"page_title": "<class 'str'>"},
            "overall-index": {},
            "version": 1,
        },
    )
    return d


def build_bin():
    d = _fresh("mini-bin")
    # A plain list of dicts - safe to unpickle, but reached through the real
    # marker-resolution path.
    payload = [{"annotator": "a1", "score": 3}, {"annotator": "a2", "score": 5}]
    with open(os.path.join(d, "Annotations-bin.p"), "wb") as f:
        pickle.dump(payload, f)

    rows = [
        {
            "id": "b0",
            "conversation_id": "b0",
            "text": "First request.",
            "speaker": "alice",
            "meta": {"Annotations": "<##bin{0}&&@**>", "Binary": 1},
            "reply-to": None,
            "timestamp": 10.0,
        },
        {
            "id": "b1",
            "conversation_id": "b0",
            "text": "Second request.",
            "speaker": "bob",
            "meta": {"Annotations": "<##bin{1}&&@**>", "Binary": -1},
            "reply-to": "b0",
            "timestamp": 20.0,
        },
    ]
    _write_jsonl(os.path.join(d, "utterances.jsonl"), rows)
    _write_json(os.path.join(d, "speakers.json"), {"alice": {}, "bob": {}})
    _write_json(os.path.join(d, "conversations.json"), {"b0": {}})
    _write_json(os.path.join(d, "corpus.json"), {})
    _write_json(
        os.path.join(d, "index.json"),
        {
            "utterances-index": {"Annotations": "bin", "Binary": "<class 'int'>"},
            "speakers-index": {},
            "conversations-index": {},
            "overall-index": {},
            "version": 1,
        },
    )
    return d


def build_broken():
    d = _fresh("mini-broken")
    rows = [
        # Dangling reply_to: 'missing' is not in the corpus.
        {
            "id": "x0",
            "conversation_id": "x0",
            "text": "Orphan reply.",
            "speaker": "alice",
            "meta": {},
            "reply-to": "missing",
            "timestamp": None,
        },
        # A two-node cycle: x1 <-> x2.
        {
            "id": "x1",
            "conversation_id": "x0",
            "text": "Cycle A.",
            "speaker": "bob",
            "meta": {},
            "reply-to": "x2",
            "timestamp": None,
        },
        {
            "id": "x2",
            "conversation_id": "x0",
            "text": "Cycle B.",
            "speaker": "bob",
            "meta": {},
            "reply-to": "x1",
            "timestamp": 5.0,
        },
        # Duplicate id - the reader keeps the first.
        {
            "id": "x0",
            "conversation_id": "x0",
            "text": "Duplicate, should be ignored.",
            "speaker": "carol",
            "meta": {},
            "reply-to": None,
            "timestamp": 6.0,
        },
    ]
    _write_jsonl(os.path.join(d, "utterances.jsonl"), rows)
    # No speakers.json at all.
    _write_json(os.path.join(d, "conversations.json"), {})
    # No corpus.json, no index.json either.
    return d


def build_underscore():
    d = _fresh("mini-underscore")
    rows = [
        {
            "id": "u0",
            "conversation_id": "u0",
            "text": "Root post.",
            "speaker": "alice",
            "meta": {},
            "reply_to": None,
            "timestamp": 1.0,
        },
        {
            "id": "u1",
            "conversation_id": "u0",
            "text": "A reply.",
            "speaker": "bob",
            "meta": {},
            "reply_to": "u0",
            "timestamp": 2.0,
        },
    ]
    _write_jsonl(os.path.join(d, "utterances.jsonl"), rows)
    _write_json(os.path.join(d, "speakers.json"), {"alice": {}, "bob": {}})
    _write_json(os.path.join(d, "conversations.json"), {"u0": {}})
    _write_json(os.path.join(d, "corpus.json"), {})
    return d


def build_zip(modern_dir):
    """Zip mini-modern the way ConvoKit's CDN does: one top-level directory."""
    out = os.path.join(HERE, "mini-modern.zip")
    if os.path.exists(out):
        os.remove(out)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(os.listdir(modern_dir)):
            zf.write(os.path.join(modern_dir, name), arcname=f"mini-modern/{name}")
    return out


def main():
    modern = build_modern()
    build_legacy()
    build_bin()
    build_broken()
    build_underscore()
    build_zip(modern)
    print("Wrote ConvoKit fixtures to", HERE)


if __name__ == "__main__":
    main()
