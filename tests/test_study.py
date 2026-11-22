import json
from datetime import datetime, timedelta

import db
import study

T0 = datetime(2026, 10, 23, 14, 0)


def bank(n=12):
    conn = db.connect(":memory:")
    for i in range(n):
        conn.execute(
            "INSERT INTO questions (file, page, topic, question, options, answer_index, explanation, quote, status)"
            " VALUES ('notes.pdf', ?, ?, ?, ?, 0, 'why', 'quote', 'passed')",
            (i % 10 + 1, f"Topic {i}", f"Question {i}?", json.dumps(["right", "b", "c", "d"])),
        )
    conn.execute("INSERT INTO questions (file, page, topic, question, options, answer_index, explanation, quote,"
                 " status) VALUES ('notes.pdf', 1, 'Bad', 'Rejected?', '[\"a\",\"b\",\"c\",\"d\"]', 0, 'x', 'x', 'rejected')")
    return conn


def answer_set(conn, qs, now, wrong_ids=()):
    for q in qs:
        study.record_answer(conn, q.id, 1 if q.id in wrong_ids else 0, now)


def test_rejected_questions_are_never_asked():
    conn = bank()
    asked = study.pick_set(conn, 50, T0)
    assert "Rejected?" not in [q.text for q in asked]


def test_wrong_answer_comes_back_in_the_next_set_not_right_away():
    conn = bank()
    first = study.pick_set(conn, 5, T0)
    missed = first[2].id
    answer_set(conn, first, T0, wrong_ids={missed})

    # 10 minutes later: too soon, the missed question waits.
    assert missed not in [q.id for q in study.pick_set(conn, 5, T0 + timedelta(minutes=10))]
    # Next gap, 2 hours later: it comes back first.
    assert study.pick_set(conn, 5, T0 + timedelta(hours=2))[0].id == missed


def test_a_bad_set_does_not_take_over_the_next_one():
    conn = bank()
    first = study.pick_set(conn, 5, T0)
    answer_set(conn, first, T0, wrong_ids={q.id for q in first})  # all 5 wrong

    second = study.pick_set(conn, 5, T0 + timedelta(hours=2))
    repeated = {q.id for q in second} & {q.id for q in first}
    assert len(second) == 5 and len(repeated) == 2  # 2 repeats, 3 new
    # The other 3 missed questions come back in the set after that.
    answer_set(conn, second, T0 + timedelta(hours=2))
    third = study.pick_set(conn, 5, T0 + timedelta(hours=4))
    assert len({q.id for q in third} & ({q.id for q in first} - repeated)) == 2


def test_new_questions_before_mastered_ones():
    conn = bank()
    first = study.pick_set(conn, 5, T0)
    answer_set(conn, first, T0)
    second = study.pick_set(conn, 5, T0 + timedelta(hours=2))
    assert not {q.id for q in first} & {q.id for q in second}


def test_weak_spot_list_ranks_most_missed_pages():
    conn = bank()
    qs = study.pick_set(conn, 5, T0)
    answer_set(conn, qs, T0, wrong_ids={qs[0].id})
    study.record_answer(conn, qs[0].id, 3, T0 + timedelta(hours=2))  # wrong again
    spots = study.weak_spots(conn)
    assert spots[0]["topic"] == qs[0].topic and spots[0]["wrong"] == 2
    assert f"page {qs[0].page}" in study.weak_spots_text(conn)
