"""
Ego Network Exporter

For ``ego_network`` schemes, on annotation items or on survey (phase) pages.
Writes, under the output directory:

    egos.csv      one row per network (participant x item, or participant x
                  survey page): network size, ties, possible ties
                  (n(n-1)/2), density, isolates, components, and whether the
                  network meets the scheme's own completeness rules
    alters.csv    one row per alter: pseudonymous id, the name generators that
                  named them, sociogram position, degree, and every attribute
                  (name interpreter answers and name generator ``sets``)
    edges.csv     one row per alter-alter tie, with its relation and any tie
                  attributes (``strength`` from a dyad census)
    graphml/<user>__<item>.graphml
                  one GraphML file per network, alters as nodes with their
                  attributes as node data, ties as undirected edges

The ego is not a node: the files describe the alters and the ties among them,
which is the usual shape for personal-network analysis (density, components
and degree are all alter-alter measures).

Alter names are personal data about people who did not consent to the study.
They are left out unless the export is run with ``export_names=true``
(``--option export_names=true``); without it every file carries the
pseudonymous alter ids (``a1``, ``a2``, ...) only. The raw annotation output
(``annotation_output/``) and the general-purpose exports still hold the
names as typed.
"""

from __future__ import annotations

import csv
import json
import os
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

GRAPHML_NS = "http://graphml.graphdrawing.org/xmlns"
_TRUE = {"1", "true", "yes", "on"}


def _flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in _TRUE


def _safe(part: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(part)).strip("_") or "x"


def _cell(value: Any) -> Any:
    if isinstance(value, list):
        return "|".join(str(v) for v in value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return value


def _raw_value(labels: Any, schema: str) -> Any:
    """The stored JSON for one scheme in an annotation record's labels."""
    if not isinstance(labels, dict):
        return None
    raw = labels.get(schema)
    if isinstance(raw, dict):
        raw = raw.get(schema, next(iter(raw.values()), None) if len(raw) == 1 else None)
    return raw


def network_stats(alters: List[dict], ties: List[list]) -> Dict[str, Any]:
    """Size, ties, possible ties, density, isolates and components.

    Ties of different relations between the same two alters count once:
    density is over pairs, and n_ties is the number of connected pairs.
    """
    ids = [a["id"] for a in alters]
    n = len(ids)
    pairs = {tuple(sorted((t[0], t[1]))) for t in ties if t[0] in ids and t[1] in ids}
    possible = n * (n - 1) // 2
    adj: Dict[str, set] = {i: set() for i in ids}
    for a, b in pairs:
        adj[a].add(b)
        adj[b].add(a)
    seen, components = set(), 0
    for i in ids:
        if i in seen:
            continue
        components += 1
        stack = [i]
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            stack.extend(adj[x] - seen)
    return {
        "network_size": n,
        "n_ties": len(pairs),
        "possible_ties": possible,
        "density": round(len(pairs) / possible, 6) if possible else "",
        "isolates": sum(1 for i in ids if not adj[i]),
        "components": components,
        "degree": {i: len(adj[i]) for i in ids},
    }


class EgoNetworkExporter(BaseExporter):
    format_name = "ego_network"
    description = "Ego networks: egos.csv, alters.csv, edges.csv and one GraphML file per network (names opt-in)"
    file_extensions = [".csv", ".graphml"]

    # ------------------------------------------------------------------

    def _annotation_schemes(self, context: ExportContext) -> Dict[str, dict]:
        return {s["name"]: s for s in context.schemas or []
                if isinstance(s, dict) and s.get("annotation_type") == "ego_network"}

    def _phase_schemes(self, context: ExportContext) -> Dict[str, dict]:
        """ego_network schemes declared in survey-page files, by name."""
        out: Dict[str, dict] = {}
        try:
            from potato.server_utils.phase_files import (
                load_phase_schemes, question_file_phases, resolve_phase_file)
        except Exception:
            return out
        config = context.config or {}
        base = config.get("task_dir") or None
        for _phase, filename in question_file_phases(config):
            path = resolve_phase_file(filename, base)
            if not path:
                continue
            try:
                schemes = load_phase_schemes(path)
            except Exception:
                continue
            for s in schemes or []:
                if isinstance(s, dict) and s.get("annotation_type") == "ego_network" and s.get("name"):
                    out[s["name"]] = s
        return out

    def _networks(self, context: ExportContext) -> Tuple[List[dict], List[str]]:
        from potato.server_utils.schemas.ego_network import (
            EgoNetworkConfigError, normalize_stages, parse_answer)
        warnings: List[str] = []
        schemes = self._annotation_schemes(context)
        phase_schemes = self._phase_schemes(context)
        stages_cache: Dict[str, Optional[list]] = {}

        def stages_for(name: str, scheme: Optional[dict]) -> Optional[list]:
            if name not in stages_cache:
                try:
                    stages_cache[name] = normalize_stages(scheme) if scheme else None
                except EgoNetworkConfigError as e:
                    warnings.append(f"{name}: scheme does not validate ({e}); completeness not checked")
                    stages_cache[name] = None
            return stages_cache[name]

        networks = []
        for ann in context.annotations or []:
            for name, scheme in schemes.items():
                answer = parse_answer(_raw_value(ann.get("labels"), name))
                if answer is None:
                    continue
                networks.append({"user_id": str(ann.get("user_id", "")),
                                 "item": str(ann.get("instance_id", "")), "source": "annotation",
                                 "schema": name, "answer": answer,
                                 "stages": stages_for(name, scheme)})
        latest: Dict[Tuple[str, str, str], dict] = {}
        for row in context.phase_responses or []:
            name = row.get("schema")
            if not name or (phase_schemes and name not in phase_schemes and name not in schemes):
                continue
            answer = parse_answer(row.get("value"))
            if answer is None:
                continue
            key = (str(row.get("user_id", "")), str(row.get("page", "")), name)
            latest[key] = {"user_id": key[0], "item": key[1], "source": str(row.get("phase", "phase")),
                           "schema": name, "answer": answer,
                           "stages": stages_for(name, phase_schemes.get(name) or schemes.get(name))}
        networks.extend(latest.values())
        return networks, warnings

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not self._annotation_schemes(context) and not self._phase_schemes(context):
            return False, "No ego_network scheme in this project (annotation schemes or survey pages)"
        if not context.annotations and not context.phase_responses:
            return False, "No annotations to export"
        return True, ""

    # ------------------------------------------------------------------

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        from potato.server_utils.schemas.ego_network import incomplete_reasons
        options = options or {}
        names = _flag(options.get("export_names", False))
        os.makedirs(output_path, exist_ok=True)
        graph_dir = os.path.join(output_path, "graphml")
        os.makedirs(graph_dir, exist_ok=True)
        networks, warnings = self._networks(context)

        attr_keys: List[str] = []
        tie_keys: List[str] = []
        for net in networks:
            for attrs in net["answer"]["attributes"].values():
                for k in attrs:
                    if k not in attr_keys:
                        attr_keys.append(k)
            for attrs in net["answer"]["tie_attributes"].values():
                if isinstance(attrs, dict):
                    for k in attrs:
                        if k not in tie_keys:
                            tie_keys.append(k)

        egos, alters_rows, edge_rows, files = [], [], [], []
        used_files: Dict[str, int] = {}
        for net in networks:
            ans = net["answer"]
            stats = network_stats(ans["alters"], ans["ties"])
            base = {"user_id": net["user_id"], "item": net["item"], "source": net["source"],
                    "schema": net["schema"]}
            reasons = incomplete_reasons(net["stages"], ans) if net["stages"] else []
            relations = sorted({t[2] if len(t) > 2 else "" for t in ans["ties"]})
            egos.append({**base, **{k: v for k, v in stats.items() if k != "degree"},
                         "relations": "|".join(r or "tie" for r in relations),
                         "complete": "" if net["stages"] is None else ("true" if not reasons else "false"),
                         "incomplete_reason": "; ".join(reasons)})
            order = {a["id"]: i for i, a in enumerate(ans["alters"])}
            for a in ans["alters"]:
                pos = ans["positions"].get(a["id"]) or ["", ""]
                row = {**base, "alter_id": a["id"], "named_in": "|".join(a["named_in"]),
                       "x": pos[0], "y": pos[1], "degree": stats["degree"].get(a["id"], 0)}
                if names:
                    row["name"] = a["name"]
                attrs = ans["attributes"].get(a["id"]) or {}
                for k in attr_keys:
                    row[f"attr_{k}"] = _cell(attrs.get(k))
                alters_rows.append(row)
            for t in ans["ties"]:
                rel = t[2] if len(t) > 2 else ""
                a, b = (t[0], t[1]) if order[t[0]] < order[t[1]] else (t[1], t[0])
                tattrs = ans["tie_attributes"].get(f"{a}|{b}" + (f"|{rel}" if rel else "")) or {}
                row = {**base, "source_alter": a, "target_alter": b, "relation": rel or "tie"}
                for k in tie_keys:
                    row[f"tie_{k}"] = _cell(tattrs.get(k) if isinstance(tattrs, dict) else None)
                edge_rows.append(row)

            fname = f"{_safe(net['user_id'])}__{_safe(net['item'])}"
            if len(set(n["schema"] for n in networks)) > 1:
                fname += f"__{_safe(net['schema'])}"
            used_files[fname] = used_files.get(fname, 0) + 1
            if used_files[fname] > 1:
                fname += f"__{used_files[fname]}"
            path = os.path.join(graph_dir, fname + ".graphml")
            self._write_graphml(path, net, ans, attr_keys, tie_keys, names, stats)
            files.append(path)

        def write(fname, columns, rows):
            path = os.path.join(output_path, fname)
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
                w.writeheader()
                for r in rows:
                    w.writerow(r)
            files.insert(0, path)

        base_cols = ["user_id", "item", "source", "schema"]
        write("edges.csv", base_cols + ["source_alter", "target_alter", "relation"]
              + [f"tie_{k}" for k in tie_keys], edge_rows)
        write("alters.csv", base_cols + ["alter_id"] + (["name"] if names else [])
              + ["named_in", "x", "y", "degree"] + [f"attr_{k}" for k in attr_keys], alters_rows)
        write("egos.csv", base_cols + ["network_size", "n_ties", "possible_ties", "density",
                                       "isolates", "components", "relations", "complete",
                                       "incomplete_reason"], egos)
        if not networks:
            warnings.append("No ego network answers were found")
        if not names:
            warnings.append("Alter names were left out (pseudonymous ids only); "
                            "pass export_names=true to include them")
        return ExportResult(success=True, format_name=self.format_name, files_written=files,
                            warnings=warnings,
                            stats={"networks": len(networks), "alters": len(alters_rows),
                                   "ties": len(edge_rows), "names_exported": names})

    @staticmethod
    def _write_graphml(path: str, net: dict, ans: dict, attr_keys: List[str], tie_keys: List[str],
                       names: bool, stats: dict) -> None:
        ET.register_namespace("", GRAPHML_NS)
        root = ET.Element(f"{{{GRAPHML_NS}}}graphml")

        def key(kid, target, name, kind="string"):
            ET.SubElement(root, f"{{{GRAPHML_NS}}}key", {"id": kid, "for": target,
                                                         "attr.name": name, "attr.type": kind})

        node_keys = []
        if names:
            node_keys.append(("name", "name", "string"))
        node_keys += [("named_in", "named_in", "string"), ("x", "x", "double"),
                      ("y", "y", "double"), ("degree", "degree", "int")]
        node_keys += [(f"attr_{k}", k, "string") for k in attr_keys]
        for kid, name, kind in node_keys:
            key(kid, "node", name, kind)
        key("relation", "edge", "relation")
        for k in tie_keys:
            key(f"tie_{k}", "edge", k)
        graph = ET.SubElement(root, f"{{{GRAPHML_NS}}}graph",
                              {"id": f"{net['user_id']}__{net['item']}", "edgedefault": "undirected"})

        def data(parent, kid, value):
            if value is None or value == "":
                return
            d = ET.SubElement(parent, f"{{{GRAPHML_NS}}}data", {"key": kid})
            d.text = str(_cell(value))

        for a in ans["alters"]:
            node = ET.SubElement(graph, f"{{{GRAPHML_NS}}}node", {"id": a["id"]})
            if names:
                data(node, "name", a["name"])
            data(node, "named_in", "|".join(a["named_in"]))
            pos = ans["positions"].get(a["id"])
            if pos:
                data(node, "x", pos[0])
                data(node, "y", pos[1])
            data(node, "degree", stats["degree"].get(a["id"], 0))
            attrs = ans["attributes"].get(a["id"]) or {}
            for k in attr_keys:
                data(node, f"attr_{k}", attrs.get(k))
        order = {a["id"]: i for i, a in enumerate(ans["alters"])}
        for i, t in enumerate(ans["ties"]):
            rel = t[2] if len(t) > 2 else ""
            a, b = (t[0], t[1]) if order[t[0]] < order[t[1]] else (t[1], t[0])
            edge = ET.SubElement(graph, f"{{{GRAPHML_NS}}}edge",
                                 {"id": f"e{i + 1}", "source": a, "target": b})
            data(edge, "relation", rel or "tie")
            tattrs = ans["tie_attributes"].get(f"{a}|{b}" + (f"|{rel}" if rel else "")) or {}
            for k in tie_keys:
                data(edge, f"tie_{k}", tattrs.get(k) if isinstance(tattrs, dict) else None)
        tree = ET.ElementTree(root)
        ET.indent(tree)
        tree.write(path, encoding="utf-8", xml_declaration=True)
