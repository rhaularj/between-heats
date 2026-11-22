import csv

import eval as evaluation


def sheet(tmp_path, marks):
    path = tmp_path / "review.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "grounded (y/n)"])
        w.writerows([i, m] for i, m in enumerate(marks))
    return path


def test_score_passes_at_95_percent(tmp_path):
    assert evaluation.score_review(sheet(tmp_path, ["y"] * 19 + ["n"]))


def test_score_fails_below_95_percent(tmp_path):
    assert not evaluation.score_review(sheet(tmp_path, ["y"] * 18 + ["n", "n"]))


def test_unmarked_sheet_does_not_pass(tmp_path):
    assert not evaluation.score_review(sheet(tmp_path, ["", ""]))
