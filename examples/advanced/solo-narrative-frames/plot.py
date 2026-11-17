#!/usr/bin/env python
"""
Plot reference-model performance on the held-out set vs. solo-mode time
step (number of simulated human labels), one line per reference model.
Dependency-free: writes an SVG (for papers/slides) and an HTML page with
the same chart plus hover tooltips and a data table.

Usage (from repo root, after evaluate.py):
  python examples/advanced/solo-narrative-frames/plot.py [--metric macro_f1|accuracy]
Outputs: run/eval/trajectory_<metric>.svg, run/eval/trajectory.html
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "run", "eval")

# Categorical slots 1-4 of the validated default palette (light, dark),
# assigned in fixed order to models in the order they first appear.
SLOTS = [("#2a78d6", "#3987e5"), ("#eb6834", "#d95926"),
         ("#1baf7a", "#199e70"), ("#eda100", "#c98500")]
MARKERS = ["circle", "square", "diamond", "triangle"]
PRETTY = {"laya": "Laya", "gemma4:e2b": "Gemma4-E2B", "qwen3.5:9b": "Qwen3.5-9B",
          "llama3.1:8b": "Llama3.1-8B (in-loop labeler)"}
METRIC_NAME = {"macro_f1": "Macro-F1", "accuracy": "Accuracy"}

W, H = 720, 420
ML, MR, MT, MB = 56, 190, 28, 48


def rows_from_preds():
    """Metrics for every (model, step) whose eval items are all scored,
    computed from the cached predictions (results.csv only holds the last
    evaluate.py call's models). Also rewrites results_all.csv."""
    sys.path.insert(0, HERE)
    from evaluate import metrics
    n_items = len(json.load(open(os.path.join(HERE, "data", "eval.json"))))
    groups = {}
    for line in open(os.path.join(OUT, "preds.jsonl")):
        r = json.loads(line)
        groups.setdefault((r["model"], r["step"]), {})[r["id"]] = r
    order = ["laya", "gemma4:e2b", "qwen3.5:9b", "llama3.1:8b"]
    rows = []
    for (m, s), byid in sorted(groups.items(), key=lambda kv: (
            order.index(kv[0][0]) if kv[0][0] in order else 99, kv[0][1])):
        if len(byid) < n_items:
            continue
        rs = list(byid.values())
        acc, mf1, f1 = metrics([r["gold"] for r in rs], [r["pred"] for r in rs])
        rows.append({"model": m, "step": s, "prompt_version": rs[0]["prompt_version"],
                     "n": len(rs), "accuracy": f"{acc:.4f}", "macro_f1": f"{mf1:.4f}",
                     "f1_episodic": f"{f1['Episodic']:.4f}", "f1_thematic": f"{f1['Thematic']:.4f}",
                     "n_unparsed": sum(r["pred"] is None for r in rs)})
    with open(os.path.join(OUT, "results_all.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return rows


def load(metric):
    rows = rows_from_preds()
    models = []
    for r in rows:
        if r["model"] not in models:
            models.append(r["model"])
    series = {m: sorted(((int(r["step"]), float(r[metric]), r) for r in rows
                         if r["model"] == m), key=lambda t: t[0]) for m in models}
    return models, series, rows


def marker(kind, x, y, cls, extra=""):
    s = 4.5
    if kind == "circle":
        return f'<circle class="{cls}" cx="{x:.1f}" cy="{y:.1f}" r="{s}" {extra}/>'
    if kind == "square":
        return f'<rect class="{cls}" x="{x-s:.1f}" y="{y-s:.1f}" width="{2*s}" height="{2*s}" rx="1" {extra}/>'
    if kind == "diamond":
        s += 1
        return f'<path class="{cls}" d="M{x:.1f},{y-s:.1f}L{x+s:.1f},{y:.1f}L{x:.1f},{y+s:.1f}L{x-s:.1f},{y:.1f}Z" {extra}/>'
    s += 1
    return f'<path class="{cls}" d="M{x:.1f},{y-s:.1f}L{x+s:.1f},{y+s*0.8:.1f}L{x-s:.1f},{y+s*0.8:.1f}Z" {extra}/>'


def svg(models, series, metric, standalone):
    steps = sorted({s for m in models for s, _, _ in series[m]})
    vals = [v for m in models for _, v, _ in series[m]]
    lo = max(0.0, (int(min(vals) * 10) / 10) - 0.0)
    hi = min(1.0, (int(max(vals) * 10) + 1) / 10)
    pw, ph = W - ML - MR, H - MT - MB
    sx = lambda s: ML + (s - steps[0]) / max(1, steps[-1] - steps[0]) * pw
    sy = lambda v: MT + (1 - (v - lo) / (hi - lo)) * ph

    style = """
  .viz-root{--surface-1:#fcfcfb;--text-primary:#0b0b0b;--text-secondary:#52514e;--grid:#e4e3df;%s}
  @media (prefers-color-scheme: dark){:root:where(:not([data-theme="light"])) .viz-root{--surface-1:#1a1a19;--text-primary:#f0efec;--text-secondary:#c3c2b7;--grid:#34332f;%s}}
  :root[data-theme="dark"] .viz-root{--surface-1:#1a1a19;--text-primary:#f0efec;--text-secondary:#c3c2b7;--grid:#34332f;%s}
  .bg{fill:var(--surface-1)} .grid{stroke:var(--grid);stroke-width:1}
  .ax{fill:var(--text-secondary);font:12px system-ui,sans-serif}
  .ttl{fill:var(--text-primary);font:600 13px system-ui,sans-serif}
  .lbl{fill:var(--text-primary);font:12px system-ui,sans-serif}
  .line{fill:none;stroke-width:2;stroke-linejoin:round}
  .mk{stroke:var(--surface-1);stroke-width:2}
""" % tuple(
        "".join(f"--s{i+1}:{SLOTS[i][k]};" for i in range(len(SLOTS))) for k in (0, 1, 1))

    out = []
    if standalone:
        out.append(f'<svg xmlns="http://www.w3.org/2000/svg" class="viz-root" viewBox="0 0 {W} {H}" '
                   f'width="{W}" height="{H}" font-family="system-ui,sans-serif">')
    else:
        out.append(f'<svg class="viz-root" viewBox="0 0 {W} {H}" role="img" '
                   f'aria-label="{METRIC_NAME[metric]} by time step per reference model">')
    out.append(f"<style>{style}</style>")
    out.append(f'<rect class="bg" width="{W}" height="{H}"/>')
    t = lo
    while t <= hi + 1e-9:
        y = sy(t)
        out.append(f'<line class="grid" x1="{ML}" x2="{ML+pw}" y1="{y:.1f}" y2="{y:.1f}"/>')
        out.append(f'<text class="ax" x="{ML-8}" y="{y+4:.1f}" text-anchor="end">{t:.1f}</text>')
        t += 0.1
    for s in steps:
        out.append(f'<text class="ax" x="{sx(s):.1f}" y="{MT+ph+18}" text-anchor="middle">{s}</text>')
    out.append(f'<text class="ax" x="{ML+pw/2:.1f}" y="{H-8}" text-anchor="middle">'
               f'Time step (human labels in solo mode)</text>')
    out.append(f'<text class="ax" transform="translate(14,{MT+ph/2:.1f}) rotate(-90)" '
               f'text-anchor="middle">{METRIC_NAME[metric]} on held-out set</text>')

    # direct labels at line ends, nudged apart so they never collide
    ends = sorted(((sy(series[m][-1][1]), i, m) for i, m in enumerate(models)))
    placed = []
    for y, i, m in ends:
        if placed and y - placed[-1] < 15:
            y = placed[-1] + 15
        placed.append(y)
        out.append(f'<text class="lbl" x="{ML+pw+12}" y="{y+4:.1f}">{html.escape(PRETTY.get(m, m))}</text>')

    for i, m in enumerate(models):
        col = f"var(--s{i+1})"
        pts = " ".join(f"{sx(s):.1f},{sy(v):.1f}" for s, v, _ in series[m])
        out.append(f'<polyline class="line" style="stroke:{col}" points="{pts}"/>')
        for s, v, r in series[m]:
            tip = (f'data-tip="{html.escape(PRETTY.get(m, m))} · step {s} · prompt v{r["prompt_version"]}'
                   f' · acc {float(r["accuracy"]):.3f} · macro-F1 {float(r["macro_f1"]):.3f}'
                   f' · unparsed {r["n_unparsed"]}"')
            out.append(marker(MARKERS[i], sx(s), sy(v), "mk", f'style="fill:{col}" {tip}'))
    out.append("</svg>")
    return "\n".join(out)


def page(models, series, rows, metric):
    legend = "".join(
        f'<span class="key"><svg width="14" height="14" viewBox="0 0 14 14">'
        f'{marker(MARKERS[i], 7, 7, "", f"style=fill:var(--s{i+1})")}</svg>'
        f'{html.escape(PRETTY.get(m, m))}</span>' for i, m in enumerate(models))
    table = "".join(
        f"<tr><td>{html.escape(PRETTY.get(r['model'], r['model']))}</td><td>{r['step']}</td>"
        f"<td>v{r['prompt_version']}</td><td>{float(r['accuracy']):.3f}</td>"
        f"<td>{float(r['macro_f1']):.3f}</td><td>{r['n_unparsed']}</td></tr>" for r in rows)
    chart = svg(models, series, metric, standalone=False)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Prompt Trajectory</title>
<style>
:root{{--bg:#fcfcfb;--fg:#0b0b0b;--muted:#52514e;--rule:#e4e3df;--tip:#0b0b0b;--tipfg:#fcfcfb}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--bg:#1a1a19;--fg:#f0efec;--muted:#c3c2b7;--rule:#34332f;--tip:#f0efec;--tipfg:#1a1a19}}}}
:root[data-theme="dark"]{{--bg:#1a1a19;--fg:#f0efec;--muted:#c3c2b7;--rule:#34332f;--tip:#f0efec;--tipfg:#1a1a19}}
body{{background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif;margin:0;padding:24px 16px}}
main{{max-width:760px;margin:0 auto}} h1{{font-size:20px;margin:0 0 4px}} p{{color:var(--muted);margin:0 0 16px}}
.legend{{display:flex;flex-wrap:wrap;gap:16px;margin:0 0 8px;color:var(--fg)}} .key{{display:inline-flex;gap:6px;align-items:center}}
svg.viz-root{{width:100%;height:auto;display:block}} .mk{{cursor:default}}
#tip{{position:fixed;pointer-events:none;background:var(--tip);color:var(--tipfg);padding:4px 8px;border-radius:4px;font-size:12px;display:none}}
table{{border-collapse:collapse;width:100%;margin-top:20px;font-variant-numeric:tabular-nums}}
td,th{{text-align:left;padding:4px 8px;border-bottom:1px solid var(--rule)}} th{{color:var(--muted);font-weight:600}}
details summary{{cursor:pointer;color:var(--muted);margin-top:16px}}
</style></head><body><main>
<h1>Reference-model performance across solo-mode prompt versions</h1>
<p>Episodic vs. Thematic framing, immigration tweets on Crime and Punishment (NAACL 2021).
Each point is the prompt in effect after <i>k</i> simulated human labels, scored on {rows[0]['n']} held-out dev+test tweets.</p>
<div class="legend">{legend}</div>
{chart}
<details><summary>Data table</summary><table><tr><th>Model</th><th>Step</th><th>Prompt</th><th>Accuracy</th><th>Macro-F1</th><th>Unparsed</th></tr>{table}</table></details>
</main><div id="tip"></div>
<script>
const tip=document.getElementById('tip');
document.querySelectorAll('[data-tip]').forEach(el=>{{
  el.addEventListener('mouseenter',()=>{{tip.textContent=el.dataset.tip;tip.style.display='block'}});
  el.addEventListener('mousemove',e=>{{tip.style.left=Math.min(e.clientX+12,innerWidth-tip.offsetWidth-8)+'px';tip.style.top=(e.clientY+12)+'px'}});
  el.addEventListener('mouseleave',()=>{{tip.style.display='none'}});
}});
</script></body></html>"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--metric", default="macro_f1", choices=list(METRIC_NAME))
    args = ap.parse_args(argv)
    models, series, rows = load(args.metric)
    with open(os.path.join(OUT, f"trajectory_{args.metric}.svg"), "w") as f:
        f.write(svg(models, series, args.metric, standalone=True))
    with open(os.path.join(OUT, "trajectory.html"), "w") as f:
        f.write(page(models, series, rows, args.metric))
    print(f"wrote {OUT}/trajectory_{args.metric}.svg and trajectory.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
