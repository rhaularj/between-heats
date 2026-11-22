"""Study logic shared by the Telegram bot and the terminal replay.

Repeat system (Leitner, 3 boxes): a wrong answer sends a question to box 1,
a right answer moves it up one box. Sets are picked in this order:
  1. box-1 questions answered wrong earlier (not in the last hour)
  2. questions never asked
  3. everything else, lowest box and oldest first
"""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta

RECENT = timedelta(hours=1)


@dataclass
class Question:
    id: int
    page: int
    topic: str
    text: str
    options: list[str]
    answer_index: int
    explanation: str


def _to_question(row) -> Question:
    return Question(row["id"], row["page"], row["topic"], row["question"], json.loads(row["options"]),
                    row["answer_index"], row["explanation"])


def pick_set(conn, size: int, now: datetime, max_repeats: int = 2) -> list[Question]:
    """Up to `max_repeats` missed questions, then new ones, then the rest.

    Capping repeats keeps a bad set from turning every later set into the same questions.
    """
    recent = (now - RECENT).isoformat()
    repeats = conn.execute(
        """SELECT * FROM questions WHERE status = 'passed' AND box = 1
             AND last_asked IS NOT NULL AND last_asked <= ?
           ORDER BY last_asked, id LIMIT ?""",
        (recent, max_repeats),
    ).fetchall()
    taken = [r["id"] for r in repeats]
    exclude = f"AND id NOT IN ({','.join('?' * len(taken))})" if taken else ""
    rest = conn.execute(
        f"""SELECT * FROM questions WHERE status = 'passed' {exclude}
            ORDER BY
              CASE WHEN last_asked IS NOT NULL AND last_asked > ? THEN 1 ELSE 0 END,
              CASE WHEN last_asked IS NULL THEN 0 ELSE 1 END,
              box, last_asked, id
            LIMIT ?""",
        (*taken, recent, size - len(repeats)),
    ).fetchall()
    return [_to_question(r) for r in [*repeats, *rest]]


def record_answer(conn, question_id: int, choice: int, now: datetime, boxes: int = 3) -> tuple[bool, Question]:
    row = conn.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()
    q = _to_question(row)
    correct = choice == q.answer_index
    new_box = min(boxes, row["box"] + 1) if correct else 1
    conn.execute("UPDATE questions SET box = ?, last_asked = ? WHERE id = ?", (new_box, now.isoformat(), q.id))
    conn.execute("INSERT INTO answers (question_id, correct, answered_at) VALUES (?, ?, ?)",
                 (q.id, int(correct), now.isoformat()))
    conn.commit()
    return correct, q


def weak_spots(conn, limit: int = 5) -> list[dict]:
    rows = conn.execute(
        """SELECT q.page, q.topic, SUM(1 - a.correct) AS wrong, COUNT(*) AS asked
           FROM answers a JOIN questions q ON q.id = a.question_id
           GROUP BY q.page, q.topic
           HAVING wrong > 0
           ORDER BY wrong DESC, CAST(wrong AS REAL) / asked DESC, q.page
           LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def weak_spots_text(conn, limit: int = 5) -> str:
    spots = weak_spots(conn, limit)
    if not spots:
        return "No weak spots yet. Nice work, or answer a few more sets first."
    lines = ["Weak spots to review before the quiz:"]
    for s in spots:
        lines.append(f"- {s['topic']} (page {s['page']}): {s['wrong']} wrong of {s['asked']}")
    return "\n".join(lines)


def feedback_text(correct: bool, q: Question) -> str:
    head = "Correct!" if correct else f"Not quite. Answer: {'ABCD'[q.answer_index]}. {q.options[q.answer_index]}"
    return f"{head}\n{q.explanation}\n(Notes page {q.page})"
