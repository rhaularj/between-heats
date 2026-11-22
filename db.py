"""SQLite storage and config loading shared by every module."""
import sqlite3
import tomllib
from pathlib import Path

ROOT = Path(__file__).parent
DB_PATH = ROOT / "data" / "between_heats.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY,
    file TEXT NOT NULL,
    page INTEGER NOT NULL,
    text TEXT NOT NULL,
    UNIQUE (file, page)
);
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY,
    file TEXT NOT NULL,
    page INTEGER NOT NULL,
    topic TEXT NOT NULL,
    question TEXT NOT NULL,
    options TEXT NOT NULL,          -- JSON list of 4 strings
    answer_index INTEGER NOT NULL,
    explanation TEXT NOT NULL,
    quote TEXT NOT NULL,
    status TEXT NOT NULL,           -- 'passed' or 'rejected'
    reject_reason TEXT,
    box INTEGER NOT NULL DEFAULT 1,
    last_asked TEXT
);
CREATE TABLE IF NOT EXISTS answers (
    id INTEGER PRIMARY KEY,
    question_id INTEGER NOT NULL REFERENCES questions(id),
    correct INTEGER NOT NULL,
    answered_at TEXT NOT NULL
);
"""


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def load_config(path: Path | str = ROOT / "config.toml") -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)
