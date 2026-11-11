"""Render seed/content/handbook.md to handbook.pdf with fpdf2.

Usage: uv run python backend/scripts/make_seed_pdf.py
Headings become bold lines. Each H2 starts a new page, so the PDF parser
(one section per page) yields one section per handbook part.
"""

import re
from datetime import UTC, datetime
from pathlib import Path

from fpdf import FPDF

CONTENT = Path(__file__).resolve().parents[1] / "seed" / "content"
_SIZES = {1: 20, 2: 15, 3: 12}


def _latin1(text: str) -> str:
    return text.encode("latin-1", "replace").decode("latin-1")


def build(markdown: str) -> FPDF:
    pdf = FPDF(format="Letter")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_title("Larkspur Labs Employee Handbook")
    pdf.set_creation_date(datetime(2026, 9, 15, tzinfo=UTC))
    pdf.add_page()
    for raw in markdown.splitlines():
        line = _latin1(raw.rstrip())
        m = re.match(r"^(#{1,3}) (.*)$", line)
        if m:
            level = len(m.group(1))
            if level == 2 and pdf.get_y() > 30:
                pdf.add_page()
            pdf.set_font("Helvetica", "B", _SIZES[level])
            pdf.multi_cell(
                0, 9 if level == 1 else 8, m.group(2), new_x="LMARGIN", new_y="NEXT"
            )
            pdf.ln(2)
        elif line:
            pdf.set_font("Helvetica", "", 11)
            pdf.multi_cell(0, 5.5, line, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
    return pdf


def main() -> None:
    pdf = build((CONTENT / "handbook.md").read_text(encoding="utf-8"))
    out = CONTENT / "handbook.pdf"
    pdf.output(str(out))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
