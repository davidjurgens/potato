"""
``potato label``: run the labeling engine without the web server.

    potato label run      CONFIG [--until predicted|met] [--max-items N]
                                 [--budget-usd X] [--max-ticks K] [--json]
    potato label status   CONFIG [--json]
    potato label certify  CONFIG [--json] [--retest]
    potato label export       CONFIG [--out DIR]
    potato label certificate  CONFIG [--format md|html|json] [--out FILE]
    potato label calls        CONFIG [--out FILE]
    potato label distill      CONFIG
    potato label optimize     CONFIG [--prompts N]
    potato label migrate-config CONFIG [--out FILE]

``run`` takes the study's single-writer lock. If a server is running on the
same study its planner holds the lock, and ``run`` says so and stops: two
writers would draw two calibration samples and certify against each other's
half-written state. Labels people give through that server reach the ledger
as they are saved, so ``status`` and ``certify`` can run alongside it.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def load_study(config_file: str) -> Tuple[Dict[str, Any], List[Any]]:
    """The study's config and its items, loaded the way the server loads them."""
    from potato.server_utils.config_module import init_config
    import potato.server_utils.config_module as cm
    args = SimpleNamespace(config_file=config_file, verbose=False, very_verbose=False,
                           customjs=None, customjs_hostname=None, debug=False,
                           persist_sessions=False, require_password=None, port=None)
    init_config(args)
    config = cm.config
    from potato.item_state_management import (
        clear_item_state_manager, get_item_state_manager, init_item_state_manager)
    from potato.user_state_management import (
        clear_user_state_manager, init_user_state_manager)
    clear_item_state_manager()
    clear_user_state_manager()
    init_user_state_manager(config)
    init_item_state_manager(config)
    from potato.flask_server import load_instance_data
    load_instance_data(config)
    from .items import views_from_item_manager
    return config, views_from_item_manager(get_item_state_manager(), config)


def _engine(config, budget_usd: Optional[float] = None):
    from .config import parse_engine_config
    from .service import Engine
    cfg = parse_engine_config(config)
    if not cfg.enabled:
        raise SystemExit("labeling_engine is not enabled in this config")
    if budget_usd is not None:
        cfg.budgets["model_usd"] = float(budget_usd)
    return Engine(config, engine_cfg=cfg)


def _print(obj, as_json: bool) -> None:
    if as_json:
        print(json.dumps(obj, indent=2, default=str))
        return
    for line in _human_lines(obj):
        print(line)


def _human_lines(status: Dict[str, Any]) -> List[str]:
    lines = [f"Items: {status.get('items', 0)}   predictions: "
             f"{status.get('predictions', 0)}   model calls: "
             f"{(status.get('calls') or {}).get('n_calls', 0)}"]
    cost = (status.get("calls") or {}).get("cost_usd")
    if cost is not None:
        lines.append(f"Model spend: ${cost:.4f}")
    reqs = status.get("requests") or {}
    if reqs:
        # As the certificate counts them: cancelled requests apart, and
        # organic labels (nobody asked for them) not as requests at all.
        parts = [f"{p} {sum(n for st, n in v.items() if st != 'cancelled')} "
                 f"({v.get('done', 0)} answered"
                 + (f"; {v['cancelled']} cancelled" if v.get("cancelled") else "") + ")"
                 for p, v in sorted(reqs.items()) if p != "organic"]
        line = "Human requests: " + (", ".join(parts) or "none")
        organic = (reqs.get("organic") or {}).get("done", 0)
        if organic:
            line += f". Organic labels (not requested): {organic}"
        lines.append(line)
    for name, s in (status.get("schemes") or {}).items():
        if s.get("status") == "unsupported":
            lines.append(f"\n{name}: unsupported, no cascade source can label it")
            lines.extend(f"    {r}" for r in s.get("reasons") or [])
            continue
        lines.append(f"\n{name}: cascade {' -> '.join(s.get('tiers') or [])}")
        for sid, h in (s.get("sources") or {}).items():
            run = h.get("last_run") or {}
            if h.get("error") or run.get("status") in ("failed", "paused"):
                line = f"  source {sid}: {h.get('ok', 0)} ok, {h.get('abstain', 0)} abstained, " \
                       f"{h.get('error', 0)} errors"
                if run.get("status") in ("failed", "paused"):
                    line += f"; last run {run['status']}: {run.get('message')}"
                elif h.get("last_error"):
                    line += f"; last error: {h['last_error']}"
                lines.append(line)
        for cid, c in (s.get("contracts") or {}).items():
            line = f"  {cid} ({c.get('kind')}): {c.get('status')}"
            if c.get("audits_breached") and c.get("status") == "met":
                line += f" (audits breached the target at audit {c['audits_breached']})"
            cov = (c.get("metrics") or {}).get("coverage")
            if cov is not None:
                line += f", coverage {cov:.1%}"
            proj = c.get("projection") or {}
            more = proj.get("more_calibration_labels")
            if more and c.get("status") != "met":
                if proj.get("reachable") is False:
                    line += (f", not reachable with this corpus (about {more:,} more labels "
                             f"needed, {proj.get('items_left', 0):,} items left)")
                else:
                    line += f", about {more} more calibration labels needed"
            lines.append(line)
            if c.get("statement") and c.get("status") == "met":
                lines.append(f"    {c['statement']}")
        unmet = [(cid, c) for cid, c in (s.get("contracts") or {}).items()
                 if c.get("kind") == "selective_risk" and c.get("status") != "met"]
        if unmet:
            lines.append(f"  No machine label is accepted on {name} until every "
                         f"selective_risk contract is met. Not met: "
                         + ", ".join(cid for cid, _ in unmet) + ".")
            for cid, c in unmet:
                if c.get("status") == "infeasible":
                    lines.append(f"  {cid} cannot be met with these sources: loosen or "
                                 "remove it, or change the cascade. Until then the "
                                 "remaining items go to people.")
        if s.get("unlabeled"):
            left = ((status.get("budgets") or {}).get("human_labels") or {})
            spent = left and left.get("limit") is not None and left.get("spent", 0) >= left["limit"]
            lines.append(f"  {s['unlabeled']:,} items have no label yet" + (
                ": the human-label budget is spent" if spent else ""))
        res = s.get("resolved") or {}
        if res:
            lines.append("  labels: " + ", ".join(f"{k} {v}" for k, v in sorted(res.items())))
    return lines


def cmd_run(ns) -> int:
    from .allocation.planner import Planner
    config, items = load_study(ns.config)
    engine = _engine(config, ns.budget_usd)
    holder = engine.store.writer_name("cli")
    if not engine.store.acquire_writer(holder):
        print(f"Another process ({engine.store.writer_holder()}) is driving this study, "
              "probably a running server. Let its planner do the work, or stop it first. "
              "If it has already stopped, the lock frees itself within 2 minutes.",
              file=sys.stderr)
        return 2
    try:
        if ns.max_items is not None:
            items = items[:ns.max_items]
        planner = Planner(engine, item_source=lambda e: items)
        last = None
        for tick in range(max(1, ns.max_ticks)):
            with engine.store.holding_writer(holder):
                report = planner.tick()
            last = report
            if ns.until == "predicted":
                break
            contracts = [c for s in engine.status()["schemes"].values()
                         for c in s["contracts"].values()]
            if contracts and all(c.get("status") == "met" for c in contracts):
                break
            waiting = any((r.get("more") or {}).get("waiting_on")
                          for r in report["schemes"].values())
            if waiting:
                print("Waiting on human labels; start the server so people can answer "
                      "the open requests, then run this again.", file=sys.stderr)
                break
        out = {"tick": last, "status": engine.status()}
        _print(out if ns.json else out["status"], ns.json)
        # Non-zero when a source's last run failed or a contract's scheme
        # cannot be labeled, so a script does not take "0 predictions" as done.
        failed = [f"{name}/{sid}" for name, s in out["status"]["schemes"].items()
                  for sid, h in (s.get("sources") or {}).items()
                  if (h.get("last_run") or {}).get("status") == "failed"
                  or (h.get("error") and not h.get("ok") and not h.get("abstain"))]
        unsupported = [n for n, s in out["status"]["schemes"].items()
                       if s.get("status") == "unsupported"]
        if failed or unsupported:
            print("Failed: " + ", ".join(failed + [f"{n} (unsupported)" for n in unsupported]),
                  file=sys.stderr)
            return 1
        return 0
    finally:
        engine.store.release_writer(holder)


def cmd_status(ns) -> int:
    config, _ = load_study(ns.config)
    _print(_engine(config).status(), ns.json)
    return 0


def cmd_certify(ns) -> int:
    config, _ = load_study(ns.config)
    engine = _engine(config)
    driver = engine.store.live_writer()
    if driver is not None:
        # Certifying writes contract results and spends looks; with a server
        # driving the study that would race its planner. Its own certify
        # (REST /api/engine/v1/certify, or the admin page) runs in step.
        print(f"{driver} is driving this study. Certify through it instead "
              "(POST /api/engine/v1/certify, or the admin page's Certify button), "
              "or stop it first.", file=sys.stderr)
        return 2
    out = {s.name: engine.certify(s, retest=ns.retest) for s in engine.schemes()}
    if ns.json:
        _print(out, True)
    else:
        _print(engine.status(), False)
    return 0


def _writer(path: Optional[str]):
    return open(path, "w", encoding="utf-8") if path else sys.stdout


def cmd_export(ns) -> int:
    """The engine's deliverable into a directory: labels with provenance, the
    certificate in three forms, a dataset card and the call log."""
    config, items = load_study(ns.config)
    from potato.export.base import ExportContext
    from potato.export.registry import export_registry
    out = ns.out or os.path.join(config.get("output_annotation_dir") or ".", "labeling_engine")
    ctx = ExportContext(config=config, annotations=[], items={},
                        schemas=config.get("annotation_schemes") or [],
                        output_dir=config.get("output_annotation_dir") or ".")
    res = export_registry.export("labeling_engine", ctx, out)
    if not res.success:
        print("; ".join(res.errors), file=sys.stderr)
        return 1
    print(f"Wrote {res.stats.get('labels', 0)} labels and the certificate to {out}",
          file=sys.stderr)
    return 0


def cmd_certificate(ns) -> int:
    from .certificate import build_certificate, render_html, render_markdown
    config, _ = load_study(ns.config)
    cert = build_certificate(_engine(config))
    text = {"json": lambda: json.dumps(cert, indent=2, default=str),
            "md": lambda: render_markdown(cert), "html": lambda: render_html(cert)}[ns.format]()
    if ns.out:
        with open(ns.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Wrote the certificate to {ns.out}", file=sys.stderr)
    else:
        print(text)
    return 0


def cmd_distill(ns) -> int:
    from . import distill
    config, items = load_study(ns.config)
    engine = _engine(config)
    if not engine.cfg.feature("distill"):
        print("features.distill is off; turn it on to use distilled tiers.", file=sys.stderr)
        return 1
    out = {}
    for scheme in engine.schemes():
        entry = distill.distill_scheme(engine, scheme, items)
        out[scheme.name] = entry or "not enough accepted labels yet"
    _print(out, True)
    return 0


def cmd_optimize(ns) -> int:
    from . import optimize
    config, items = load_study(ns.config)
    engine = _engine(config)
    out = {}
    for scheme in engine.schemes():
        out[scheme.name] = {"cascades": optimize.cascade_report(engine, scheme)}
        if ns.prompts:
            out[scheme.name]["prompts"] = optimize.prompt_search(
                engine, scheme, items, n_variants=ns.prompts)
    _print(out, True)
    return 0


def cmd_migrate_config(ns) -> int:
    """Print the config with an equivalent labeling_engine block added.

    Reads the YAML directly (no data loading). The block is disabled: read
    the notes, then set enabled: true.
    """
    import yaml
    from .config.schema import EngineConfigError, parse_engine_config
    from .config.translate import deprecation_warnings, translate
    with open(ns.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if cfg.get("labeling_engine"):
        print("This config already has a labeling_engine block.", file=sys.stderr)
        return 1
    block, notes = translate(cfg)
    if block is None:
        print("Nothing to translate: no machine-labeling block in this config.",
              file=sys.stderr)
        return 1
    try:
        parse_engine_config({**cfg, "labeling_engine": {**block, "enabled": True}})
    except EngineConfigError as e:
        notes.append(f"The translated block needs edits before it validates: {e}")
    out = dict(cfg)
    out["labeling_engine"] = block
    header = ["# Translated by `potato label migrate-config`. The labeling_engine block",
              "# is disabled; read these notes, then set enabled: true.", "#"]
    header += [f"# - {n}" for n in notes + deprecation_warnings(cfg)]
    text = "\n".join(header) + "\n" + yaml.safe_dump(out, sort_keys=False,
                                                       allow_unicode=True)
    if ns.out:
        with open(ns.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Wrote {ns.out}", file=sys.stderr)
    else:
        print(text)
    return 0


def cmd_calls(ns) -> int:
    config, _ = load_study(ns.config)
    engine = _engine(config)
    f = _writer(ns.out)
    try:
        offset, n = 0, 0
        while True:
            batch = engine.store.calls(limit=5000, offset=offset)
            if not batch:
                break
            for c in batch:
                f.write(json.dumps(c.__dict__, default=str) + "\n")
                n += 1
            offset += len(batch)
    finally:
        if ns.out:
            f.close()
    if ns.out:
        print(f"Wrote {n} calls to {ns.out}", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="potato label",
                                description="Run the labeling engine on a study.")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="label, sample, certify and resolve")
    run.add_argument("config")
    run.add_argument("--until", choices=("predicted", "met"), default="predicted",
                     help="stop after one pass (predicted) or once every contract "
                          "is met or the engine is waiting on people (met)")
    run.add_argument("--max-items", type=int, default=None)
    run.add_argument("--budget-usd", type=float, default=None,
                     help="override budgets.model_usd for this run")
    run.add_argument("--max-ticks", type=int, default=20)
    run.add_argument("--json", action="store_true")
    run.set_defaults(fn=cmd_run)

    for name, fn, help_ in (("status", cmd_status, "show progress and contracts"),
                            ("certify", cmd_certify, "evaluate every contract now")):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("config")
        sp.add_argument("--json", action="store_true")
        if name == "certify":
            sp.add_argument("--retest", action="store_true",
                            help="also test when only dev labels changed the rule "
                                 "(spends a look)")
        sp.set_defaults(fn=fn)

    sp = sub.add_parser("export", help="labels with provenance, the certificate and the "
                                       "call log, into a directory")
    sp.add_argument("config")
    sp.add_argument("--out", default=None,
                    help="directory (default: <output_annotation_dir>/labeling_engine)")
    sp.set_defaults(fn=cmd_export)

    sp = sub.add_parser("certificate", help="the quality certificate")
    sp.add_argument("config")
    sp.add_argument("--format", choices=("md", "html", "json"), default="md")
    sp.add_argument("--out", default=None, help="file to write (default: stdout)")
    sp.set_defaults(fn=cmd_certificate)

    sp = sub.add_parser("distill", help="train a cheap model on the labels so far and "
                                        "put it first in the cascade")
    sp.add_argument("config")
    sp.set_defaults(fn=cmd_distill)

    sp = sub.add_parser("optimize", help="report cheaper cascades (and, with --prompts N, "
                                         "N prompt variants), scored on dev labels")
    sp.add_argument("config")
    sp.add_argument("--prompts", type=int, default=0)
    sp.set_defaults(fn=cmd_optimize)

    sp = sub.add_parser("migrate-config", help="add an equivalent labeling_engine block "
                                               "to a config that uses older keys")
    sp.add_argument("config")
    sp.add_argument("--out", default=None, help="file to write (default: stdout)")
    sp.set_defaults(fn=cmd_migrate_config)

    sp = sub.add_parser("calls", help="the model-call audit log, as JSON lines")
    sp.add_argument("config")
    sp.add_argument("--out", default=None, help="file to write (default: stdout)")
    sp.set_defaults(fn=cmd_calls)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    ns = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    from potato.server_utils.config_module import ConfigSecurityError, ConfigValidationError
    try:
        return ns.fn(ns)
    except (ConfigValidationError, ConfigSecurityError, FileNotFoundError):
        # init_config has already printed the message; a traceback after it
        # only buries it.
        return 1
