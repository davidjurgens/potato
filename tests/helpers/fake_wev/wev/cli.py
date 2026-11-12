"""``python -m wev.cli train ...``: checks the data, prints wev's log lines,
writes a run directory with the arguments it was given."""
import argparse
import json
import os
import sys


def main():
    if len(sys.argv) < 2 or sys.argv[1] != "train":
        sys.exit(2)
    ap = argparse.ArgumentParser()
    for name in ("--init_from", "--data", "--out", "--epochs", "--lr",
                 "--batch_tokens", "--batch", "--accum", "--checkpointing",
                 "--max_state", "--max_branch", "--eval_n", "--log_every",
                 "--seed"):
        ap.add_argument(name)
    a = ap.parse_args(sys.argv[2:])
    rows = [json.loads(l) for l in open(os.path.join(a.data, "train.jsonl"))]
    assert os.path.isfile(os.path.join(a.data, "dev.jsonl"))
    if os.environ.get("FAKE_WEV_FAIL"):
        print("RuntimeError: CUDA out of memory", flush=True)
        sys.exit(1)
    epochs, batches = int(a.epochs), max(1, (len(rows) + 7) // 8)
    for ep in range(epochs):
        for b in range(batches):
            print("ep %d step %d batch %d/%d loss %.4f lr 5.0e-05 4.0 rec/s"
                  % (ep, ep * batches + b + 1, b + 1, batches, 0.5 / (ep + 1)),
                  flush=True)
        print("== epoch %d dev[%s]: %s" % (ep, os.path.basename(a.data), json.dumps(
            {"n": 3, "step_success": 0.5 + 0.1 * ep,
             "sentiment": {"n": 3, "accuracy": 0.5 + 0.1 * ep}})), flush=True)
    os.makedirs(os.path.join(a.out, "ckpt"), exist_ok=True)
    open(os.path.join(a.out, "head.pt"), "w").write("fake")
    json.dump({"args": vars(a), "rows": rows[:2]},
              open(os.path.join(a.out, "seen.json"), "w"))
    print("saved %s" % a.out, flush=True)


if __name__ == "__main__":
    main()
