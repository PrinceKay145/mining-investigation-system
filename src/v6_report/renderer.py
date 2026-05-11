"""
Renderers — turn a V6Report into a final markdown or HTML document.

Markdown rendering:
  - Title + metadata header
  - 7 numbered sections (Section 6 embeds the AF graph PNG)
  - Counts table
  - Footer with run ID for reproducibility

HTML rendering:
  - Minimal styling so the report is presentable without external CSS
  - Markdown content rendered via a small in-house markdown→HTML
    helper (we keep it minimal to avoid pulling a markdown library)
"""

from __future__ import annotations

from pathlib import Path

from schema.v6_report import V6Report


def render_markdown(report: V6Report) -> str:
    """Compose the V6Report content + section headers + graph embed into one markdown string."""
    c = report.content
    counts = report.counts

    lines = [
        f"# Investigation Report — {report.case_name}",
        "",
        f"**Date of incident:** {report.case_date}  ",
        f"**Run ID:** `{report.run_id}`",
        "",
        "---",
        "",
        "## 1. Incident summary",
        "",
        c.incident_summary.strip(),
        "",
        "## 2. Classification and precedents",
        "",
        c.classification_and_precedents.strip(),
        "",
        "## 3. Accepted conclusions",
        "",
        c.accepted_conclusions.strip(),
        "",
        "## 4. Rejected hypotheses",
        "",
        c.rejected_hypotheses.strip(),
        "",
        "## 5. Unresolved questions",
        "",
        c.unresolved_questions.strip(),
        "",
        "## 6. Argumentation graph",
        "",
        f"![Argumentation framework]({report.graph_path})",
        "",
        "Node colors: **green** = accepted (grounded extension), "
        "**orange** = ambiguous (in some preferred extension but not all), "
        "**red** = rejected (in no preferred extension). "
        "Edges: **solid red** = rebutting attack, **dashed** = undercutting attack.",
        "",
        "## 7. Regulatory violations",
        "",
        c.regulatory_violations.strip(),
        "",
        "---",
        "",
        "## Summary counts",
        "",
        "| Metric | Value |",
        "|-|-|",
    ]
    for k, v in counts.items():
        lines.append(f"| {k} | {v} |")
    lines.append("")
    lines.append(f"_Reproducible from run artifacts in `runs/{report.run_id}/`._")
    return "\n".join(lines)


def _markdown_to_minimal_html(md: str) -> str:
    """
    Minimal markdown → HTML conversion. Handles the subset our report uses:
    headers (#..####), paragraphs, bold (**...**), italic (*...*), inline code
    (`...`), unordered lists, and images. Not a general-purpose converter.
    """
    import re

    lines = md.split("\n")
    html_parts: list[str] = []
    in_list = False
    in_table = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            html_parts.append("</ul>")
            in_list = False

    def close_table() -> None:
        nonlocal in_table
        if in_table:
            html_parts.append("</tbody></table>")
            in_table = False

    def inline(text: str) -> str:
        # Images: ![alt](src)
        text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)",
                      r'<img src="\2" alt="\1" style="max-width:100%;">', text)
        # Bold
        text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
        # Italic (single *)
        text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
        # Inline code
        text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
        return text

    for raw in lines:
        line = raw.rstrip()

        if not line.strip():
            close_list()
            close_table()
            html_parts.append("")
            continue

        if line.startswith("# "):
            close_list(); close_table()
            html_parts.append(f"<h1>{inline(line[2:])}</h1>")
        elif line.startswith("## "):
            close_list(); close_table()
            html_parts.append(f"<h2>{inline(line[3:])}</h2>")
        elif line.startswith("### "):
            close_list(); close_table()
            html_parts.append(f"<h3>{inline(line[4:])}</h3>")
        elif line.startswith("#### "):
            close_list(); close_table()
            html_parts.append(f"<h4>{inline(line[5:])}</h4>")
        elif line.strip() == "---":
            close_list(); close_table()
            html_parts.append("<hr>")
        elif line.startswith("- "):
            close_table()
            if not in_list:
                html_parts.append("<ul>")
                in_list = True
            html_parts.append(f"<li>{inline(line[2:])}</li>")
        elif line.startswith("|"):
            # Skip the alignment row (|---|---|)
            if re.match(r"^\|[-:|\s]+\|$", line):
                continue
            cells = [inline(c.strip()) for c in line.strip("|").split("|")]
            if not in_table:
                # First row is header
                html_parts.append('<table border="1" cellpadding="6" cellspacing="0">')
                html_parts.append("<thead><tr>")
                for c in cells:
                    html_parts.append(f"<th>{c}</th>")
                html_parts.append("</tr></thead><tbody>")
                in_table = True
            else:
                html_parts.append("<tr>")
                for c in cells:
                    html_parts.append(f"<td>{c}</td>")
                html_parts.append("</tr>")
        else:
            close_list(); close_table()
            html_parts.append(f"<p>{inline(line)}</p>")

    close_list()
    close_table()
    return "\n".join(html_parts)


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Investigation Report — {case_name}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        max-width: 900px; margin: 2em auto; padding: 0 1em; line-height: 1.55;
        color: #222; }}
h1 {{ border-bottom: 2px solid #333; padding-bottom: 0.3em; }}
h2 {{ border-bottom: 1px solid #999; padding-bottom: 0.2em; margin-top: 2em; }}
h3 {{ color: #444; }}
code {{ background: #f4f4f4; padding: 1px 4px; border-radius: 3px;
        font-family: "SF Mono", Menlo, Consolas, monospace; font-size: 0.92em; }}
table {{ border-collapse: collapse; margin: 1em 0; }}
th {{ background: #f4f4f4; text-align: left; }}
hr {{ border: none; border-top: 1px solid #ddd; margin: 2em 0; }}
img {{ display: block; margin: 1em auto; }}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def render_html(report: V6Report) -> str:
    md = render_markdown(report)
    body = _markdown_to_minimal_html(md)
    return _HTML_TEMPLATE.format(case_name=report.case_name, body=body)
