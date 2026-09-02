"""
The JavaScript tokenizer against the canonical one, token for token.

WHY THIS TEST EXISTS
--------------------
Grounding DINO attributes each predicted box to a phrase by looking at which
TOKEN POSITIONS score highest for that box. A tokenizer that is subtly wrong —
one missed punctuation split, one un-stripped accent, an off-by-one from
[CLS] — produces boxes in the right places carrying the WRONG LABELS, with no
error anywhere. Nothing downstream can detect that, so it has to be caught
here.

Potato implements WordPiece in JavaScript rather than shipping transformers.js
(~2 MB for one function, on a codebase that vendors its assets for air-gapped
installs). The price of that decision is this test: the shipped JS runs in Node
and its output is compared against HuggingFace `tokenizers` on the same
vocabulary file.

Skipped unless the model is installed, because the vocabulary is part of the
download. A vacuous pass would be worse than a skip.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
JS = REPO / "potato" / "static" / "segmentation" / "wordpiece.js"
MODEL_DIR = REPO / "potato" / "models" / "grounding_dino_tiny"
VOCAB = MODEL_DIR / "vocab.txt"
TOKENIZER_JSON = MODEL_DIR / "tokenizer.json"

pytestmark = pytest.mark.skipif(
    not VOCAB.exists() or not TOKENIZER_JSON.exists(),
    reason="grounding_dino_tiny is not installed "
           "(potato download-models grounding_dino_tiny)",
)

#: Prompts chosen to exercise what actually breaks: multi-word phrases that
#: split into subwords, the period separator Grounding DINO needs, accents,
#: hyphens, digits, casing, and a word no vocabulary contains.
PROMPTS = [
    "cat . dog .",
    "traffic light . fire hydrant .",
    "a person riding a skateboard .",
    "café . jalapeño .",
    "x-ray machine . t-shirt .",
    "COVID-19 test kit .",
    # Emoji and runes are the real unknown case. "zzzqqxv" looks unknown and
    # is not: BERT's vocabulary covers every single letter, so it decomposes
    # into z / ##zz / ##q / ##q / ##x / ##v.
    "🦄 .",
    "ᚠᚢᚦ .",
    "person. bicycle. car.",
    "  spaced   out   words  .",
    "1080p monitor . 3d printer .",
]


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available")
    return node


def _js_encode(prompts):
    """Run the shipped tokenizer in Node and return its output."""
    script = f"""
    const fs = require('fs');
    const {{ WordPieceTokenizer }} = require({str(JS)!r});
    const vocab = fs.readFileSync({str(VOCAB)!r}, 'utf8');
    const tok = WordPieceTokenizer.fromVocabText(vocab);
    const prompts = {json.dumps(PROMPTS)};
    const out = prompts.map((p) => {{
        const e = tok.encode(p);
        return {{ tokens: e.tokens, ids: e.ids,
                 attention: e.attentionMask, types: e.tokenTypeIds }};
    }});
    process.stdout.write(JSON.stringify(out));
    """
    result = subprocess.run([_node(), "-e", script], capture_output=True,
                            text=True, timeout=120)
    if result.returncode != 0:
        pytest.fail(f"node failed: {result.stderr[:2000]}")
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def js_output():
    return _js_encode(PROMPTS)


@pytest.fixture(scope="module")
def reference():
    tokenizers = pytest.importorskip("tokenizers")
    tok = tokenizers.Tokenizer.from_file(str(TOKENIZER_JSON))
    return [tok.encode(p) for p in PROMPTS]


class TestTokenizerParity:
    def test_tokens_match_the_reference_exactly(self, js_output, reference):
        for prompt, ours, theirs in zip(PROMPTS, js_output, reference):
            assert ours["tokens"] == theirs.tokens, (
                f"tokenization diverged for {prompt!r}:\n"
                f"  ours:   {ours['tokens']}\n"
                f"  theirs: {theirs.tokens}"
            )

    def test_ids_match_the_reference_exactly(self, js_output, reference):
        for prompt, ours, theirs in zip(PROMPTS, js_output, reference):
            assert ours["ids"] == theirs.ids, f"ids diverged for {prompt!r}"

    def test_attention_and_type_ids_match(self, js_output, reference):
        for ours, theirs in zip(js_output, reference):
            assert ours["attention"] == theirs.attention_mask
            assert ours["types"] == theirs.type_ids

    def test_every_prompt_is_wrapped_in_cls_and_sep(self, js_output):
        for ours in js_output:
            assert ours["tokens"][0] == "[CLS]"
            assert ours["tokens"][-1] == "[SEP]"

    def test_an_unknown_word_becomes_a_single_unk(self, js_output):
        """One unmatchable word must not become several tokens.

        Emitting per-character [UNK]s would still 'work' — and would shift
        every later token position, silently re-attributing every phrase after
        it.
        """
        index = PROMPTS.index("🦄 .")
        assert js_output[index]["tokens"].count("[UNK]") == 1
        assert js_output[PROMPTS.index("ᚠᚢᚦ .")]["tokens"].count("[UNK]") == 1

    def test_accents_are_stripped_rather_than_unknown(self, js_output):
        index = PROMPTS.index("café . jalapeño .")
        tokens = js_output[index]["tokens"]
        assert "[UNK]" not in tokens, tokens
        assert "cafe" in tokens


class TestControls:
    """Deliberately wrong tokenizers must fail, or the parity test proves little."""

    def test_skipping_accent_stripping_diverges(self, reference):
        """Proves the accent case is load-bearing rather than incidental."""
        script = f"""
        const fs = require('fs');
        const path = {str(JS)!r};
        let src = fs.readFileSync(path, 'utf8');
        // Neuter the accent stripper, keeping everything else.
        src = src.replace(".replace(/\\\\p{{Mn}}/gu, '')", "");
        const module = {{ exports: {{}} }};
        (new Function('module', 'exports', 'window', src))(
            module, module.exports, undefined);
        const tok = module.exports.WordPieceTokenizer.fromVocabText(
            fs.readFileSync({str(VOCAB)!r}, 'utf8'));
        process.stdout.write(JSON.stringify(tok.encode("café . jalapeño .").tokens));
        """
        result = subprocess.run([_node(), "-e", script], capture_output=True,
                                text=True, timeout=120)
        assert result.returncode == 0, result.stderr[:1000]
        broken = json.loads(result.stdout)
        index = PROMPTS.index("café . jalapeño .")
        assert broken != reference[index].tokens, (
            "removing accent stripping changed nothing, so the parity test "
            "would not have caught it"
        )
