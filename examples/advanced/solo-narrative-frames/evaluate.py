#!/usr/bin/env python
"""
Score the solo-mode prompt at each time step with several reference
models on the held-out Episodic/Thematic eval set.

Time step k = the prompt in effect after k simulated human labels (from
run/snapshots.jsonl, written by simulate.py). By default k = 0, 10, ..., 100.

Generative models (Ollama) get the exact prompt solo mode's labeler
sends, with the tweet substituted for {TEXT}, and their JSON "label" is
parsed (falling back to the first label name in the reply). Laya is
non-generative: it gets one yes/no question, "is this Episodic?", whose
instructions are the prompt's guidance (everything before "Text to
label:"), and predicts Episodic when P(yes) >= 0.5.

Every call is cached in run/eval/preds.jsonl keyed by (model, step,
item), so reruns only fill in what's missing.

Outputs:
  run/eval/preds.jsonl   one row per (model, step, item)
  run/eval/results.csv   model, step, n, accuracy, macro_f1, f1_episodic,
                         f1_thematic, n_unparsed

Usage (from repo root):
  python examples/advanced/solo-narrative-frames/evaluate.py
  python examples/advanced/solo-narrative-frames/evaluate.py --models qwen3.5:9b --steps 0,50,100
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
RUN = os.path.join(HERE, "run")
OUT = os.path.join(RUN, "eval")
LABELS = ("Episodic", "Thematic")

DEFAULT_MODELS = ["laya", "gemma4:e2b", "qwen3.5:9b", "llama3.1:8b"]


# ---------------------------------------------------------------- utils
def post(url, payload, timeout=600):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def parse_label(reply: str):
    m = re.search(r'"label"\s*:\s*"([^"]*)"', reply)
    cand = m.group(1) if m else reply
    for l in LABELS:
        if l.lower() in cand.lower():
            return l
    hits = [(reply.lower().find(l.lower()), l) for l in LABELS if l.lower() in reply.lower()]
    return min(hits)[1] if hits else None


def metrics(golds, preds):
    n = len(golds)
    acc = sum(g == p for g, p in zip(golds, preds)) / n
    f1 = {}
    for l in LABELS:
        tp = sum(g == l and p == l for g, p in zip(golds, preds))
        fp = sum(g != l and p == l for g, p in zip(golds, preds))
        fn = sum(g == l and p != l for g, p in zip(golds, preds))
        f1[l] = 2 * tp / (2 * tp + fp + fn) if tp else 0.0
    return acc, sum(f1.values()) / len(f1), f1


# ---------------------------------------------------------------- models
class OllamaModel:
    def __init__(self, name, base="http://localhost:11434"):
        self.name, self.base = name, base
        self.think_ok = True

    def __call__(self, template, text):
        prompt = template.replace("{TEXT}", text)
        body = {"model": self.name, "stream": False,
                "messages": [{"role": "user", "content": prompt}],
                "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 512}}
        if self.think_ok:
            body["think"] = False          # qwen3.5 / gemma4 reasoning off
        try:
            reply = post(self.base + "/api/chat", body)["message"]["content"]
        except urllib.error.HTTPError as e:
            if self.think_ok and e.code == 400:
                self.think_ok = False
                return self(template, text)
            raise
        return parse_label(reply), reply[:400]


class LayaModel:
    """One noul question per tweet via the laya_server.py sidecar."""
    name = "laya"

    def __init__(self, base="http://127.0.0.1:8770", head_max_len=400):
        self.base, self.head_max_len = base, head_max_len

    @staticmethod
    def question(template):
        guidance = template.split("Text to label:")[0].strip()
        return ("Is this tweet's narrative frame Episodic (yes) rather than Thematic (no)?\n"
                + guidance)

    def batch(self, template, texts):
        q = {"q": {"type": "noul", "instructions": self.question(template)}}
        out = []
        for i in range(0, len(texts), 32):
            res = post(self.base + "/predict_batch", {
                "states": texts[i:i + 32], "questions": q,
                "head_max_len": self.head_max_len, "batch_size": 8})
            if "error" in res:
                raise RuntimeError(res["error"])
            for r in res["results"]:
                p = float(r["answers"]["q"]["noul"])
                out.append(("Episodic" if p >= 0.5 else "Thematic", f"P(yes)={p:.3f}"))
        return out


# ---------------------------------------------------------------- main
def load_templates(steps):
    by_step = {}
    for line in open(os.path.join(RUN, "snapshots.jsonl")):
        row = json.loads(line)
        if row.get("template"):
            by_step[row["step"]] = row        # last snapshot at a step wins
    missing = [s for s in steps if s not in by_step]
    if missing:
        raise SystemExit(f"No snapshot for step(s) {missing}; have up to {max(by_step)}")
    return {s: by_step[s] for s in steps}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS))
    ap.add_argument("--steps", default="0,10,20,30,40,50,60,70,80,90,100")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args(argv)

    steps = [int(s) for s in args.steps.split(",")]
    templates = load_templates(steps)
    items = json.load(open(os.path.join(HERE, "data", "eval.json")))
    os.makedirs(OUT, exist_ok=True)
    pred_path = os.path.join(OUT, "preds.jsonl")

    done = {}
    if os.path.exists(pred_path):
        for line in open(pred_path):
            r = json.loads(line)
            done[(r["model"], r["step"], r["id"])] = r
    lock = threading.Lock()
    fh = open(pred_path, "a")

    def save(model, step, item, pred, raw):
        r = {"model": model, "step": step, "id": item["id"], "gold": item["label"],
             "pred": pred, "raw": raw, "prompt_version": templates[step]["prompt_version"]}
        with lock:
            fh.write(json.dumps(r) + "\n")
            fh.flush()
            done[(model, step, item["id"])] = r

    for name in args.models.split(","):
        for step in steps:
            tpl = templates[step]["template"]
            todo = [it for it in items if (name, step, it["id"]) not in done]
            if not todo:
                continue
            print(f"{name} step={step}: {len(todo)} items", flush=True)
            if name == "laya":
                for it, (p, raw) in zip(todo, LayaModel().batch(tpl, [t["text"] for t in todo])):
                    save(name, step, it, p, raw)
                continue
            m = OllamaModel(name)
            with cf.ThreadPoolExecutor(args.workers) as ex:
                futs = {ex.submit(m, tpl, it["text"]): it for it in todo}
                for f in cf.as_completed(futs):
                    p, raw = f.result()
                    save(name, step, futs[f], p, raw)

    rows = []
    for name in args.models.split(","):
        for step in steps:
            rs = [done[(name, step, it["id"])] for it in items]
            golds = [r["gold"] for r in rs]
            preds = [r["pred"] for r in rs]
            acc, mf1, f1 = metrics(golds, preds)
            rows.append({"model": name, "step": step,
                         "prompt_version": templates[step]["prompt_version"],
                         "n": len(rs), "accuracy": round(acc, 4), "macro_f1": round(mf1, 4),
                         "f1_episodic": round(f1["Episodic"], 4),
                         "f1_thematic": round(f1["Thematic"], 4),
                         "n_unparsed": sum(p is None for p in preds)})
    with open(os.path.join(OUT, "results.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print(f"{r['model']:14s} step={r['step']:3d} pv={r['prompt_version']} "
              f"acc={r['accuracy']:.3f} macroF1={r['macro_f1']:.3f} unparsed={r['n_unparsed']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
