"""Evaluation for the definition of done.

  python eval.py sends    # check 1 + 3: audit the replay log against the calendar, and the repeat loop
  python eval.py review   # check 2: export 20 random checked questions for a manual review
  python eval.py score    # check 2: score the filled-in review sheet (target: at least 95% grounded)

Check 4 ($0 spent) is a screenshot of https://openrouter.ai/activity.
"""
import csv
import json
import random
import sys
from datetime import datetime, time
from zoneinfo import ZoneInfo

import db
import gaps
from replay import LOG_PATH

OUT = db.ROOT / "eval" / "out"
REVIEW_PATH = OUT / "review_sheet.csv"


def audit_sends(cfg: dict, conn) -> bool:
    """Independent re-check of every logged send time. Doesn't reuse the gap-finding code."""
    g = cfg["gaps"]
    tz = ZoneInfo(g["timezone"])
    events = gaps.load_events(db.ROOT / "data" / "chloe.ics", tz)
    is_bus = lambda e: any(k in e.summary.lower() for k in g["gap_keywords"])
    sleep_start, sleep_end = time.fromisoformat(g["sleep_start"]), time.fromisoformat(g["sleep_end"])
    meet_dates = set()
    for e in events:
        if e.all_day and any(k in e.summary.lower() for k in g["meet_keywords"]):
            d = e.start
            while d < e.end:
                meet_dates.add(d)
                d = d.fromordinal(d.toordinal() + 1)

    with open(LOG_PATH, encoding="utf-8") as f:
        sets = [r for r in csv.DictReader(f) if r["kind"] == "set"]
    problems = []
    for r in sets:
        t = datetime.fromisoformat(r["sim_time"]).astimezone(tz)
        if t.time() >= sleep_start or t.time() < sleep_end:
            problems.append(f"{t:%a %H:%M} is during sleep")
        for e in events:
            if not e.all_day and not is_bus(e) and e.start <= t < e.end:
                problems.append(f"{t:%a %H:%M} is during '{e.summary}'")
        in_bus = any(not e.all_day and is_bus(e) and e.start <= t < e.end for e in events)
        if not in_bus and t.date() not in meet_dates:
            problems.append(f"{t:%a %H:%M} is not in a bus ride or on a meet day")
    print(f"Check 1 - sets land in gaps: {len(sets)} sets audited, {len(problems)} problems")
    for p in problems:
        print("  - " + p)

    wrong = conn.execute("SELECT question_id, answered_at FROM answers WHERE correct = 0").fetchall()
    came_back = [w for w in wrong if conn.execute(
        "SELECT 1 FROM answers WHERE question_id = ? AND answered_at > ?", (w[0], w[1])).fetchone()]
    print(f"Check 3 - repeat loop: {len(came_back)} of {len(wrong)} missed questions came back in a later set")
    ok = not problems and bool(came_back)
    print("PASS" if ok else "FAIL")
    return ok


def export_review(conn, n: int = 20, seed: int = 1) -> None:
    rows = conn.execute(
        "SELECT q.*, p.text AS page_text FROM questions q JOIN pages p ON p.file = q.file AND p.page = q.page "
        "WHERE q.status = 'passed'").fetchall()
    sample = random.Random(seed).sample(rows, min(n, len(rows)))
    OUT.mkdir(parents=True, exist_ok=True)
    with open(REVIEW_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "page", "question", "correct_answer", "explanation", "quote", "page_text",
                    "grounded (y/n)", "notes"])
        for r in sample:
            w.writerow([r["id"], r["page"], r["question"], json.loads(r["options"])[r["answer_index"]],
                        r["explanation"], r["quote"], r["page_text"], "", ""])
    stats = conn.execute("SELECT status, COUNT(*) FROM questions GROUP BY status").fetchall()
    print(f"Wrote {len(sample)} questions to {REVIEW_PATH}")
    print("Bank: " + ", ".join(f"{s} {c}" for s, c in stats))
    print("Open it in Excel, mark each row y or n in 'grounded (y/n)', save as CSV, then run: python eval.py score")


def score_review(path=None) -> bool:
    with open(path or REVIEW_PATH, encoding="utf-8") as f:
        marks = [r["grounded (y/n)"].strip().lower() for r in csv.DictReader(f)]
    done = [m for m in marks if m in ("y", "n")]
    if len(done) < len(marks):
        print(f"{len(marks) - len(done)} rows are not marked y or n yet.")
    if not done:
        return False
    pct = 100 * done.count("y") / len(done)
    print(f"Check 2 - grounded: {done.count('y')}/{len(done)} = {pct:.0f}% (target 95%)")
    print("PASS" if pct >= 95 else "FAIL")
    return pct >= 95


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "sends":
        audit_sends(db.load_config(), db.connect())
    elif cmd == "review":
        export_review(db.connect())
    elif cmd == "score":
        score_review()
    else:
        raise SystemExit(__doc__)
