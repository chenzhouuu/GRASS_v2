"""Deterministic PDF renderer for the Report Agent.

Renders a ReportContent (LLM-authored narrative) plus state artifacts
(optimization solution, cypher query) into a PDF with fpdf2. The layout
code is fixed and tested here, so report generation cannot fail on
LLM-generated syntax or fpdf layout mistakes — the failure class that
previously burned three full script-regeneration retries per report.

Runs in-process: this is trusted project code, not agent-generated code,
so it does not go through the execution sandbox.
"""

import logging
import os
from datetime import date

from fpdf import FPDF

from ..core.schemas import ReportContent

logger = logging.getLogger(__name__)

# fpdf2 core fonts are latin-1 only; LLM prose routinely contains these.
_LATIN1_REPLACEMENTS = {
    "—": "-",
    "–": "-",
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "•": "-",
    "…": "...",
    " ": " ",
}

_ROUTE_TABLE_MAX_ROWS = 15


def _latin1(text: str) -> str:
    for src, dst in _LATIN1_REPLACEMENTS.items():
        text = text.replace(src, dst)
    return text.encode("latin-1", "replace").decode("latin-1")


class _ReportPDF(FPDF):
    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")
        self.set_text_color(0)


def _heading(pdf: FPDF, text: str, size: int = 14) -> None:
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "B", size)
    pdf.multi_cell(0, 8, _latin1(text))
    pdf.ln(2)


def _body(pdf: FPDF, text: str) -> None:
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 6, _latin1(text))
    pdf.ln(2)


def _bullet(pdf: FPDF, text: str) -> None:
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 6, _latin1(f"-  {text}"))


def _fmt_num(value) -> str:
    if isinstance(value, (int, float)):
        return f"{value:,.2f}" if isinstance(value, float) else f"{value:,}"
    return str(value)


def _routes_table(pdf: FPDF, routes: list[dict]) -> None:
    widths = (55, 55, 33, 33)
    headers = ("From", "To", "Volume", "Cost")
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "B", 9)
    for w, h in zip(widths, headers):
        pdf.cell(w, 7, h, border=1)
    pdf.ln()
    pdf.set_font("Helvetica", "", 9)
    for r in routes[:_ROUTE_TABLE_MAX_ROWS]:
        pdf.set_x(pdf.l_margin)
        cells = (
            _latin1(str(r.get("from", "")))[:30],
            _latin1(str(r.get("to", "")))[:30],
            _fmt_num(r.get("volume", "")),
            _fmt_num(r.get("cost", "")),
        )
        for w, c in zip(widths, cells):
            pdf.cell(w, 6, c, border=1)
        pdf.ln()
    if len(routes) > _ROUTE_TABLE_MAX_ROWS:
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_x(pdf.l_margin)
        pdf.cell(0, 6, f"... {len(routes) - _ROUTE_TABLE_MAX_ROWS} more route(s)")
        pdf.ln()
    pdf.ln(2)


def _optimization_block(pdf: FPDF, solution: dict) -> None:
    _heading(pdf, "Optimization Results")
    headline = [
        f"{key}: {solution[key]}"
        for key in ("status", "objective", "solver")
        if key in solution
    ]
    if headline:
        _body(pdf, " | ".join(str(h) for h in headline))

    kpis = solution.get("kpis")
    if isinstance(kpis, dict) and kpis:
        for name, value in kpis.items():
            _bullet(pdf, f"{name}: {_fmt_num(value)}")
        pdf.ln(2)

    routes = solution.get("routes") or []
    if isinstance(routes, list) and routes:
        _routes_table(pdf, routes)

    binding = solution.get("binding") or []
    if isinstance(binding, list) and binding:
        _body(pdf, "Binding constraints: " + ", ".join(str(b) for b in binding[:10]))


def render_report_pdf(
    content: ReportContent, state: dict, output_path: str
) -> str:
    """Render the report to ``output_path`` (absolute); returns that path."""
    pdf = _ReportPDF(format="letter")
    pdf.set_margins(20, 20, 20)
    pdf.set_auto_page_break(True, margin=20)

    # Title page
    pdf.add_page()
    pdf.ln(60)
    pdf.set_font("Helvetica", "B", 22)
    pdf.multi_cell(0, 12, _latin1(content.title), align="C")
    pdf.ln(8)
    pdf.set_font("Helvetica", "", 12)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, 8, date.today().isoformat(), align="C")
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, 8, "GRASS Supply Chain Analytics", align="C")

    # Narrative
    pdf.add_page()
    _heading(pdf, "Executive Summary")
    _body(pdf, content.executive_summary)

    for section in content.sections:
        _heading(pdf, section.heading)
        if section.body:
            _body(pdf, section.body)
        for b in section.bullets:
            _bullet(pdf, b)
        if section.bullets:
            pdf.ln(2)

    # Deterministic data blocks from state
    solution = state.get("optimization_solution")
    if isinstance(solution, dict) and solution:
        _optimization_block(pdf, solution)

    if content.recommendations:
        _heading(pdf, "Recommendations")
        for i, rec in enumerate(content.recommendations, 1):
            pdf.set_x(pdf.l_margin)
            pdf.set_font("Helvetica", "", 10)
            pdf.multi_cell(0, 6, _latin1(f"{i}. {rec}"))
        pdf.ln(2)

    if content.limitations:
        _heading(pdf, "Limitations")
        _body(pdf, content.limitations)

    # Appendix
    query = state.get("cypher_query")
    if query:
        _heading(pdf, "Appendix: Data Retrieval", size=12)
        rows = state.get("cypher_results") or []
        if rows:
            _body(pdf, f"Rows retrieved: {len(rows)}")
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Courier", "", 8)
        pdf.multi_cell(0, 4.5, _latin1(str(query)))

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    pdf.output(output_path)
    logger.info("Report PDF rendered: %s", output_path)
    return output_path
