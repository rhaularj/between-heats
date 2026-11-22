"""Replay Chloe's Oct 23-26 weekend on a fake clock, in the terminal.

  python replay.py            # you answer each question (A-D)
  python replay.py --auto     # a simulated student answers (about 70% right), runs in seconds

Writes every send time to eval/out/replay_log.csv for the evaluation.
"""
import argparse
import csv
import random
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import db
import gaps
import study

LOG_PATH = db.ROOT / "eval" / "out" / "replay_log.csv"


def timeline(cfg: dict, ics_path=db.ROOT / "data" / "chloe.ics") -> list[tuple[datetime, str, str]]:
    """All replay events in time order: ("set", label) at each gap, plus the weak-spot list."""
    tz = ZoneInfo(cfg["gaps"]["timezone"])
    events = [(st.at, "set", st.label) for st in gaps.send_times_for(ics_path, cfg)]
    quiz = date.fromisoformat(cfg["study"]["quiz_date"])
    weak_at = datetime.combine(quiz - timedelta(days=1), time(cfg["study"]["weak_list_hour"]), tz)
    events.append((weak_at, "weak", "Night before the quiz"))
    return sorted(events)


def ask(q: study.Question, auto: bool, rng: random.Random) -> int:
    print(f"\n  ({q.topic}, page {q.page}) {q.text}")
    for i, opt in enumerate(q.options):
        print(f"    {'ABCD'[i]}. {opt}")
    if auto:
        choice = q.answer_index if rng.random() < 0.7 else rng.choice([i for i in range(4) if i != q.answer_index])
        print(f"  > {'ABCD'[choice]}")
        return choice
    while (raw := input("  Your answer (A-D): ").strip().upper()) not in ("A", "B", "C", "D"):
        pass
    return "ABCD".index(raw)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--auto", action="store_true", help="simulate answers instead of asking you")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    cfg, conn, rng = db.load_config(), db.connect(), random.Random(args.seed)
    if not conn.execute("SELECT 1 FROM questions WHERE status = 'passed' LIMIT 1").fetchone():
        raise SystemExit("No checked questions yet. Run: python ingest.py data/notes.pdf, then python generate.py")
    # Start the replay from a clean study history.
    conn.execute("DELETE FROM answers")
    conn.execute("UPDATE questions SET box = 1, last_asked = NULL")
    conn.commit()

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "w", newline="", encoding="utf-8") as f:
        log = csv.writer(f)
        log.writerow(["sim_time", "kind", "label", "question_ids", "correct"])
        for n, (now, kind, label) in enumerate(timeline(cfg), start=1):
            print(f"\n=== {now:%a %b %d %H:%M} | {label} ===")
            if kind == "weak":
                print(study.weak_spots_text(conn))
                log.writerow([now.isoformat(), kind, label, "", ""])
                continue
            qs = study.pick_set(conn, cfg["study"]["set_size"], now)
            right = 0
            for q in qs:
                correct, _ = study.record_answer(conn, q.id, ask(q, args.auto, rng), now, cfg["study"]["boxes"])
                right += correct
                print("  " + study.feedback_text(correct, q).replace("\n", "\n  "))
            print(f"--- Set score: {right}/{len(qs)}")
            log.writerow([now.isoformat(), kind, label, " ".join(str(q.id) for q in qs), right])
    print(f"\nReplay log written to {LOG_PATH}")


if __name__ == "__main__":
    main()
