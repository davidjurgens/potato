#!/usr/bin/env python
"""
Run a solo-mode session from scratch with a simulated human who always
gives the NAACL gold label, and snapshot the prompt the LLM sees after
every human label.

It drives the real Flask server over HTTP the way the browser does:
register -> /solo/setup -> skip edge cases -> loop over /solo/annotate
(fetch the LLM suggestion first, as the UI does, then submit gold) and
resolve every disagreement in the human's favour. Refinement cycles
run in a background thread inside the server; after each label the
simulator waits for any running cycle to finish so time steps are
deterministic with respect to the label count.

Outputs (run/ in this directory):
  snapshots.jsonl  one row per human label: step, prompt_version,
                   codebook_revision, template (full prompt with the
                   tweet replaced by {TEXT})
  versions.json    deduplicated time steps: [{t, first_step,
                   prompt_version, codebook_revision, template}]
  session.jsonl    per-label log (gold, llm suggestion, redirects)
  server.log

Usage (from repo root, Ollama running with llama3.1:8b):
  python examples/advanced/solo-narrative-frames/simulate.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from html import unescape

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
RUN = os.path.join(HERE, "run")
SCHEMA = "narrative_frame"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def hidden(html: str, name: str):
    m = re.search(r'name="%s"\s+(?:id="[^"]*"\s+)?value="([^"]*)"' % re.escape(name), html)
    return unescape(m.group(1)) if m else None


class Sim:
    def __init__(self, base, gold, texts):
        self.base, self.gold, self.texts = base, gold, texts
        self.s = requests.Session()
        self.step = 0
        self.snap_f = open(os.path.join(RUN, "snapshots.jsonl"), "a")
        self.sess_f = open(os.path.join(RUN, "session.jsonl"), "a")

    def url(self, p):
        return self.base + p

    def get(self, p, **kw):
        return self.s.get(self.url(p), timeout=900, **kw)

    def post(self, p, data, **kw):
        return self.s.post(self.url(p), data=data, timeout=900, **kw)

    def path(self, r):
        return r.url[len(self.base):].split("?")[0]

    # -- setup ---------------------------------------------------------
    def setup(self, task_description):
        self.post("/register", {"email": "sim", "pass": "sim"})
        r = self.post("/auth", {"email": "sim", "pass": "sim"})
        r = self.get("/solo/setup")
        if 'already_configured' not in r.text and self.path(r) == "/solo/setup":
            r = self.post("/solo/setup", {"task_description": task_description})
            log("setup ->", self.path(r))
        r = self.post("/solo/prompt", {"action": "skip_to_annotation"})
        log("skip edge cases ->", self.path(r))

    # -- snapshots -----------------------------------------------------
    def snapshot(self, instance_id):
        pv = self.get("/solo/prompt-preview", params={"instance_id": instance_id}).json()
        full, text = pv["full_prompt"], self.texts[instance_id]
        i = full.find(text)
        template = full[:i] + "{TEXT}" + full[i + len(text):] if i >= 0 else None
        row = {"step": self.step, "prompt_version": pv.get("prompt_version"),
               "codebook_revision": pv.get("codebook_revision"),
               "template": template, "instance_id": instance_id}
        if template is None:
            row["full_prompt"] = full
            log(f"WARNING: tweet text not found verbatim in prompt for {instance_id}")
        self.snap_f.write(json.dumps(row) + "\n")
        self.snap_f.flush()

    def wait_for_refinement(self, timeout=1800):
        t0 = time.time()
        time.sleep(1.0)
        while time.time() - t0 < timeout:
            st = self.get("/solo/api/refinement-status").json()
            if not st.get("is_running"):
                return st
            time.sleep(3)
        log("refinement still running after timeout; continuing")

    # -- one label -----------------------------------------------------
    def label(self, instance_id, html=None):
        # As the UI does, make sure the LLM has labeled this item before the
        # human answers, so the label is compared (retry transient failures).
        for attempt in range(3):
            sugg = self.get("/solo/llm-suggestion", params={"instance_id": instance_id}).json()
            if sugg.get("available") and sugg.get("label"):
                break
            time.sleep(2)
        gold = self.gold[instance_id]
        r = self.post("/solo/annotate", {"instance_id": instance_id, "annotation": gold})
        self.step += 1
        rec = {"step": self.step, "instance_id": instance_id, "gold": gold,
               "llm": sugg.get("label"), "llm_conf": sugg.get("confidence"),
               "after": self.path(r)}
        self.sess_f.write(json.dumps(rec) + "\n")
        self.sess_f.flush()
        log(f"#{self.step:3d} {instance_id} gold={gold:9s} llm={sugg.get('label')!s:9s} -> {rec['after']}")
        return r

    def resolve_disagreements(self, r):
        n = 0
        while self.path(r) == "/solo/disagreements":
            did = hidden(r.text, "disagreement_id")
            if not did:
                break
            r = self.post("/solo/disagreements",
                          {"disagreement_id": did, "resolution": "human", "notes": ""})
            n += 1
            if n > 200:
                raise RuntimeError("disagreement loop")
        return r

    def back_to_frontier(self):
        """Jumping to an older item (?instance_id=) moves solo mode's Back/Next
        cursor back into the history, and every plain 'next' after that
        replays already-labeled items instead of fetching a new one. The
        history lives in the login session, so start a fresh session: its
        history is empty and the next plain request asks the instance
        selector, which never returns an already-labeled item."""
        self.s = requests.Session()
        self.post("/auth", {"email": "sim", "pass": "sim"})

    def run(self, max_labels):
        seen_stale = set()
        replays = 0
        # Resume: items already labeled in an earlier (crashed) run of this
        # same solo state count toward the step total.
        self.labeled, self.frontier = set(), None
        sess_path = os.path.join(RUN, "session.jsonl")
        if os.path.exists(sess_path):
            for line in open(sess_path):
                rec = json.loads(line)
                self.labeled.add(rec["instance_id"])
                self.frontier = rec["instance_id"]
            self.step = len(self.labeled)
            if self.step:
                log(f"resuming after {self.step} labeled items")
        while self.step < max_labels:
            r = self.get("/solo/annotate")
            p = self.path(r)
            if p == "/solo/disagreements":
                r = self.resolve_disagreements(r)
                continue
            if p == "/solo/codebook-review":
                stale = [i for i in re.findall(r'instance_id=([^"&]+)', r.text)
                         if i in self.gold and i not in seen_stale]
                if not stale:
                    log("codebook-review with nothing actionable; stopping")
                    break
                # Re-confirm labels made under an older codebook (mandatory
                # in the UI). Not counted as time steps: no new item is seen.
                for iid in stale:
                    seen_stale.add(iid)
                    self.get("/solo/annotate", params={"instance_id": iid})
                    rr = self.post("/solo/annotate", {"instance_id": iid, "annotation": self.gold[iid]})
                    self.resolve_disagreements(rr)
                log(f"re-confirmed {len(stale)} stale label(s)")
                self.back_to_frontier()
                continue
            if p == "/solo/final-override":
                log("reached final-override (nothing left to label)")
                break
            if p != "/solo/annotate":
                log("unexpected page", p)
                break
            iid = hidden(r.text, "instance_id")
            if not iid or iid not in self.gold:
                log("no instance on annotate page; stopping")
                break
            if iid in self.labeled:          # history replay, not a new item
                replays += 1
                if replays > 50:
                    raise RuntimeError("stuck replaying labeled items")
                self.back_to_frontier()
                continue
            replays = 0
            self.snapshot(iid)               # prompt in effect for this label
            self.labeled.add(iid)
            self.frontier = iid
            r = self.label(iid)
            r = self.resolve_disagreements(r)
            self.wait_for_refinement()
        # final prompt after the last label / refinement
        self.wait_for_refinement()
        self.snapshot(next(iter(self.gold)))


def dedupe(path_in, path_out):
    rows = [json.loads(l) for l in open(path_in)]
    versions, last = [], None
    for row in rows:
        tpl = row.get("template")
        if tpl is None or tpl == last:
            continue
        versions.append({"t": len(versions), "first_step": row["step"],
                         "prompt_version": row["prompt_version"],
                         "codebook_revision": row["codebook_revision"],
                         "template": tpl})
        last = tpl
    json.dump(versions, open(path_out, "w"), indent=1)
    return versions


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=8011)
    ap.add_argument("--max-labels", type=int, default=100)
    ap.add_argument("--fresh", action="store_true",
                    help="delete prior solo state/annotations/run outputs first")
    args = ap.parse_args(argv)

    import yaml
    cfg = yaml.safe_load(open(os.path.join(HERE, "config.yaml")))
    gold = json.load(open(os.path.join(HERE, "data", "train_gold.json")))
    texts = {d["id"]: d["text"] for d in json.load(open(os.path.join(HERE, "data", "train.json")))}

    if args.fresh:
        for d in ("solo_state", "annotations", "run", "user_config.json"):
            p = os.path.join(HERE, d)
            if os.path.isdir(p):
                shutil.rmtree(p)
            elif os.path.exists(p):
                os.remove(p)
    os.makedirs(RUN, exist_ok=True)

    server_log = open(os.path.join(RUN, "server.log"), "a")
    proc = subprocess.Popen(
        [sys.executable, "potato/flask_server.py", "start",
         os.path.join(HERE, "config.yaml"), "-p", str(args.port)],
        cwd=REPO_ROOT, stdout=server_log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{args.port}"
    try:
        for _ in range(120):
            try:
                requests.get(base, timeout=2)
                break
            except requests.RequestException:
                time.sleep(1)
        sim = Sim(base, gold, texts)
        sim.setup(cfg["task_description"].strip())
        sim.run(args.max_labels)
        versions = dedupe(os.path.join(RUN, "snapshots.jsonl"),
                          os.path.join(RUN, "versions.json"))
        log(f"done: {sim.step} labels, {len(versions)} distinct prompt versions")
        for v in versions:
            log(f"  t={v['t']} first_step={v['first_step']} pv={v['prompt_version']} "
                f"cb={v['codebook_revision']} len={len(v['template'])}")
    finally:
        proc.terminate()
        proc.wait(timeout=30)
    return 0


if __name__ == "__main__":
    sys.exit(main())
