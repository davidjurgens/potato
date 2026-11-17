#!/usr/bin/env python
"""
Minimal loopback HTTP sidecar around Laya (https://github.com/NandhaKishorM/laya)
for potato.codebook_lab.laya_scorer.

Laya needs Python 3.12 + torch, and potato's own venv can't import it, so
it runs in its own venv and the scorer talks to it over 127.0.0.1. Laya
ships `laya-serve`, but that needs fastapi/uvicorn; this file uses only
the standard library plus `laya`.

    ~/laya-venv/bin/python examples/advanced/codebook-lab-naacl-frames/laya_server.py --port 8770

Routes (JSON in, JSON out, one request at a time):
  POST /predict_batch  {states, questions, head_max_len?, max_len?, batch_size?}
                       -> {"results": [<Agent.predict result>, ...]}
  GET  /health         -> {"model": ..., "device": ...}
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

import laya

AGENT = None


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"model": AGENT.model_id, "device": str(AGENT.device)})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/predict_batch":
                results = AGENT.predict_batch(
                    body["states"], body["questions"],
                    batch_size=body.get("batch_size"),
                    max_len=body.get("max_len"),
                    head_max_len=body.get("head_max_len"))
                self._send(200, {"results": results})
            else:
                self._send(404, {"error": "not found"})
        except Exception as e:  # report, don't kill the server
            self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def log_message(self, fmt, *args):
        pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--model", default="convaiinnovations/laya")
    ap.add_argument("--subfolder", default=None,
                    help="e.g. multilingual or typed-decisions; default English")
    args = ap.parse_args(argv)

    global AGENT
    kwargs = {"subfolder": args.subfolder} if args.subfolder else {}
    AGENT = laya.load(args.model, **kwargs)
    AGENT.predict("warm up", {"q": {"type": "noul", "instructions": "Is this a test?"}})
    print(f"Laya {laya.__version__} on {AGENT.device}, "
          f"listening on 127.0.0.1:{args.port}", flush=True)
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
