"""Build data/notes.pdf (10 pages) from data/notes_source.txt.

The notes are original sample notes written for testing this project.
Each '=== Title' section becomes one PDF page.
"""
from pathlib import Path

from fpdf import FPDF

DATA = Path(__file__).resolve().parent.parent / "data"


def main() -> None:
    sections = DATA.joinpath("notes_source.txt").read_text(encoding="utf-8").split("=== ")[1:]
    pdf = FPDF(format="letter")
    pdf.set_auto_page_break(auto=False)
    pdf.set_margins(20, 18, 20)
    for i, section in enumerate(sections, start=1):
        title, body = section.split("\n", 1)
        pdf.add_page()
        pdf.set_font("Helvetica", "I", 8)
        pdf.cell(0, 5, "NURS 2100 Pathophysiology - sample notes for Between Heats testing", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "B", 14)
        pdf.multi_cell(0, 8, title.strip(), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        pdf.set_font("Helvetica", "", 11)
        for para in body.strip().split("\n\n"):
            pdf.multi_cell(0, 5.6, para.strip(), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2.5)
        if pdf.get_y() > 260:
            raise SystemExit(f"Section {i} overflows its page: {title}")
        pdf.set_y(-15)
        pdf.set_font("Helvetica", "", 8)
        pdf.cell(0, 5, f"Page {i}", align="C")
    out = DATA / "notes.pdf"
    pdf.output(str(out))
    print(f"Wrote {out} ({len(sections)} pages)")


if __name__ == "__main__":
    main()
