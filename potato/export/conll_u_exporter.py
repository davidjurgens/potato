"""
CoNLL-U Exporter

Exports span annotations to CoNLL-U format:
- 10 columns: ID FORM LEMMA UPOS XPOS FEATS HEAD DEPREL DEPS MISC
- NER annotations placed in MISC column as SpaceAfter/NER features
- HEAD and DEPREL from a directed span_link scheme over the exported spans,
  when the project has one (head span first, the way Potato stores a
  dependency): a span's first token is attached to its head span's first
  token, and a span with no head is the root. Otherwise ``_``.
- Blank lines between sentences
- Comment lines with sent_id and text
"""

import os
import logging
from typing import Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult
from .nlp_utils import annotator_groups, conll_documents

logger = logging.getLogger(__name__)


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name) or "_"


def _dependency_scheme(schemas, schema_name: str, chosen: Optional[str]) -> Optional[str]:
    """The span_link scheme that holds dependencies over *schema_name*:
    the ``link_schema`` option, or the first directed span_link scheme
    drawing on those spans."""
    for scheme in schemas:
        if scheme.get("annotation_type") != "span_link" \
                or scheme.get("span_schema") != schema_name:
            continue
        if chosen:
            if scheme.get("name") == chosen:
                return chosen
            continue
        if any(t.get("directed") for t in scheme.get("link_types") or []
               if isinstance(t, dict)):
            return scheme.get("name")
    return None


def _offsets(span) -> Optional[Tuple[int, int]]:
    try:
        return int(span["start"]), int(span["end"])
    except (KeyError, TypeError, ValueError):
        return None


def _dependencies(record, schema_name: str, link_schema: Optional[str]):
    """``(heads, spans)`` for one record: dependent span offsets to (head
    span offsets, relation), and every span's offsets."""
    spans = (record.get("spans") or {}).get(schema_name) or []
    by_id = {sp.get("id"): _offsets(sp) for sp in spans if sp.get("id")}
    heads = {}
    for link in ((record.get("links") or {}).get(link_schema) or []) if link_schema else []:
        ids = link.get("span_ids") or []
        if link.get("direction") != "directed" or len(ids) != 2:
            continue
        positions = (link.get("properties") or {}).get("span_positions") or []
        ends = [by_id.get(i) or (_offsets(positions[n]) if n < len(positions)
                                 and isinstance(positions[n], dict) else None)
                for n, i in enumerate(ids)]
        if None in ends:
            continue
        heads[ends[1]] = (ends[0], str(link.get("link_type") or "_"))
    return heads, [o for o in map(_offsets, spans) if o]


class CoNLLUExporter(BaseExporter):
    format_name = "conll_u"
    description = "CoNLL-U format (Universal Dependencies compatible, NER in MISC)"
    file_extensions = [".conllu"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        has_span_schema = any(
            s.get("annotation_type") == "span"
            for s in context.schemas
        )
        if not has_span_schema:
            return False, "No span annotation schema found in config"
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        options = options or {}
        warnings = []

        tokenization = options.get("tokenization", "whitespace")
        schema_name = options.get("schema_name")
        if not schema_name:
            for s in context.schemas:
                if s.get("annotation_type") == "span":
                    schema_name = s.get("name")
                    break
        link_schema = _dependency_scheme(context.schemas, schema_name,
                                         options.get("link_schema"))
        cross_sentence = 0

        os.makedirs(output_path, exist_ok=True)

        files_written = []
        total_tokens = 0
        total_entities = 0
        total_documents = 0
        sent_counter = 0

        for suffix, records in annotator_groups(
                context.annotations, options.get("annotator"), warnings, "CoNLL-U"):
            lines = []
            record_of = {str(r.get("instance_id", "")): r for r in records}
            for doc_id, text, tokens, bio_tags, sentences in conll_documents(
                    context, records, schema_name, tokenization, warnings):
                heads, spans = _dependencies(record_of.get(doc_id, {}), schema_name,
                                             link_schema)

                def span_of(tok):
                    return next((o for o in spans if o[0] <= tok["start"] < o[1]), None)

                total_documents += 1
                total_tokens += len(tokens)
                total_entities += sum(1 for t in bio_tags if t.startswith("B-"))

                for sentence_indices in sentences:
                    sent_counter += 1
                    sent_tokens = [tokens[i] for i in sentence_indices]
                    sent_tags = [bio_tags[i] for i in sentence_indices]

                    # Reconstruct sentence text
                    if sent_tokens:
                        s_start = sent_tokens[0]["start"]
                        s_end = sent_tokens[-1]["end"]
                        sent_text = text[s_start:s_end].replace("\n", " ")
                    else:
                        sent_text = ""

                    lines.append(f"# sent_id = {doc_id}-s{sent_counter}")
                    lines.append(f"# text = {sent_text}")

                    # A span's first token in this sentence, 1-based.
                    first_token = {}
                    for tok_num, tok in enumerate(sent_tokens, start=1):
                        span = span_of(tok)
                        if span is not None and span not in first_token:
                            first_token[span] = tok_num

                    for tok_num, (tok, ner_tag) in enumerate(
                        zip(sent_tokens, sent_tags), start=1
                    ):
                        # Build MISC field
                        misc_parts = []

                        # SpaceAfter=No if no space before next token
                        if tok_num < len(sent_tokens):
                            next_tok = sent_tokens[tok_num]  # 0-indexed next
                            if tok["end"] == next_tok["start"]:
                                misc_parts.append("SpaceAfter=No")

                        # NER tag
                        if ner_tag != "O":
                            misc_parts.append(f"NER={ner_tag}")

                        misc = "|".join(misc_parts) if misc_parts else "_"

                        head, deprel = "_", "_"
                        span = span_of(tok)
                        if heads and span is not None and first_token.get(span) == tok_num:
                            if span in heads:
                                head_span, relation = heads[span]
                                if head_span in first_token:
                                    head, deprel = str(first_token[head_span]), relation
                                else:
                                    cross_sentence += 1
                            else:
                                head, deprel = "0", "root"

                        # 10-column CoNLL-U format
                        # ID FORM LEMMA UPOS XPOS FEATS HEAD DEPREL DEPS MISC
                        cols = [
                            str(tok_num),       # ID
                            tok["token"],       # FORM
                            "_",                # LEMMA
                            "_",                # UPOS
                            "_",                # XPOS
                            "_",                # FEATS
                            head,               # HEAD
                            deprel,             # DEPREL
                            "_",                # DEPS
                            misc,               # MISC
                        ]
                        lines.append("\t".join(cols))

                    lines.append("")  # Blank line between sentences

            name = f"annotations.{_safe(suffix)}.conllu" if suffix else "annotations.conllu"
            out_file = os.path.join(output_path, name)
            with open(out_file, "w") as f:
                f.write("\n".join(lines))
            files_written.append(out_file)

        if cross_sentence:
            warnings.append(
                "%d dependency link(s) cross a sentence boundary and were left "
                "out (HEAD _). Sentences are split by the tokenizer, not by "
                "the links." % cross_sentence)
        return ExportResult(
            success=True,
            format_name=self.format_name,
            files_written=files_written,
            warnings=warnings,
            stats={
                "num_documents": total_documents,
                "num_sentences": sent_counter,
                "num_tokens": total_tokens,
                "num_entities": total_entities,
            },
        )
