/**
 * BERT WordPiece tokenizer, enough of it to prompt an open-vocabulary detector.
 *
 * WHY WE IMPLEMENT THIS RATHER THAN SHIP A LIBRARY
 * ------------------------------------------------
 * The obvious alternative is transformers.js, which is ~2 MB of JavaScript to
 * do one job we need: turn "a cat . a dog ." into token ids. Potato vendors its
 * frontend dependencies and serves them from disk for air-gapped installs, so
 * every megabyte is a megabyte an administrator has to copy. A WordPiece
 * tokenizer is ~150 lines and its correctness is checkable against the
 * canonical implementation, which is what `tests/unit/test_wordpiece_bridge.py`
 * does — the JS runs in Node and its output is compared token for token with
 * HuggingFace `tokenizers` on the same vocabulary.
 *
 * WHY THE TOKENIZER IS WORTH TESTING THAT HARD
 * --------------------------------------------
 * Grounding DINO decides which phrase a box belongs to by looking at which
 * TOKEN POSITIONS score highest for that box. Get the tokenization subtly
 * wrong — a stray accent, a missed punctuation split, an off-by-one from the
 * [CLS] token — and every box comes back attributed to the wrong phrase, with
 * no error anywhere. The boxes look right. The labels are silently scrambled.
 *
 * WHAT THIS SUPPORTS
 * ------------------
 * Uncased BERT vocabularies with `##` continuations, which is what Grounding
 * DINO ships. Chinese character segmentation is included because the
 * normalizer config enables it and prompts in Chinese would otherwise tokenize
 * as one enormous unknown word.
 */

(function (global) {
    'use strict';

    const CLS = '[CLS]';
    const SEP = '[SEP]';
    const UNK = '[UNK]';
    const MAX_CHARS_PER_WORD = 100;

    /** Codepoint ranges the BERT normalizer treats as CJK. */
    function isChineseChar(cp) {
        return (cp >= 0x4E00 && cp <= 0x9FFF)
            || (cp >= 0x3400 && cp <= 0x4DBF)
            || (cp >= 0x20000 && cp <= 0x2A6DF)
            || (cp >= 0x2A700 && cp <= 0x2B73F)
            || (cp >= 0x2B740 && cp <= 0x2B81F)
            || (cp >= 0x2B820 && cp <= 0x2CEAF)
            || (cp >= 0xF900 && cp <= 0xFAFF)
            || (cp >= 0x2F800 && cp <= 0x2FA1F);
    }

    /**
     * BERT's punctuation rule, which is wider than Unicode's P category: it
     * also counts the ASCII symbol ranges. Using only /\p{P}/ splits "a-b" but
     * not "a+b", and the vocabulary was built with both split.
     */
    function isPunctuation(ch) {
        const cp = ch.codePointAt(0);
        if ((cp >= 33 && cp <= 47) || (cp >= 58 && cp <= 64)
            || (cp >= 91 && cp <= 96) || (cp >= 123 && cp <= 126)) {
            return true;
        }
        return /\p{P}|\p{S}/u.test(ch);
    }

    function isControl(ch) {
        if (ch === '\t' || ch === '\n' || ch === '\r') return false;
        return /\p{Cc}|\p{Cf}/u.test(ch);
    }

    function isWhitespace(ch) {
        return ch === ' ' || ch === '\t' || ch === '\n' || ch === '\r'
            || /\s/u.test(ch);
    }

    /** Strip control characters and normalise whitespace, then split CJK. */
    function cleanText(text) {
        let out = '';
        for (const ch of String(text)) {
            const cp = ch.codePointAt(0);
            if (cp === 0 || cp === 0xFFFD || isControl(ch)) continue;
            if (isWhitespace(ch)) { out += ' '; continue; }
            if (isChineseChar(cp)) { out += ` ${ch} `; continue; }
            out += ch;
        }
        return out;
    }

    /**
     * Lowercase and drop combining marks.
     *
     * `strip_accents` is null in the config, which in HuggingFace means "follow
     * lowercase" — so an uncased model strips accents. Skipping this maps
     * "café" to [UNK] instead of "cafe".
     */
    function normalize(text) {
        return text.toLowerCase().normalize('NFD')
            .replace(/\p{Mn}/gu, '');
    }

    /** Whitespace split, then peel punctuation into its own tokens. */
    function basicTokenize(text) {
        const words = cleanText(text).split(' ').filter(Boolean);
        const tokens = [];
        words.forEach((word) => {
            const normalized = normalize(word);
            let current = '';
            for (const ch of normalized) {
                if (isPunctuation(ch)) {
                    if (current) { tokens.push(current); current = ''; }
                    tokens.push(ch);
                } else {
                    current += ch;
                }
            }
            if (current) tokens.push(current);
        });
        return tokens;
    }

    class WordPieceTokenizer {
        /**
         * @param {Map<string, number>|object} vocab token -> id
         */
        constructor(vocab) {
            this.vocab = vocab instanceof Map
                ? vocab
                : new Map(Object.entries(vocab || {}));
        }

        /** Build from the lines of a `vocab.txt`, which is index-ordered. */
        static fromVocabText(text) {
            const vocab = new Map();
            String(text).split('\n').forEach((line, index) => {
                const token = line.replace(/\r$/, '');
                // A vocabulary has no blank entries, but a trailing newline
                // produces one, and adding it would shift nothing yet map ''
                // to a real id.
                if (token.length) vocab.set(token, index);
            });
            return new WordPieceTokenizer(vocab);
        }

        /** Greedy longest-match-first, the standard WordPiece algorithm. */
        wordpiece(word) {
            if (word.length > MAX_CHARS_PER_WORD) return [UNK];
            const pieces = [];
            let start = 0;
            while (start < word.length) {
                let end = word.length;
                let found = null;
                while (start < end) {
                    const piece = start > 0
                        ? `##${word.slice(start, end)}`
                        : word.slice(start, end);
                    if (this.vocab.has(piece)) { found = piece; break; }
                    end -= 1;
                }
                // One unmatchable character makes the WHOLE word unknown, which
                // is what the reference does; emitting per-character [UNK]s
                // would shift every later token position.
                if (found === null) return [UNK];
                pieces.push(found);
                start = end;
            }
            return pieces;
        }

        /**
         * @param {string} text
         * @param {boolean} [addSpecial=true] wrap in [CLS] ... [SEP]
         * @returns {{tokens: string[], ids: number[], attentionMask: number[],
         *            tokenTypeIds: number[]}}
         */
        encode(text, addSpecial = true) {
            const tokens = [];
            if (addSpecial) tokens.push(CLS);
            basicTokenize(text).forEach((word) => {
                this.wordpiece(word).forEach((piece) => tokens.push(piece));
            });
            if (addSpecial) tokens.push(SEP);

            const unkId = this.vocab.has(UNK) ? this.vocab.get(UNK) : 0;
            const ids = tokens.map(
                (t) => (this.vocab.has(t) ? this.vocab.get(t) : unkId));
            return {
                tokens,
                ids,
                attentionMask: ids.map(() => 1),
                tokenTypeIds: ids.map(() => 0),
            };
        }
    }

    const api = { WordPieceTokenizer, basicTokenize, normalize, cleanText };
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    }
    if (global) {
        global.WordPieceTokenizer = WordPieceTokenizer;
    }
})(typeof window !== 'undefined' ? window : this);
