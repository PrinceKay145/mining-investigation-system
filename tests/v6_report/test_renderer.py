"""Tests for v6 markdown + HTML rendering — pure functions."""

from schema.v6_report import V6Report, V6ReportContent
from v6_report.renderer import render_html, render_markdown


def _sample_report() -> V6Report:
    return V6Report(
        content=V6ReportContent(
            incident_summary="**Kostenko** [U-A1] mine event.",
            classification_and_precedents="Primary: methane_explosion.",
            accepted_conclusions="### Methane source\nK2 seam [K-A2, D-A1].",
            rejected_hypotheses="K-A4 was defeated by U-A3.",
            unresolved_questions="Ignition source remains contested.",
            regulatory_violations="REG-03 not met.",
        ),
        case_name="Kostenko Mine Explosion",
        case_date="2023-10-28",
        run_id="kostenko_v6_test",
        graph_path="argumentation_graph.png",
        counts={"combined_arguments": 41, "attacks_detected": 33},
    )


def test_render_markdown_includes_all_sections():
    md = render_markdown(_sample_report())
    for header in (
        "## 1. Incident summary",
        "## 2. Classification and precedents",
        "## 3. Accepted conclusions",
        "## 4. Rejected hypotheses",
        "## 5. Unresolved questions",
        "## 6. Argumentation graph",
        "## 7. Regulatory violations",
    ):
        assert header in md


def test_render_markdown_includes_run_id_and_case_name():
    md = render_markdown(_sample_report())
    assert "Kostenko Mine Explosion" in md
    assert "kostenko_v6_test" in md
    assert "2023-10-28" in md


def test_render_markdown_embeds_graph():
    md = render_markdown(_sample_report())
    assert "![Argumentation framework](argumentation_graph.png)" in md


def test_render_markdown_includes_citations_verbatim():
    """Argument-ID citations like [U-A1] must pass through unchanged."""
    md = render_markdown(_sample_report())
    assert "[U-A1]" in md
    assert "[K-A2, D-A1]" in md


def test_render_markdown_includes_counts_table():
    md = render_markdown(_sample_report())
    assert "| Metric | Value |" in md
    assert "| combined_arguments | 41 |" in md
    assert "| attacks_detected | 33 |" in md


def test_render_html_is_valid_html_structure():
    html = render_html(_sample_report())
    assert html.startswith("<!DOCTYPE html>")
    assert "<title>Investigation Report" in html
    assert "</html>" in html.strip()


def test_render_html_converts_headers():
    html = render_html(_sample_report())
    assert "<h1>" in html and "<h2>" in html


def test_render_html_converts_bold_and_code():
    html = render_html(_sample_report())
    # Sample has **Kostenko** in section 1
    assert "<strong>Kostenko</strong>" in html


def test_render_html_embeds_graph_image():
    html = render_html(_sample_report())
    assert '<img src="argumentation_graph.png"' in html
