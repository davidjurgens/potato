"""``potato training ...``: the agent, agent tokens, and backend checks.

    potato training agent --server URL --backend NAME
    potato training register NAME config.yaml
    potato training check NAME config.yaml

``register`` and ``check`` read the project's config; ``agent`` does not,
because it runs on a machine that has none.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional


def _load_config(path: str) -> Dict[str, Any]:
    import yaml

    path = os.path.abspath(path)
    with open(path) as fh:
        config = yaml.safe_load(fh) or {}
    task_dir = config.get("task_dir", ".")
    if not os.path.isabs(task_dir):
        # Relative to the config file, as the server resolves it.
        config["task_dir"] = os.path.normpath(
            os.path.join(os.path.dirname(path), task_dir))
    return config


def _backend(config: Dict[str, Any], name: str):
    from potato.training.backends import load_backends

    backend = load_backends(config).get(name)
    if backend is None:
        names = ", ".join(sorted(load_backends(config)))
        raise SystemExit("No backend named %r under model_training.backends "
                         "(have: %s)" % (name, names))
    return backend


def _register(args) -> int:
    config = _load_config(args.config)
    backend = _backend(config, args.backend)
    if backend.type != "agent":
        print("Backend %r is type %r. Only type: agent backends take a "
              "token; Potato starts ssh backends itself."
              % (backend.name, backend.type), file=sys.stderr)
        return 2
    from potato.training import store

    token = store.register_backend(config, backend.name)
    port = config.get("port", 8000)
    print("Token for backend %r (shown once; registering again replaces "
          "it):\n\n  %s\n" % (backend.name, token))
    print("On the training machine:\n\n"
          "  export POTATO_TRAINING_TOKEN=%s\n"
          "  potato training agent --server http://<this-server>:%s "
          "--backend %s\n" % (token, port, backend.name))
    return 0


def _check(args) -> int:
    config = _load_config(args.config)
    backend = _backend(config, args.backend)
    if backend.type == "local":
        from potato.training.devices import describe_device, resolve_device
        device = resolve_device(
            (config.get("model_training") or {}).get("device", "auto"))
        print("local: this machine, %s" % describe_device(device))
        return 0
    if backend.type == "agent":
        from potato.training import store
        rows = [r for r in store.list_backends(config)
                if r["name"] == backend.name]
        if not rows:
            print("%s: no token issued yet. Run: potato training register "
                  "%s %s" % (backend.name, backend.name, args.config))
            return 1
        print(json.dumps(rows[0], indent=2))
        return 0

    from potato.training.launchers import check_backend
    report = check_backend(backend)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(report.get("message", ""))
        for gpu in report.get("gpus") or []:
            print("  GPU %d  %-24s %6d / %6d MB free  %3d%% busy%s"
                  % (gpu["index"], gpu["name"], gpu["free_mb"],
                     gpu["total_mb"], gpu["util"],
                     "  (torch there has no kernels for it)"
                     if gpu.get("supported") is False else ""))
        if report.get("missing"):
            print("  not installed there: %s" % ", ".join(report["missing"]))
    return 0 if report.get("ok") else 1


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "agent":
        from potato.training.agent import main as agent_main
        return agent_main(argv[1:])

    parser = argparse.ArgumentParser(
        prog="potato training",
        description="Training backends. `potato training agent --help` for "
                    "the agent.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("agent", help="Run training jobs on this machine")
    reg = sub.add_parser("register",
                         help="Issue a token for a type: agent backend")
    reg.add_argument("backend")
    reg.add_argument("config")
    chk = sub.add_parser("check", help="Test a backend: reachability, "
                                       "Python, GPUs, missing packages")
    chk.add_argument("backend")
    chk.add_argument("config")
    chk.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "register":
        return _register(args)
    return _check(args)


if __name__ == "__main__":
    sys.exit(main())
