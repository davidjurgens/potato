"""Conversation trees: rate each turn, and pick the best path.

For ``tree_annotation`` schemes, where annotators answer a question about
each node of a conversation tree (its ``node_scheme``) and select the best
path from the root by clicking nodes. Before this the scheme was classified
as a span scheme and offered the span tagger, which found nothing to tag.

One transformer encoder reads each node with its parent's text as context
(the turn it answers), and two heads sit on it:

* a **node head**: the answer to each node question, over the answers
  annotators gave (a likert point, a label);
* a **path head**: whether a node continues the selected path from its
  parent, trained on the path's nodes against their siblings.

A predicted path starts at the root and keeps taking the child the path head
likes best while that is more likely than not. Nodes annotators did not
answer are not trained on: an unrated turn is not a turn rated "none".

Predictions are ``{"path": [node ids], "nodes": {node id: {question:
answer}}}``, the shape the tree widget's hidden inputs hold.
"""

from __future__ import annotations

import os
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainerError, TrainingSpec)
from potato.training.trainers import _hf_common as hf

INSTALL_HINT = "pip install 'potato-annotation[train-text]'"
_NEEDS = ("torch", "transformers")
DEFAULT_MODEL = "distilbert/distilroberta-base"
HEADS_FILE = "heads.pt"


def walk(tree: Dict[str, Any], parent: Optional[Dict[str, Any]] = None):
    """``(node, parent)`` for every node, depth first."""
    if not isinstance(tree, dict):
        return
    yield tree, parent
    for child in tree.get("children") or []:
        yield from walk(child, tree)


def _text(node: Optional[Dict[str, Any]]) -> str:
    if not node:
        return ""
    speaker = str(node.get("speaker") or "").strip()
    text = str(node.get("text") or node.get("content") or "")
    return "%s: %s" % (speaker, text) if speaker else text


def _answer(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return "|".join(sorted(str(v) for v in value))
    return str(value)


def examples(row: Dict[str, Any], schema: str, classes: Dict[str, int]):
    """``(node_examples, path_examples)`` from one row.

    A node example is ``(parent text, node text, class index)`` per answered
    question; a path example is ``(parent text, node text, 1 or 0)`` for each
    child of a node on the path."""
    target = (row.get("targets") or {}).get(schema) or {}
    tree = row.get("tree")
    nodes, paths = [], []
    if not tree:
        return nodes, paths
    answers = target.get("nodes") or {}
    by_id = {}
    for node, parent in walk(tree):
        by_id[str(node.get("id"))] = node
        for question, value in (answers.get(str(node.get("id"))) or {}).items():
            index = classes.get("%s=%s" % (question, _answer(value)))
            if index is not None:
                nodes.append((_text(parent), _text(node), index))
    path = [str(p) for p in target.get("path") or []]
    on_path = set(path)
    for node_id in path:
        node = by_id.get(node_id)
        for child in (node or {}).get("children") or []:
            paths.append((_text(node), _text(child), int(str(child.get("id")) in on_path)))
    return nodes, paths


def node_classes(rows: Iterable[Dict[str, Any]], schema: str) -> List[str]:
    found = set()
    for row in rows:
        for answers in ((row.get("targets") or {}).get(schema) or {}).get("nodes", {}).values():
            for question, value in (answers or {}).items():
                found.add("%s=%s" % (question, _answer(value)))
    return sorted(found)


def _network(torch, encoder, hidden: int, n_node: int):
    nn = torch.nn

    class TreeNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.encoder = encoder
            self.node = nn.Linear(hidden, max(1, n_node))
            self.path = nn.Linear(hidden, 2)

        def pooled(self, enc):
            states = self.encoder(input_ids=enc["input_ids"],
                                  attention_mask=enc["attention_mask"]).last_hidden_state
            return states[:, 0]

        def heads(self):
            return {"node": self.node.state_dict(), "path": self.path.state_dict()}

        def load_heads(self, state):
            self.node.load_state_dict(state["node"])
            self.path.load_state_dict(state["path"])

    return TreeNet()


class HFConversationTreeTrainer(Trainer):
    name: ClassVar[str] = "hf-conversation-tree"
    description: ClassVar[str] = (
        "Conversation trees: rates each turn and picks the best path, from "
        "tree_annotation answers.")
    kinds: ClassVar[Tuple[str, ...]] = ("conversation_tree",)
    modalities: ClassVar[Tuple[str, ...]] = ("text",)
    install_hint: ClassVar[str] = INSTALL_HINT
    licence: ClassVar[str] = "Apache-2.0"
    commercial_use: ClassVar[Optional[bool]] = True

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        return hf.availability(_NEEDS)

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {"model_name": DEFAULT_MODEL, "epochs": 5, "batch_size": 16,
                "gradient_accumulation": 1, "learning_rate": None,
                "weight_decay": 0.01, "warmup_ratio": 0.1, "patience": 2,
                "precision": "auto", "lora": None, "max_length": 256,
                "min_instances": 10}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        props = dict(hf.COMMON_PARAMS)
        props["learning_rate"] = dict(
            props["learning_rate"], default=None,
            description="Defaults to 5e-5, or 2e-4 with LoRA.")
        props.update({
            "model_name": {"type": "string", "default": DEFAULT_MODEL,
                           "description": "A Hugging Face model id or a local "
                                          "path."},
            "max_length": {"type": "integer", "minimum": 8, "default": 256,
                           "description": "Tokens per turn and its parent."},
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
        rows = hf.rows_with_target(bundle.read_split("train"), schema.name)
        problems = []
        if not any(r.get("tree") for r in rows):
            problems.append("The items carry no conversation tree. It is read from "
                            "the field of the conversation_tree display.")
        classes = {c: n for n, c in enumerate(node_classes(rows, schema.name))}
        n_nodes = n_paths = 0
        for row in rows:
            nodes, paths = examples(row, schema.name, classes)
            n_nodes += len(nodes)
            n_paths += len(paths)
        if not n_nodes and not n_paths:
            problems.append("No node answers or selected paths in the train split "
                            "for %r." % schema.name)
        if len(rows) < int(params["min_instances"]):
            problems.append(
                "Only %d items in the train split; this trainer needs at "
                "least %d. Annotate more, or lower min_instances."
                % (len(rows), int(params["min_instances"])))
        problems.extend(hf.quantize_unsupported(params))
        return problems

    def _encode(self, tokenizer, pairs, params, device):
        return tokenizer([p[0] for p in pairs], [p[1] for p in pairs],
                         truncation="longest_first", max_length=int(params["max_length"]),
                         padding=True, return_tensors="pt").to(device)

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
        train = hf.rows_with_target(bundle.read_split("train"), schema.name)
        val = hf.rows_with_target(bundle.read_split("val"), schema.name)
        classes = node_classes(train, schema.name)
        index = {c: n for n, c in enumerate(classes)}
        units = []
        for row in train:
            nodes, paths = examples(row, schema.name, index)
            units += [("node",) + n for n in nodes] + [("path",) + p for p in paths]
        if not units:
            raise TrainerError("No node answers or paths in the train split for %r"
                               % schema.name)
        path_roots = [str(((r.get("targets") or {}).get(schema.name) or {}).get("path", [None])[0])
                      == str((r.get("tree") or {}).get("id")) for r in train
                      if ((r.get("targets") or {}).get(schema.name) or {}).get("path")]
        report.log("info", "%d node answers and %d path choices from %d trees; "
                   "answers %s" % (sum(u[0] == "node" for u in units),
                                   sum(u[0] == "path" for u in units), len(train),
                                   ", ".join(classes) or "(none)"))

        hf.seed_everything(spec.seed)
        device = hf.pick_device(spec, report)
        report.status("running", "loading %s" % params["model_name"])
        tokenizer = AutoTokenizer.from_pretrained(params["model_name"])
        encoder = AutoModel.from_pretrained(params["model_name"])
        encoder = hf.apply_lora(encoder, params["lora"], None, report)
        net = hf.place(_network(torch, encoder, encoder.config.hidden_size,
                                len(classes)), device)

        def loss_of(batch):
            losses = []
            for kind, head in (("node", net.node), ("path", net.path)):
                part = [u for u in batch if u[0] == kind]
                if not part or (kind == "node" and not classes):
                    continue
                pooled = net.pooled(self._encode(tokenizer, [u[1:3] for u in part],
                                                 params, device))
                labels = torch.tensor([u[3] for u in part], device=device)
                losses.append(F.cross_entropy(head(pooled), labels) * len(part))
            return torch.stack(losses).sum() / len(batch)

        card = {"trainer": self.name, "schema": schema.name, "kind": schema.kind,
                "base_model": params["model_name"], "lora": params["lora"],
                "node_classes": classes, "max_length": int(params["max_length"]),
                "hidden_size": encoder.config.hidden_size,
                # Whether annotators' paths begin with the root's id.
                "path_includes_root": bool(path_roots) and
                sum(path_roots) * 2 >= len(path_roots)}
        selected = {"saved": False}

        def save():
            hf.save_model(net.encoder, tokenizer, spec.workdir)
            torch.save(net.heads(), os.path.join(spec.workdir, hf.MODEL_DIR, HEADS_FILE))
            selected["saved"] = True

        def on_epoch_end(epoch):
            if not val:
                return None
            from potato.training.evaluation import HEADLINE, score_split
            predictions = {(str(r.get("instance_id")), schema.name): p
                           for r, p, _ in self._predict_rows(net, tokenizer, val, card,
                                                             device)}
            metrics, _ = score_split(val, predictions, schema.name, schema.kind)
            score = metrics.get(HEADLINE[schema.kind], metrics.get("path_accuracy", 0.0))
            report.metric("val", HEADLINE[schema.kind], score, step=epoch + 1)
            if selected.get("best") is None or score > selected["best"]:
                selected["best"] = score
                save()
            return score

        report.status("running", "fine-tuning")
        summary = hf.train_loop(net, units, params, loss_of, report, device=device,
                                seed=spec.seed, on_epoch_end=on_epoch_end)
        if not selected["saved"]:
            save()
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
                         label_order=classes, selected_on="val" if val else "")

    def _predict_rows(self, net, tokenizer, rows, card, device,
                      report: Optional[ProgressReporter] = None):
        import torch

        classes = card["node_classes"]
        questions: Dict[str, List[int]] = {}
        for n, c in enumerate(classes):
            questions.setdefault(c.split("=", 1)[0], []).append(n)
        params = {"max_length": card.get("max_length", 256)}
        net.eval()
        for done, row in enumerate(rows, 1):
            data = row if isinstance(row, dict) else (row.data or {})
            tree = data.get("tree")
            if not tree:
                continue
            pairs = list(walk(tree))
            decisions: List[float] = []
            nodes: Dict[str, Dict[str, str]] = {}
            with torch.inference_mode():
                pooled = net.pooled(self._encode(
                    tokenizer, [(_text(p), _text(n)) for n, p in pairs], params, device))
                node_probs = torch.softmax(net.node(pooled).float(), -1).cpu().tolist() \
                    if classes else []
                path_probs = torch.softmax(net.path(pooled).float(), -1)[:, 1].cpu().tolist()
            for k, (node, _) in enumerate(pairs):
                answers = {}
                for question, members in questions.items():
                    best = max(members, key=lambda m: node_probs[k][m])
                    answers[question] = classes[best].split("=", 1)[1]
                    share = sum(node_probs[k][m] for m in members) or 1.0
                    decisions.append(node_probs[k][best] / share)
                if answers:
                    nodes[str(node.get("id"))] = answers
            on_path = {id(node): path_probs[k] for k, (node, _) in enumerate(pairs)}
            path, current = [], tree
            if card.get("path_includes_root"):
                path.append(str(tree.get("id")))
            while current.get("children"):
                child = max(current["children"], key=lambda c: on_path.get(id(c), 0.0))
                if on_path.get(id(child), 0.0) <= 0.5:
                    break
                path.append(str(child.get("id")))
                decisions.append(on_path[id(child)])
                current = child
            payload = {"path": path if len(path) > int(bool(card.get("path_includes_root"))) else [],
                       "nodes": nodes}
            yield row, payload, (min(decisions) if decisions else None)
            if report is not None:
                report.progress("predict", done, len(rows))
                if report.should_stop():
                    return

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
        net = _network(torch, encoder, int(card["hidden_size"]), len(card["node_classes"]))
        net.load_heads(torch.load(os.path.join(model_dir, HEADS_FILE), map_location="cpu"))
        net = hf.place(net, device)
        items = list(items)
        for item, payload, confidence in self._predict_rows(net, tokenizer, items, card,
                                                            device, report):
            yield PredictionRecord(
                instance_id=item.instance_id, schema_name=card["schema"], payload=payload,
                confidence=None if confidence is None else round(float(confidence), 4))
