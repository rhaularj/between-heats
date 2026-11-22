from pathlib import Path

import db
from ingest import ingest

NOTES = Path(__file__).resolve().parent.parent / "data" / "notes.pdf"


def test_every_page_is_stored_with_its_number():
    conn = db.connect(":memory:")
    stored, low_text = ingest(NOTES, conn)
    assert stored == 10 and low_text == []
    row = conn.execute("SELECT text FROM pages WHERE page = 5").fetchone()
    assert "Potassium" in row["text"]
