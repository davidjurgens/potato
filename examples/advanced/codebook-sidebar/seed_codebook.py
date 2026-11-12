#!/usr/bin/env python
"""Seed this example's codebook with full per-code entries.

`potato codebook <config>` (and the server's own first-run bootstrap) creates a
code per YAML label, but a label list carries only *names*. The content that
makes a codebook worth opening — the definition, the inclusion and exclusion
criteria, the examples that settled past disagreements — lives in typed content
blocks, which is what this script writes.

Idempotent: re-running replaces each code's blocks with the same content.

    python examples/advanced/codebook-sidebar/seed_codebook.py
"""

from __future__ import annotations

import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..")))

from potato.codebook import create_code                       # noqa: E402
from potato.codebook.codebook import Codebook                 # noqa: E402
from potato.codebook.content_service import save_scope        # noqa: E402
from potato.codebook.service import DuplicateCodeError        # noqa: E402
from potato.codebook import blocks as cb_blocks               # noqa: E402


# Block types come from potato/codebook/blocks.py: short_def, definition,
# use_when, avoid_when, example, counter_example, rationale, keywords, notes.
ENTRIES = {
    "Polite": [
        ("short_def",
         "The writer does visible work to lower the imposition on the reader."),
        ("definition",
         "A message is Polite when it contains at least one marker whose only "
         "job is to make the request easier to receive: a hedge, thanks or an "
         "apology for asking, an explicit release of time pressure, or an "
         "offer that costs the writer something."),
        ("use_when",
         "- Hedging: *when you get a chance*, *if you have a moment*, *no rush*\n"
         "- Gratitude or apology for the ask itself\n"
         "- An offer that absorbs the reader's work\n"
         "- Explicit release of pressure: *this is not blocking me*"),
        ("avoid_when",
         "The message is merely inoffensive. Absence of rudeness is **Neutral**, "
         "not Polite — this is the most common over-application of this code."),
        ("example",
         "> Hi Sam, could you send me the Q3 report when you get a chance? "
         "No rush at all — thanks so much!\n\n"
         "Hedge, release of time pressure, and thanks: three markers."),
        ("counter_example",
         "> Please send the Q3 report.\n\n"
         "*Please* is not softening work; it is the ordinary register of a "
         "request. **Neutral**."),
        ("keywords",
         "when you get a chance, no rush, if you have a moment, sorry to ask, "
         "happy to, whenever works"),
    ],
    "Neutral": [
        ("short_def",
         "Plain business. No softening, but nothing that stings."),
        ("definition",
         "The default for workplace messages. The writer states what they need "
         "without doing extra work to soften it and without any cue that would "
         "make a reasonable peer wince. In the pilot, 61% of real messages "
         "landed here."),
        ("use_when",
         "- Bare imperatives with no pressure cue\n"
         "- Deadlines stated as information, with a reason\n"
         "- Messages that are only a link or a file\n"
         "- Templates and autoreplies\n"
         "- Anything you are genuinely torn about (rule 5)"),
        ("avoid_when",
         "There is a clear pressure cue — a deadline used as leverage rather "
         "than as information, a pointed reminder, or an accusation."),
        ("example",
         "> Send me the slides before the meeting.\n\n"
         "Terse, but no pressure cue and nothing that stings. This item "
         "accounted for 38% of round-1 adjudicated conflicts; see rule 2."),
        ("counter_example",
         "> I need this by 3pm. I have already told you twice.\n\n"
         "The reminder is a reproach. **Impolite**."),
        ("notes",
         "If you are using Neutral rarely, re-read rule 2 (terse is not "
         "impolite). Under-use of Neutral is the strongest single predictor of "
         "low agreement with the adjudicated set."),
    ],
    "Impolite": [
        ("short_def",
         "The message would make a reasonable peer wince."),
        ("definition",
         "The writer imposes on the reader in a way that carries a social cost: "
         "by mocking, blaming, pressuring, or publicly exposing them. Judge the "
         "message as sent to a peer — not to someone you manage."),
        ("use_when",
         "- Sarcasm, **including sarcastic politeness markers**\n"
         "- Blame or accusation: *you never told me*\n"
         "- Pointed reminders: *third time asking*\n"
         "- Public callouts: naming a failure in a channel rather than a DM\n"
         "- A deadline invoked to pressure rather than to inform"),
        ("avoid_when",
         "The message is only *terse*. Brevity on its own is Neutral (rule 2). "
         "All-caps, missing punctuation and typos are out of scope (rule 4), "
         "and a trailing emoji neither upgrades nor downgrades (rule 6)."),
        ("example",
         "> Thanks so much for finally getting to this.\n\n"
         "Contains a genuine thank-you and is still Impolite: *finally* turns "
         "it into a reproach. Read to the end before labeling (rule 3)."),
        ("counter_example",
         "> can you fix this 🙂\n\n"
         "A bare request with an emoji. The emoji is tone-neutral, so this is "
         "**Neutral** (rule 6, added in codebook v2.3)."),
        ("keywords",
         "finally, third time, as I said, you never, per my last message"),
    ],
}


def main() -> int:
    with open(os.path.join(HERE, "config.yaml"), "rt", encoding="utf-8") as fh:
        config = yaml.safe_load(fh)

    # task_dir is resolved relative to the config file, exactly as the server
    # resolves it — otherwise the script seeds a codebook the server never reads.
    task_dir = os.path.normpath(
        os.path.join(HERE, config.get("task_dir", ".")))
    project = config["annotation_task_name"]

    for name in ENTRIES:
        try:
            create_code(task_dir, project=project, name=name,
                        created_by="seed_codebook.py")
        except DuplicateCodeError:
            pass

    cb = Codebook.load(task_dir, project)
    ids = cb.label_to_id()

    for name, entry in ENTRIES.items():
        code_id = ids.get(name)
        if not code_id:
            print(f"  ! no code id for {name!r}; skipping")
            continue
        version = cb_blocks.scope_version(
            task_dir, project, code_id=code_id, section=cb_blocks.NO_SECTION)
        save_scope(
            task_dir, project=project, scope_kind="code", scope_id=code_id,
            base_version=version, actor="seed_codebook.py", actor_kind="human",
            blocks_in=[{"block_type": bt, "body_md": body}
                       for bt, body in entry])
        print(f"  seeded {name!r}: {len(entry)} blocks")

    print(f"\nCodebook written under {task_dir}. Now start the server:")
    print("  python potato/flask_server.py start "
          "examples/advanced/codebook-sidebar/config.yaml -p 8000")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
