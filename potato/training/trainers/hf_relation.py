"""Relations, events and coreference from linked spans.

For ``span_link``, ``event_annotation`` and ``coreference`` schemes, whose
answer is links between the spans of another scheme. Before this they were
classified as span schemes and offered the span tagger, which found no spans
under their name, and their links never reached a bundle at all.

One transformer encoder, three small heads over it, trained together:

* a **mention tagger**: BIO tags over tokens, the spans annotators drew;
* a **pair classifier** over two spans (each the encoder states at its first
  and last token, and their product): ``none`` or a link type for relations,
  ``none`` or a role for a trigger and an argument, same entity or not for
  coreference;
* a **span classifier**: an event type (or ``none``) for each span, which
  picks out the triggers, and for coreference the entity type of a span's
  chain.

Pairs are trained on the annotators' own spans, and predicted on the spans
the tagger finds, so the run's held-out score measures the whole pipeline:
a link counts only when both of its spans were found with the right
boundaries. Coreference is decoded by mention ranking: each mention joins
its most likely earlier mention when that is more likely than not.

**Dependency parsing.** When every training answer is a dependency tree (a
directed span_link with the head first, every span but one having one head),
the run decodes trees: the span classifier scores each span as the root, the
pair classifier's ``none`` probability scores each possible head, and the
parse is the maximum spanning tree over those scores (Chu-Liu-Edmonds), so a
prediction is always one tree. ``decode: pairs`` turns this off; the held-out
score adds UAS and LAS.

A text longer than ``max_length`` tokens is cut there; spans past the cut
are not trained on or predicted, and the run log counts them.

Predictions are in the canonical form of :mod:`potato.training.structured`:
spans as offsets and labels, and links, chains or events referring to spans
by position in that list.
"""

from __future__ import annotations

import os
import random
from collections import Counter
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainerError, TrainingSpec)
from potato.training.trainers import _hf_common as hf
from potato.training.trainers.hf_token_classification import (bio_tags, decode,
                                                              non_overlapping)

INSTALL_HINT = "pip install 'potato-annotation[train-text]'"
_NEEDS = ("torch", "transformers")
DEFAULT_MODEL = "distilbert/distilroberta-base"
HEADS_FILE = "heads.pt"
NONE = "none"


# ------------------------------------------------------------- targets

def _spans(target: Dict[str, Any]) -> List[Tuple[int, int, str]]:
    out = []
    for span in (target or {}).get("spans") or []:
        try:
            out.append((int(span["start"]), int(span["end"]), str(span.get("label") or "")))
        except (KeyError, TypeError, ValueError):
            out.append((0, 0, ""))
    return out


def vocabularies(kind: str, rows: Iterable[Dict[str, Any]], schema: str,
                 decode: str = "auto") -> Dict[str, Any]:
    """Mention labels, pair classes, span classes, which link types are
    directed, and whether to decode trees, from the training rows."""
    from potato.training.structured import is_tree_answer
    rows = list(rows)
    mentions, pair, span = set(), set(), set()
    directed: Counter = Counter()
    undirected: Counter = Counter()
    for row in rows:
        target = (row.get("targets") or {}).get(schema) or {}
        mentions.update(s[2] for s in _spans(target) if s[2])
        if kind == "relation":
            for link in target.get("links") or []:
                if len(link.get("spans") or []) == 2:
                    pair.add(str(link.get("type") or ""))
                    (directed if link.get("directed") else undirected)[str(link.get("type") or "")] += 1
        elif kind == "event":
            for event in target.get("events") or []:
                span.add(str(event.get("type") or ""))
                pair.update(str(a.get("role") or "") for a in event.get("arguments") or [])
        elif kind == "coreference":
            pair.add("same")
            span.update(str(c.get("type") or "") for c in target.get("clusters") or [])
    tree = kind == "relation" and decode != "pairs" and bool(rows) and all(
        is_tree_answer((r.get("targets") or {}).get(schema)) for r in rows)
    if tree:
        span = {"root"}
    return {"mention_labels": sorted(mentions),
            "pair_classes": [NONE] + sorted(pair),
            "span_classes": ([NONE] + sorted(span)) if span else [],
            "directed": sorted(t for t in pair if directed[t] >= undirected[t] and directed[t]),
            "tree": tree}


def gold_structure(kind: str, target: Dict[str, Any], vocab: Dict[str, Any]
                   ) -> Tuple[Dict[Tuple[int, int], int], Dict[int, int]]:
    """``({(i, j): pair class}, {i: span class})`` for one answer, positive
    entries only; every other pair or span is class 0, ``none``."""
    pair_index = {c: n for n, c in enumerate(vocab["pair_classes"])}
    span_index = {c: n for n, c in enumerate(vocab["span_classes"])}
    pairs: Dict[Tuple[int, int], int] = {}
    spans: Dict[int, int] = {}
    if kind == "relation":
        for link in target.get("links") or []:
            members = link.get("spans") or []
            label = pair_index.get(str(link.get("type") or ""))
            if len(members) != 2 or label is None:
                continue
            i, j = int(members[0]), int(members[1])
            pairs[(i, j)] = label
            if not link.get("directed"):
                pairs[(j, i)] = label
        if vocab.get("tree"):
            headed = {int(l["spans"][1]) for l in target.get("links") or []}
            for n in range(len(target.get("spans") or [])):
                if n not in headed:
                    spans[n] = span_index["root"]
    elif kind == "event":
        for event in target.get("events") or []:
            trigger = int(event.get("trigger"))
            spans[trigger] = span_index.get(str(event.get("type") or ""), 0)
            for argument in event.get("arguments") or []:
                role = pair_index.get(str(argument.get("role") or ""))
                if role is not None:
                    pairs[(trigger, int(argument.get("span")))] = role
    elif kind == "coreference":
        for cluster in target.get("clusters") or []:
            members = sorted(int(m) for m in cluster.get("spans") or [])
            kind_id = span_index.get(str(cluster.get("type") or ""), 0)
            for m in members:
                spans[m] = kind_id
            for a in members:
                for b in members:
                    if b < a:
                        pairs[(a, b)] = 1       # b is an antecedent of a
    return pairs, spans


def candidate_pairs(kind: str, n_spans: int, triggers: Optional[List[int]] = None
                    ) -> List[Tuple[int, int]]:
    if kind == "coreference":
        return [(a, b) for a in range(n_spans) for b in range(a)]
    if kind == "event":
        return [(t, a) for t in (triggers if triggers is not None else range(n_spans))
                for a in range(n_spans) if a != t]
    return [(i, j) for i in range(n_spans) for j in range(n_spans) if i != j]


# ---------------------------------------------------------------- decoding

def decode_structure(kind: str, spans: List[Dict[str, Any]],
                     pair_probs: Dict[Tuple[int, int], List[float]],
                     span_probs: List[List[float]], vocab: Dict[str, Any]
                     ) -> Tuple[Dict[str, Any], List[float]]:
    """The canonical answer from the heads' probabilities, and the
    probability of every decision it made (for the confidence)."""
    classes = vocab["pair_classes"]
    span_classes = vocab["span_classes"]
    canonical_spans = [{"start": s["start"], "end": s["end"], "label": s["label"]}
                       for s in spans]
    decisions = [float(s.get("confidence", 1.0)) for s in spans]

    if kind == "relation" and vocab.get("tree") and spans:
        return _decode_tree(spans, canonical_spans, pair_probs, span_probs,
                            classes, decisions)

    if kind == "relation":
        directed = set(vocab.get("directed") or [])
        links, seen = [], set()
        for (i, j), probs in sorted(pair_probs.items()):
            best = max(range(len(probs)), key=probs.__getitem__)
            if best == 0:
                continue
            label = classes[best]
            if label in directed:
                links.append({"type": label, "spans": [i, j], "directed": True})
                decisions.append(probs[best])
                continue
            key = (min(i, j), max(i, j), label)
            if key in seen:
                continue
            # An undirected link is one decision about both orders.
            reverse = pair_probs.get((j, i)) or probs
            p = (probs[best] + reverse[best]) / 2
            if p <= (probs[0] + reverse[0]) / 2:
                continue
            seen.add(key)
            links.append({"type": label, "spans": [key[0], key[1]], "directed": False})
            decisions.append(p)
        links.sort(key=lambda l: (l["spans"], l["type"]))
        return {"spans": canonical_spans, "links": links}, decisions

    if kind == "event":
        events = []
        for t, probs in enumerate(span_probs):
            best = max(range(len(probs)), key=probs.__getitem__)
            if best == 0:
                continue
            decisions.append(probs[best])
            arguments = []
            for a in range(len(spans)):
                p = pair_probs.get((t, a))
                if not p:
                    continue
                role = max(range(len(p)), key=p.__getitem__)
                if role:
                    arguments.append({"role": classes[role], "span": a})
                    decisions.append(p[role])
            arguments.sort(key=lambda x: (x["span"], x["role"]))
            events.append({"type": span_classes[best], "trigger": t,
                           "arguments": arguments})
        return {"spans": canonical_spans, "events": events}, decisions

    # coreference: each mention joins its likeliest earlier mention, if any
    parent = list(range(len(spans)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a in range(len(spans)):
        best, best_p = None, 0.5
        for b in range(a):
            p = (pair_probs.get((a, b)) or [1.0, 0.0])[1]
            if p > best_p:
                best, best_p = b, p
        if best is not None:
            parent[root(a)] = root(best)
            decisions.append(best_p)
    groups: Dict[int, List[int]] = {}
    for i in range(len(spans)):
        groups.setdefault(root(i), []).append(i)
    clusters = []
    for members in groups.values():
        if len(members) < 2:
            continue
        votes = Counter()
        for m in members:
            if m < len(span_probs) and span_classes:
                probs = span_probs[m][1:]
                if probs:
                    votes[span_classes[1 + max(range(len(probs)), key=probs.__getitem__)]] += 1
        clusters.append({"type": votes.most_common(1)[0][0] if votes else "",
                         "spans": sorted(members)})
    clusters.sort(key=lambda c: c["spans"])
    return {"spans": canonical_spans, "clusters": clusters}, decisions


def _decode_tree(spans, canonical_spans, pair_probs, span_probs, classes,
                 decisions):
    """One dependency tree: the maximum spanning tree over log-probabilities
    of each span being the root and of each pair being linked (head first)."""
    import math
    from potato.training.trees import max_spanning_tree

    def log(p):
        return math.log(max(p, 1e-9))

    n = len(spans)
    scores = [[float("-inf")] * (n + 1) for _ in range(n + 1)]
    for d in range(n):
        root = span_probs[d][1] if d < len(span_probs) and len(span_probs[d]) > 1 else 0.0
        scores[0][d + 1] = log(root)
        for h in range(n):
            if h != d and (h, d) in pair_probs:
                scores[h + 1][d + 1] = log(1.0 - pair_probs[(h, d)][0])
    heads = max_spanning_tree(scores)
    links = []
    for d in range(n):
        h = heads[d + 1]
        if h is None:
            continue
        if h == 0:
            decisions.append(span_probs[d][1] if d < len(span_probs) else 0.0)
            continue
        probs = pair_probs[(h - 1, d)]
        best = 1 + max(range(len(probs) - 1), key=lambda k: probs[k + 1])
        links.append({"type": classes[best], "spans": [h - 1, d], "directed": True})
        decisions.append(1.0 - probs[0])
    links.sort(key=lambda l: (l["spans"], l["type"]))
    return {"spans": canonical_spans, "links": links}, decisions


# ------------------------------------------------------------------- model

def _network(torch, encoder, hidden: int, n_tags: int, n_pair: int, n_span: int,
             dropout: float = 0.1):
    nn = torch.nn

    class RelationNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.encoder = encoder
            self.tagger = nn.Linear(hidden, n_tags)
            self.pair = nn.Sequential(nn.Linear(6 * hidden, hidden), nn.ReLU(),
                                      nn.Dropout(dropout), nn.Linear(hidden, n_pair))
            self.span = nn.Linear(2 * hidden, n_span) if n_span else None

        def states(self, enc):
            return self.encoder(input_ids=enc["input_ids"],
                                attention_mask=enc["attention_mask"]).last_hidden_state

        def heads(self):
            out = {"tagger": self.tagger.state_dict(), "pair": self.pair.state_dict()}
            if self.span is not None:
                out["span"] = self.span.state_dict()
            return out

        def load_heads(self, state):
            self.tagger.load_state_dict(state["tagger"])
            self.pair.load_state_dict(state["pair"])
            if self.span is not None:
                self.span.load_state_dict(state["span"])

    return RelationNet()


def _token_span(offsets: List[Tuple[int, int]], start: int, end: int
                ) -> Optional[Tuple[int, int]]:
    """First and last token covering ``[start, end)``; None past the cut."""
    first = last = None
    for n, (a, b) in enumerate(offsets):
        if a == b:
            continue
        if b > start and a < end:
            first = n if first is None else first
            last = n
    return None if first is None else (first, last)


class HFRelationTrainer(Trainer):
    name: ClassVar[str] = "hf-relation"
    description: ClassVar[str] = (
        "Relations, events and coreference: a transformer tags the spans and "
        "classifies pairs of them.")
    kinds: ClassVar[Tuple[str, ...]] = ("relation", "event", "coreference")
    modalities: ClassVar[Tuple[str, ...]] = ("text",)
    install_hint: ClassVar[str] = INSTALL_HINT
    licence: ClassVar[str] = "Apache-2.0"
    commercial_use: ClassVar[Optional[bool]] = True

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        return hf.availability(_NEEDS)

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {"model_name": DEFAULT_MODEL, "epochs": 10, "batch_size": 8,
                "gradient_accumulation": 1, "learning_rate": None,
                "weight_decay": 0.01, "warmup_ratio": 0.1, "patience": 3,
                "precision": "auto", "lora": None, "max_length": 512,
                "max_negatives": 100, "decode": "auto", "min_instances": 20}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        props = dict(hf.COMMON_PARAMS)
        props["learning_rate"] = dict(
            props["learning_rate"], default=None,
            description="Defaults to 5e-5, or 2e-4 with LoRA.")
        props["epochs"] = dict(props["epochs"], default=10)
        props["patience"] = dict(props["patience"], default=3)
        props.update({
            "model_name": {"type": "string", "default": DEFAULT_MODEL,
                           "description": "A Hugging Face model id or a local "
                                          "path."},
            "max_length": {"type": "integer", "minimum": 16, "default": 512,
                           "description": "Tokens per item; spans past the "
                                          "cut are not used."},
            "decode": {"type": "string", "enum": ["auto", "tree", "pairs"],
                       "default": "auto",
                       "description": "Relations: decode one dependency tree "
                                      "per item (tree), each pair on its own "
                                      "(pairs), or tree when every training "
                                      "answer is one (auto)."},
            "max_negatives": {"type": "integer", "minimum": 1, "default": 100,
                              "description": "Unlinked span pairs trained on "
                                             "per item, sampled. Most pairs "
                                             "in a long text are unlinked."},
        })
        return {"type": "object", "properties": props,
                "additionalProperties": False}

    def validate(self, spec: TrainingSpec, bundle: BundleRef) -> List[str]:
        params = hf.merged_params(self.default_params(), spec)
        schema = spec.primary_schema
        if schema is None:
            return ["No schema was selected for training."]
        if schema.kind not in self.kinds:
            return ["Schema %r is %s; this trainer handles %s."
                    % (schema.name, schema.kind, ", ".join(self.kinds))]
        problems = []
        rows = hf.rows_with_target(bundle.read_split("train"), schema.name)
        vocab = vocabularies(schema.kind, rows, schema.name, params["decode"])
        if params["decode"] == "tree" and not vocab["tree"]:
            problems.append("decode: tree, but not every training answer for %r "
                            "is a dependency tree (directed links, head first, "
                            "one head per span, one root)." % schema.name)
        if not vocab["mention_labels"]:
            problems.append("No spans in the train split for %r. Its spans "
                            "come from the scheme named by span_schema."
                            % schema.name)
        if len(vocab["pair_classes"]) < 2 and len(vocab["span_classes"]) < 2:
            problems.append("No links, chains or events in the train split "
                            "for %r." % schema.name)
        if len(rows) < int(params["min_instances"]):
            problems.append(
                "Only %d items in the train split; this trainer needs at "
                "least %d. Annotate more, or lower min_instances."
                % (len(rows), int(params["min_instances"])))
        problems.extend(hf.quantize_unsupported(params))
        return problems

    # ------------------------------------------------------------- encode

    def _encode(self, tokenizer, texts: List[str], params, device):
        enc = tokenizer(texts, truncation=True, max_length=int(params["max_length"]),
                        padding=True, return_offsets_mapping=True,
                        return_special_tokens_mask=True, return_tensors="pt")
        offsets = [[tuple(int(x) for x in o) for o in row] for row in enc.pop("offset_mapping").tolist()]
        special = [[bool(x) for x in row] for row in enc.pop("special_tokens_mask").tolist()]
        return enc.to(device), offsets, special

    @staticmethod
    def _span_vectors(torch, states, token_spans):
        return torch.stack([torch.cat([states[a], states[b]]) for a, b in token_spans])

    def _pair_logits(self, torch, net, vectors, pairs):
        left = vectors[[i for i, _ in pairs]]
        right = vectors[[j for _, j in pairs]]
        return net.pair(torch.cat([left, right, left * right], dim=-1))

    # ---------------------------------------------------------------- fit

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        hf.require(_NEEDS, INSTALL_HINT)
        import torch
        import torch.nn.functional as F
        from transformers import AutoModel, AutoTokenizer

        params = hf.merged_params(self.default_params(), spec)
        if params.get("learning_rate") is None:
            params["learning_rate"] = 2e-4 if params["lora"] else 5e-5
        schema = spec.primary_schema
        kind = schema.kind
        train = hf.rows_with_target(bundle.read_split("train"), schema.name)
        val = hf.rows_with_target(bundle.read_split("val"), schema.name)
        if not train:
            raise TrainerError("No labelled rows in the train split for %r" % schema.name)
        vocab = vocabularies(kind, train, schema.name, params["decode"])
        if vocab["tree"]:
            report.log("info", "Every answer is a dependency tree: decoding "
                               "one tree per item")
        tags = ["O"] + ["%s-%s" % (p, label) for label in vocab["mention_labels"]
                        for p in ("B", "I")]
        tag_index = {t: n for n, t in enumerate(tags)}
        report.log("info", "%d train and %d val items; mentions %s; classes %s"
                   % (len(train), len(val), ", ".join(vocab["mention_labels"]),
                      ", ".join(vocab["pair_classes"][1:])))

        hf.seed_everything(spec.seed)
        rng = random.Random(spec.seed)
        device = hf.pick_device(spec, report)
        report.status("running", "loading %s" % params["model_name"])
        tokenizer = AutoTokenizer.from_pretrained(params["model_name"])
        encoder = AutoModel.from_pretrained(params["model_name"])
        encoder = hf.apply_lora(encoder, params["lora"], None, report)
        net = _network(torch, encoder, encoder.config.hidden_size, len(tags),
                       len(vocab["pair_classes"]), len(vocab["span_classes"]))
        net = hf.place(net, device)
        lost = {"spans": 0}

        def loss_of(batch):
            texts = [r.get("text", "") for r in batch]
            enc, offsets, special = self._encode(tokenizer, texts, params, device)
            states = net.states(enc)
            tag_targets, losses = [], []
            for b, row in enumerate(batch):
                target = row["targets"][schema.name]
                spans = _spans(target)
                kept, _ = non_overlapping([{"start": s, "end": e, "label": l}
                                           for s, e, l in spans])
                tag_targets.append(bio_tags(offsets[b], kept, tag_index, special[b]))
                token_spans = [_token_span(offsets[b], s, e) for s, e, _ in spans]
                usable = [n for n, t in enumerate(token_spans) if t is not None]
                lost["spans"] += len(spans) - len(usable)
                if not usable:
                    continue
                vectors = self._span_vectors(torch, states[b], [token_spans[n] for n in usable])
                where = {n: k for k, n in enumerate(usable)}
                gold_pairs, gold_spans = gold_structure(kind, target, vocab)
                if net.span is not None:
                    span_targets = torch.tensor([gold_spans.get(n, 0) for n in usable],
                                                device=device)
                    losses.append(F.cross_entropy(net.span(vectors), span_targets))
                triggers = sorted(where[t] for t in gold_spans if t in where and gold_spans[t]) \
                    if kind == "event" else None
                pairs = candidate_pairs(kind, len(usable), triggers)
                positive = [p for p in pairs if (usable[p[0]], usable[p[1]]) in gold_pairs]
                negative = [p for p in pairs if (usable[p[0]], usable[p[1]]) not in gold_pairs]
                if len(negative) > int(params["max_negatives"]):
                    negative = rng.sample(negative, int(params["max_negatives"]))
                chosen = positive + negative
                if not chosen:
                    continue
                labels = torch.tensor([gold_pairs.get((usable[i], usable[j]), 0)
                                       for i, j in chosen], device=device)
                losses.append(F.cross_entropy(self._pair_logits(torch, net, vectors, chosen),
                                              labels))
            width = states.shape[1]
            tag_tensor = torch.tensor([t + [-100] * (width - len(t)) for t in tag_targets],
                                      device=device)
            tag_loss = F.cross_entropy(net.tagger(states).reshape(-1, len(tags)),
                                       tag_tensor.reshape(-1), ignore_index=-100)
            return tag_loss + (torch.stack(losses).sum() / len(batch) if losses else 0.0)

        selected = {"saved": False}

        def save():
            hf.save_model(net.encoder, tokenizer, spec.workdir)
            torch.save(net.heads(), os.path.join(spec.workdir, hf.MODEL_DIR, HEADS_FILE))
            selected["saved"] = True

        card = {"trainer": self.name, "schema": schema.name, "kind": kind,
                "base_model": params["model_name"], "lora": params["lora"],
                "tags": tags, "max_length": int(params["max_length"]),
                "hidden_size": encoder.config.hidden_size, **vocab}

        def on_epoch_end(epoch):
            if not val:
                return None
            score = self._score(net, tokenizer, val, schema, card, device)
            report.metric("val", _headline(kind), score, step=epoch + 1)
            if selected.get("best") is None or score > selected["best"]:
                selected["best"] = score
                save()
            return score

        report.status("running", "fine-tuning")
        summary = hf.train_loop(net, train, params, loss_of, report, device=device,
                                seed=spec.seed, on_epoch_end=on_epoch_end)
        if not selected["saved"]:
            save()
        if lost["spans"]:
            report.log("warning", "Spans past max_length (%d tokens) were left out "
                                  "%d time(s) over the epochs; raise max_length "
                                  "for long texts." % (int(params["max_length"]),
                                                       lost["spans"]))
        card.update({"device": device, "n_train": len(train),
                     "bundle_digest": bundle.digest,
                     "selected_epoch": summary["best_epoch"]})
        hf.write_card(spec.workdir, card)
        metrics = {"n_train": float(len(train)),
                   "train_seconds": summary["train_seconds"],
                   "epochs_run": float(summary["epochs_run"])}
        if summary["final_loss"] is not None:
            metrics["train_loss"] = round(summary["final_loss"], 4)
        return FitResult(model_version="%s-%s-%s" % (self.name, schema.name, spec.run_id),
                         artifact_paths=hf.artifact_files(spec.workdir), metrics=metrics,
                         label_order=vocab["pair_classes"], selected_on="val" if val else "")

    def _score(self, net, tokenizer, rows, schema, card, device):
        from potato.training.evaluation import score_split
        predictions = {}
        for row, payload, _ in self._predict_rows(net, tokenizer, rows, card, device):
            predictions[(str(row.get("instance_id", "")), schema.name)] = payload
        metrics, _ = score_split(rows, predictions, schema.name, card["kind"])
        return metrics.get(_headline(card["kind"]), 0.0)

    def _predict_rows(self, net, tokenizer, rows, card, device,
                      report: Optional[ProgressReporter] = None):
        import torch

        kind, tags = card["kind"], card["tags"]
        params = {"max_length": card.get("max_length", 512)}
        net.eval()
        for done, row in enumerate(rows, 1):
            text = row.get("text", "") if isinstance(row, dict) else row.text
            with torch.inference_mode():
                enc, offsets, special = self._encode(tokenizer, [text], params, device)
                states = net.states(enc)[0]
                probs = torch.softmax(net.tagger(states).float(), dim=-1).cpu().tolist()
                token_offsets = [o for o, s in zip(offsets[0], special[0]) if not s and o[0] != o[1]]
                token_probs = [p for p, o, s in zip(probs, offsets[0], special[0])
                               if not s and o[0] != o[1]]
                spans = decode(token_offsets, token_probs, tags)
                token_spans = [_token_span(offsets[0], s["start"], s["end"]) for s in spans]
                spans = [s for s, t in zip(spans, token_spans) if t is not None]
                token_spans = [t for t in token_spans if t is not None]
                pair_probs: Dict[Tuple[int, int], List[float]] = {}
                span_probs: List[List[float]] = []
                if spans:
                    vectors = self._span_vectors(torch, states, token_spans)
                    if net.span is not None:
                        span_probs = torch.softmax(net.span(vectors).float(), -1).cpu().tolist()
                    triggers = None
                    if kind == "event":
                        triggers = [n for n, p in enumerate(span_probs)
                                    if max(range(len(p)), key=p.__getitem__) != 0]
                    pairs = candidate_pairs(kind, len(spans), triggers)
                    if pairs:
                        logits = self._pair_logits(torch, net, vectors, pairs)
                        for pair, p in zip(pairs, torch.softmax(logits.float(), -1).cpu().tolist()):
                            pair_probs[pair] = p
            payload, decisions = decode_structure(kind, spans, pair_probs, span_probs, card)
            confidence = min(decisions) if decisions else None
            yield row, payload, confidence
            if report is not None:
                report.progress("predict", done, len(rows))
                if report.should_stop():
                    return

    # ------------------------------------------------------------- predict

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        hf.require(_NEEDS, INSTALL_HINT)
        import torch
        from transformers import AutoModel, AutoTokenizer

        card = hf.read_card(artifact_dir)
        device = hf.pick_device(spec, report)
        model_dir = os.path.join(artifact_dir, hf.MODEL_DIR)
        tokenizer = AutoTokenizer.from_pretrained(model_dir)
        encoder = hf.load_pretrained(AutoModel, artifact_dir, card, device)
        net = _network(torch, encoder, int(card["hidden_size"]), len(card["tags"]),
                       len(card["pair_classes"]), len(card["span_classes"]))
        net.load_heads(torch.load(os.path.join(model_dir, HEADS_FILE),
                                  map_location="cpu"))
        net = hf.place(net, device)
        items = list(items)
        for item, payload, confidence in self._predict_rows(net, tokenizer, items, card,
                                                            device, report):
            yield PredictionRecord(
                instance_id=item.instance_id, schema_name=card["schema"],
                payload=payload,
                confidence=None if confidence is None else round(float(confidence), 4))


def _headline(kind: str) -> str:
    from potato.training.evaluation import HEADLINE
    return HEADLINE.get(kind, "score")
