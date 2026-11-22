"""Read a notes PDF into the pages table, one row per page.

Usage: python ingest.py data/notes.pdf
"""
import sys
from pathlib import Path

from pypdf import PdfReader

import db

MIN_TEXT_CHARS = 50  # below this a page is probably handwritten or scanned


def ingest(pdf_path: str | Path, conn) -> tuple[int, list[int]]:
    """Store each page's text. Returns (pages stored, page numbers with too little text)."""
    pdf_path = Path(pdf_path)
    stored, low_text = 0, []
    for number, page in enumerate(PdfReader(pdf_path).pages, start=1):
        text = (page.extract_text() or "").strip()
        if len(text) < MIN_TEXT_CHARS:
            low_text.append(number)  # stretch goal: send these pages to the vision model
            continue
        conn.execute(
            "INSERT OR REPLACE INTO pages (file, page, text) VALUES (?, ?, ?)",
            (pdf_path.name, number, text),
        )
        stored += 1
    conn.commit()
    return stored, low_text


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python ingest.py <notes.pdf>")
    stored, low_text = ingest(sys.argv[1], db.connect())
    print(f"Stored {stored} pages.")
    if low_text:
        print(f"Skipped pages with little text (handwritten or scanned?): {low_text}")
