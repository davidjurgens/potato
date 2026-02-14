"""
CoNLL-U Exporter

Exports span annotations to CoNLL-U format:
- 10 columns: ID FORM LEMMA UPOS XPOS FEATS HEAD DEPREL DEPS MISC
- NER annotations placed in MISC column as SpaceAfter/NER features
- Blank lines between sentences
- Comment lines with sent_id and text
"""

import os
import logging
from typing import Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult
from .nlp_utils import tokenize_text, char_spans_to_bio_tags, group_sentences

logger = logging.getLogger(__name__)


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

        os.makedirs(output_path, exist_ok=True)
        out_file = os.path.join(output_path, "annotations.conllu")

        lines = []
        total_tokens = 0
        total_entities = 0
        sent_counter = 0

        item_props = context.config.get("item_properties", {})
        text_key = item_props.get("text_key", "text")

        # Deduplicate by instance
        instance_annotations = {}
        for ann in context.annotations:
            iid = ann.get("instance_id", "")
            if iid not in instance_annotations:
                instance_annotations[iid] = ann

        for instance_id, ann in instance_annotations.items():
            item = context.items.get(instance_id, {})
            text = item.get(text_key, "")
            if not text:
                for alt_key in ("text", "sentence", "content"):
                    if alt_key in item:
                        text = item[alt_key]
                        break

            if not text:
                warnings.append(f"No text found for {instance_id}")
                continue

            if isinstance(text, list):
                text = " ".join(str(t) for t in text)

            tokens = tokenize_text(text, method=tokenization)
            if not tokens:
                continue

            # Get spans
            spans = []
            for span_schema, span_list in ann.get("spans", {}).items():
                if schema_name and span_schema != schema_name:
                    continue
                for sp in span_list:
                    spans.append({
                        "start": sp.get("start", 0),
                        "end": sp.get("end", 0),
                        "label": sp.get("name") or sp.get("label", "ENTITY"),
                    })

            bio_tags = char_spans_to_bio_tags(tokens, spans)
            total_tokens += len(tokens)
            total_entities += sum(1 for t in bio_tags if t.startswith("B-"))

            sentences = group_sentences(tokens, text)

            for sentence_indices in sentences:
                sent_counter += 1
                sent_tokens = [tokens[i] for i in sentence_indices]
                sent_tags = [bio_tags[i] for i in sentence_indices]

                # Reconstruct sentence text
                if sent_tokens:
                    s_start = sent_tokens[0]["start"]
                    s_end = sent_tokens[-1]["end"]
                    sent_text = text[s_start:s_end]
                else:
                    sent_text = ""

                lines.append(f"# sent_id = {instance_id}-s{sent_counter}")
                lines.append(f"# text = {sent_text}")

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

                    # 10-column CoNLL-U format
                    # ID FORM LEMMA UPOS XPOS FEATS HEAD DEPREL DEPS MISC
                    cols = [
                        str(tok_num),       # ID
                        tok["token"],       # FORM
                        "_",                # LEMMA
                        "_",                # UPOS
                        "_",                # XPOS
                        "_",                # FEATS
                        "_",                # HEAD
                        "_",                # DEPREL
                        "_",                # DEPS
                        misc,               # MISC
                    ]
                    lines.append("\t".join(cols))

                lines.append("")  # Blank line between sentences

        with open(out_file, "w") as f:
            f.write("\n".join(lines))

        return ExportResult(
            success=True,
            format_name=self.format_name,
            files_written=[out_file],
            warnings=warnings,
            stats={
                "num_documents": len(instance_annotations),
                "num_sentences": sent_counter,
                "num_tokens": total_tokens,
                "num_entities": total_entities,
            },
        )
