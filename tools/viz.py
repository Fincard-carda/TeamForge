"""Zenginlestirilmis output tool'lari — table, chart, kpi, mermaid.

Davranis:
- Her tool agent'in answer text'inde gomulu **markdown blok** produces.
- Dashboard renderMarkdown this bloklari Chart.js / Mermaid / HTML table'a convertir.
- Standalone HTML versiyonu da artifacts/<role>/charts/<id>.html altina is written.

Usage examples:
- viz.table -> { headers: [...], rows: [[...]], title: "Q3 Prforg" }
- viz.bar_chart -> { labels: [...], values: [...], y_label, title }
- viz.line_chart -> { labels: [...], datasets: [{name, values}], title }
- viz.kpi_card -> { items: [{label, value, change_pct?, trend?}] }
- viz.mermaid -> { source: "graph TD\\nA-->B", title }
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from claude_agent_sdk import tool

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
ARTIFACTS_DIR.mkdir(exist_ok=True)


def _save_html_artifact(role: str, name: str, html: str) -> str:
    """Standalone HTML artifact'ini diske write, relative path don."""
    role = (role or "shared").strip() or "shared"
    out_dir = ARTIFACTS_DIR / role / "charts"
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / name
    p.write_text(html, encoding="utf-8")
    return str(p.relative_to(PROJECT_ROOT))


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@tool(
    "table",
    ("Yapilandirilmis tablo. headers: [str, ...], rows: [[cell, ...], ...]. "
     "Markdown tablo + standalone HTML artifact produces. role: yazan agent role (CEO, CFO vb.)."),
    {"role": str, "title": str, "headers": list, "rows": list, "footer_note": str},
)
async def table(args: dict) -> dict:
    role = (args.get("role") or "shared").strip()
    title = (args.get("title") or "").strip() or "Tablo"
    headers = args.get("headers") or []
    rows = args.get("rows") or []
    footer = (args.get("footer_note") or "").strip()
    if not headers or not rows:
        return {"content": [{"type": "text",
                              "text": "headers and rows mandatory (her ikisi de empty olmamali)"}],
                "is_error": True}

    # Markdown tablo
    md = [f"### {title}", ""]
    md.append("| " + " | ".join(str(h) for h in headers) + " |")
    md.append("|" + "|".join("---" for _ in headers) + "|")
    for row in rows:
        cells = [str(c).replace("|", "\\|").replace("\n", " ") for c in row]
        # Missing hucreler empty sayilsin
        while len(cells) < len(headers): cells.append("")
        md.append("| " + " | ".join(cells[:len(headers)]) + " |")
    if footer:
        md.append("")
        md.append(f"_{footer}_")

    # Standalone HTML
    tid = _gen_id("table")
    html_rows = "".join(
        "<tr>" + "".join(f"<td>{str(c)}</td>" for c in row) + "</tr>"
        for row in rows
    )
    html = f"""<!doctype html><meta charset="utf-8">
<title>{title}</title>
<style>body{{font-family:system-ui;max-width:900px;margin:24px auto;padding:0 12px;}}
table{{border-collapse:collapse;width:100%;}}
th,td{{padding:8px 12px;border:1px solid #ccc;text-align:left;}}
th{{background:#eef;}}
tr:nth-child(even){{background:#f8f8f8;}}</style>
<h1>{title}</h1>
<table>
<thead><tr>{''.join(f'<th>{h}</th>' for h in headers)}</tr></thead>
<tbody>{html_rows}</tbody>
</table>
<p><em>{footer}</em></p>"""
    art_path = _save_html_artifact(role, f"{tid}.html", html)

    text = "\n".join(md) + f"\n\n_(standalone: `{art_path}`)_"
    return {"content": [{"type": "text", "text": text}]}


@tool(
    "bar_chart",
    ("Bar chart. labels: [str, ...] (X ekseni), values: [num, ...] (Y values), "
     "title, y_label optional. Dashboard'da Chart.js render eder. role mandatory."),
    {"role": str, "title": str, "labels": list, "values": list,
     "y_label": str, "x_label": str},
)
async def bar_chart(args: dict) -> dict:
    role = (args.get("role") or "shared").strip()
    title = (args.get("title") or "").strip() or "Bar Chart"
    labels = args.get("labels") or []
    values = args.get("values") or []
    y_label = (args.get("y_label") or "").strip()
    x_label = (args.get("x_label") or "").strip()
    if not labels or not values or len(labels) != len(values):
        return {"content": [{"type": "text",
                              "text": "labels and values esit lengthta + empty olmamali"}],
                "is_error": True}

    cid = _gen_id("bar")
    config = {
        "type": "bar",
        "labels": labels,
        "values": values,
        "title": title,
        "y_label": y_label,
        "x_label": x_label,
    }
    md = (f"### {title}\n\n"
          f"```chart-bar\n{json.dumps(config, ensure_ascii=False, indent=2)}\n```")

    # Standalone HTML
    html = _standalone_chart_html(title, "bar", labels, [{"label": y_label or "Value",
                                                            "data": values}])
    art_path = _save_html_artifact(role, f"{cid}.html", html)
    return {"content": [{"type": "text",
                          "text": md + f"\n\n_(standalone: `{art_path}`)_"}]}


@tool(
    "line_chart",
    ("Line chart (trend). datasets: [{name: str, values: [num, ...]}, ...] — "
     "her dataset bir line. labels: X ekseni etikets. role mandatory."),
    {"role": str, "title": str, "labels": list, "datasets": list,
     "y_label": str, "x_label": str},
)
async def line_chart(args: dict) -> dict:
    role = (args.get("role") or "shared").strip()
    title = (args.get("title") or "").strip() or "Line Chart"
    labels = args.get("labels") or []
    datasets = args.get("datasets") or []
    y_label = (args.get("y_label") or "").strip()
    x_label = (args.get("x_label") or "").strip()
    if not labels or not datasets:
        return {"content": [{"type": "text",
                              "text": "labels and datasets mandatory"}], "is_error": True}

    cid = _gen_id("line")
    config = {
        "type": "line", "labels": labels, "datasets": datasets,
        "title": title, "y_label": y_label, "x_label": x_label,
    }
    md = (f"### {title}\n\n"
          f"```chart-line\n{json.dumps(config, ensure_ascii=False, indent=2)}\n```")

    html = _standalone_chart_html(
        title, "line", labels,
        [{"label": d.get("name", f"S{i+1}"), "data": d.get("values", [])}
         for i, d in enumerate(datasets)]
    )
    art_path = _save_html_artifact(role, f"{cid}.html", html)
    return {"content": [{"type": "text",
                          "text": md + f"\n\n_(standalone: `{art_path}`)_"}]}


@tool(
    "kpi_card",
    ("KPI grid karti. items: [{label, value, change_pct?, trend?}] — her item bir kart. "
     "trend: 'up' | 'down' | 'flat'. role mandatory."),
    {"role": str, "title": str, "items": list},
)
async def kpi_card(args: dict) -> dict:
    role = (args.get("role") or "shared").strip()
    title = (args.get("title") or "").strip() or "KPI"
    items = args.get("items") or []
    if not items:
        return {"content": [{"type": "text", "text": "items mandatory"}], "is_error": True}

    cid = _gen_id("kpi")
    config = {"type": "kpi", "title": title, "items": items}
    md = (f"### {title}\n\n"
          f"```kpi-grid\n{json.dumps(config, ensure_ascii=False, indent=2)}\n```")

    cards_html = ""
    for it in items:
        trend = (it.get("trend") or "flat").lower()
        color = {"up": "#3fb950", "down": "#ff7b72", "flat": "#8b949e"}.get(trend, "#8b949e")
        change = it.get("change_pct")
        change_str = f"{change:+.1f}%" if isinstance(change, (int, float)) else (str(change or "") if change is not None else "")
        cards_html += (
            f'<div style="background:#f8f8fa;border-left:4px solid {color};'
            f'padding:14px 18px;border-radius:6px;min-width:180px;">'
            f'<div style="color:#586069;font-size:11px;text-transform:uppercase;'
            f'letter-spacing:.5px">{it.get("label","")}</div>'
            f'<div style="font-size:24px;font-weight:600;color:#24292f;margin:4px 0">'
            f'{it.get("value","")}</div>'
            f'<div style="color:{color};font-size:12px">{change_str}</div></div>'
        )
    html = (f"<!doctype html><meta charset=utf-8><title>{title}</title>"
            f"<style>body{{font-family:system-ui;background:#fff;padding:24px;}}"
            f"h1{{margin:0 0 18px}}.grid{{display:flex;flex-wrap:wrap;gap:12px;}}</style>"
            f"<h1>{title}</h1><div class=grid>{cards_html}</div>")
    art_path = _save_html_artifact(role, f"{cid}.html", html)
    return {"content": [{"type": "text",
                          "text": md + f"\n\n_(standalone: `{art_path}`)_"}]}


@tool(
    "mermaid",
    ("Mermaid diagrami (flowchart, sequence, gantt, ER, vs.). source: tam mermaid syntax. "
     "Example: 'graph TD\\nA-->B\\nB-->C'. role mandatory."),
    {"role": str, "title": str, "source": str},
)
async def mermaid(args: dict) -> dict:
    role = (args.get("role") or "shared").strip()
    title = (args.get("title") or "").strip() or "Diagram"
    source = (args.get("source") or "").strip()
    if not source:
        return {"content": [{"type": "text", "text": "source mandatory"}], "is_error": True}

    cid = _gen_id("mermaid")
    md = f"### {title}\n\n```mermaid\n{source}\n```"

    html = (f"<!doctype html><meta charset=utf-8><title>{title}</title>"
            f"<script src=https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js></script>"
            f"<script>mermaid.initialize({{startOnLoad:true,theme:'default'}});</script>"
            f"<style>body{{font-family:system-ui;padding:24px;background:#fff}}</style>"
            f"<h1>{title}</h1><pre class=mermaid>{source}</pre>")
    art_path = _save_html_artifact(role, f"{cid}.html", html)
    return {"content": [{"type": "text",
                          "text": md + f"\n\n_(standalone: `{art_path}`)_"}]}


def _standalone_chart_html(title: str, ctype: str, labels: list,
                            datasets: list) -> str:
    """Chart.js standalone HTML produces."""
    palette = ["#1f6feb", "#3fb950", "#ff7b72", "#d2a8ff", "#56d364", "#f78166"]
    chart_datasets = []
    for i, d in enumerate(datasets):
        c = palette[i % len(palette)]
        chart_datasets.append({
            "label": d.get("label", f"S{i+1}"),
            "data": d.get("data", []),
            "backgroundColor": c if ctype == "bar" else c + "33",
            "borderColor": c,
            "borderWidth": 2,
        })
    config = {
        "type": ctype,
        "data": {"labels": labels, "datasets": chart_datasets},
        "options": {
            "responsive": True,
            "plugins": {"title": {"display": True, "text": title}},
        },
    }
    return f"""<!doctype html><meta charset=utf-8><title>{title}</title>
<script src=https://cdn.jsdelivr.net/npm/chart.js></script>
<style>body{{font-family:system-ui;padding:24px;background:#fff;max-width:900px;margin:auto}}</style>
<h1>{title}</h1>
<canvas id=c></canvas>
<script>new Chart(document.getElementById('c'), {json.dumps(config)});</script>"""


VIZ_TOOLS = [table, bar_chart, line_chart, kpi_card, mermaid]
