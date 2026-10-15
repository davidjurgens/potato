"""Certificate as Markdown, HTML, and a Hugging Face dataset card."""

from __future__ import annotations

import html
from typing import Any, Dict, List


def _pct(v):
    return "n/a" if v is None else f"{v:.1%}"


def _estimate_table(cid: str, c: Dict[str, Any]) -> List[str]:
    """A PPI contract's intervals, which its statement promises."""
    est = c.get("estimates") or {}
    rows = []
    for group, by_label in est.items():
        if not isinstance(by_label, dict) or "note" in by_label:
            continue
        for label, e in by_label.items():
            if not isinstance(e, dict) or "lo" not in e:
                continue
            rows.append(f"| {group} | {label} | {e['estimate']:.3f} | "
                        f"[{e['lo']:.3f}, {e['hi']:.3f}] | {e.get('n', '')} |")
    if not rows:
        return []
    return ([f"Estimates ({cid}):", "", "| Group | Label | Estimate | Interval | Human labels |",
             "|---|---|---|---|---|"] + rows + [""])


def render_markdown(cert: Dict[str, Any]) -> str:
    out: List[str] = [f"# Labeling certificate: {cert.get('study') or 'study'}", ""]
    for name, sec in cert["schemes"].items():
        out += [f"## {name} ({sec['annotation_type']})", ""]
        out.append("Cascade: " + " → ".join(
            f"{t['source']} ({t['model'] or t['kind']}, version {t['version'][:10]})"
            for t in sec["cascade"]))
        out.append("")
        out.append("| Contract | Kind | Status | Statement |")
        out.append("|---|---|---|---|")
        for cid, c in sec["contracts"].items():
            stmt = (c.get("statement") or "").replace("|", "\\|")
            status = c["status"]
            if c.get("audits_breached") and status == "met":
                status = "met, audits breached"
            out.append(f"| {cid} | {c['kind']} | {status} | {stmt} |")
        out.append("")
        for cid, c in sec["contracts"].items():
            for note in c.get("notes") or []:
                out.append(f"- {cid}: {note}")
        if any(c.get("notes") for c in sec["contracts"].values()):
            out.append("")
        unmet = [cid for cid, c in sec["contracts"].items()
                 if c.get("kind") == "selective_risk" and c.get("status") != "met"]
        if unmet:
            out.append(f"No machine label is accepted on this scheme until every "
                       f"selective_risk contract is met. Not met: {', '.join(unmet)}.")
            stuck = [cid for cid in unmet if sec["contracts"][cid].get("status") == "infeasible"]
            if stuck:
                out.append(f"{', '.join(stuck)} cannot be met with these sources; the "
                           "remaining items went to people.")
            out.append("")
        delivered = ", ".join(f"{k} {v}" for k, v in sec["delivered"].items()) or "none yet"
        out.append(f"Labels delivered: {delivered}.")
        by_version = sec.get("accepted_by_source_version") or {}
        if sec["cascade"]:
            out.append("Machine labels accepted, by source: " + ", ".join(
                f"{t['source']} {by_version.get(t['version'], 0)}"
                for t in sec["cascade"]) + ".")
        # Cancelled requests were never put to anyone; count them apart.
        reqs = ", ".join(
            f"{p} {sum(n for st, n in v.items() if st != 'cancelled')} "
            f"({v.get('done', 0)} answered"
            + (f"; {v['cancelled']} cancelled" if v.get("cancelled") else "") + ")"
            for p, v in sorted(sec["human_requests"].items()) if p != "organic") or "none"
        line = f"Human requests: {reqs}."
        organic = (sec["human_requests"].get("organic") or {}).get("done", 0)
        if organic:
            line += f" Organic labels (not requested): {organic}."
        if sec.get("multi_rater_items"):
            line += (f" On the {sec['multi_rater_items']} items labeled by more than one "
                     f"person, their labels were combined by "
                     f"{sec['truth'].replace('_', '-')}.")
        out.append(line)
        if sec.get("drift"):
            for cid, d in sec["drift"].items():
                line = f"Drift ({cid}): " + (d.get("statement") or "no audits answered "
                                                          "since the last certification.")
                if d.get("earlier_breach"):
                    line += " " + d["earlier_breach"]
                out.append(line)
        out.append("")
        for cid, c in sec["contracts"].items():
            out += _estimate_table(cid, c)
    mc = cert["model_calls"]
    cost = "unpriced" if mc.get("cost_usd") is None else f"${mc['cost_usd']:.4f}"
    hl = (cert.get("budgets") or {}).get("human_labels")
    if hl:
        answered = sum(v.get("done", 0) for sec in cert["schemes"].values()
                       for p, v in sec["human_requests"].items() if p != "organic")
        out += [f"Human labels: {int(hl['spent'])} of {int(hl['limit'])} requested "
                f"({answered} answered).", ""]
    out += ["## Provenance", "",
            f"- Model calls: {mc['n']} ({cost})",
            f"- Dataset hash: `{cert['dataset_hash']}`",
            f"- Call log digest: `{cert['call_log_digest']}`",
            f"- Certificate content hash: `{cert['content_sha256']}`", ""]
    return "\n".join(out)


def _inline(text: str) -> str:
    """Escape, then turn `code` spans into <code>."""
    parts = html.escape(text).split("`")
    return "".join(f"<code>{p}</code>" if i % 2 else p for i, p in enumerate(parts))


def render_html(cert: Dict[str, Any]) -> str:
    md = render_markdown(cert)
    body = []
    in_table, header, in_list = False, False, False
    heads: List[str] = []
    for line in md.splitlines():
        e = _inline(line)
        if in_list and not line.startswith("- "):
            body.append("</ul>")
            in_list = False
        if in_table and not line.startswith("|"):
            body.append("</table>")
            in_table = False
        if line.startswith("| ") and not in_table:
            body.append("<table>")
            in_table, header = True, True
        if line.startswith("# "):
            body.append(f"<h1>{e[2:]}</h1>")
        elif line.startswith("## "):
            body.append(f"<h2>{e[3:]}</h2>")
        elif line.startswith("|---"):
            continue
        elif line.startswith("| "):
            cells = [c.strip().replace("\\|", "|") for c in line.strip("|").split(" | ")]
            if header:
                heads = cells
                body.append("<tr class='head'>" + "".join(
                    f"<th>{_inline(c)}</th>" for c in cells) + "</tr>")
                header = False
            else:
                # data-label: on a phone each row is stacked into a card and
                # every cell names its column.
                body.append("<tr>" + "".join(
                    f"<td data-label='{html.escape(heads[i] if i < len(heads) else '', quote=True)}'>"
                    f"{_inline(c)}</td>" for i, c in enumerate(cells)) + "</tr>")
        elif line.startswith("- "):
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{_inline(line[2:])}</li>")
        elif line:
            body.append(f"<p>{e}</p>")
    if in_list:
        body.append("</ul>")
    if in_table:
        body.append("</table>")
    content = "\n".join(body)
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<title>Labeling certificate</title><style>:root{--fg:#1a1a1a;--bg:#fff;"
            "--rule:#ccc}@media (prefers-color-scheme:dark){:root{--fg:#e6e6e6;"
            "--bg:#161616;--rule:#444}}body{font-family:system-ui,sans-serif;"
            "max-width:60rem;margin:2rem auto;padding:0 1rem;color:var(--fg);"
            "background:var(--bg);overflow-wrap:break-word}table{border-collapse:collapse;"
            "width:100%;display:block;overflow-x:auto}td,th{border:1px solid var(--rule);"
            "padding:.4rem;text-align:left;vertical-align:top}td:first-child{overflow-wrap:anywhere}"
            "code{word-break:break-all}"
            "@media (max-width:600px){table,tbody,tr,td{display:block}tr.head{display:none}"
            "tr{border:1px solid var(--rule);margin:.5rem 0;padding:.25rem 0}"
            "td{border:none;padding:.15rem .5rem}td::before{content:attr(data-label) ': ';"
            "font-weight:600}}"
            "</style></head><body>"
            + content + "</body></html>")


def dataset_card(cert: Dict[str, Any]) -> str:
    """A README.md for a Hugging Face dataset: YAML front matter + the certificate."""
    lines = ["---", "annotations_creators:", "- machine-generated", "- expert-generated",
             "tags:", "- potato-labeling-engine", "---", ""]
    return "\n".join(lines) + render_markdown(cert)
