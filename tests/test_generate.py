import json

import db
import generate

PAGE_TEXT = ("Normal serum potassium is 3.5 to 5.0 mEq/L. Hyperkalemia is a serum potassium above\n"
             "5.0 mEq/L. ECG changes include tall, peaked T waves and a widened QRS complex.")


def q(question, quote, page=5, answer=0, topic="Hyperkalemia ECG"):
    return {"question": question, "options": ["Peaked T waves", "U waves", "Short QT", "Flat P waves"],
            "answer_index": answer, "explanation": "From the notes.", "page": page, "quote": quote, "topic": topic}


def fake_chat(models, prompt, system=None):
    if "fact-checker" in (system or ""):
        # Checker approves question 0, rejects question 1.
        return json.dumps({"verdicts": [{"index": 0, "supported": True, "reason": "ok"},
                                        {"index": 1, "supported": False, "reason": "not in notes"}]})
    return "```json\n" + json.dumps({"questions": [
        q("Which ECG change is seen in hyperkalemia?", "ECG changes include tall, peaked T waves and a widened QRS"),
        q("What else happens to the ECG in hyperkalemia?", "a widened QRS complex"),
        q("Made-up quote question here?", "Potassium is stored mainly in the liver"),
        q("Question citing a page not given?", "Normal serum potassium is 3.5 to 5.0 mEq/L.", page=9),
        {"question": "Broken item"},
    ]}) + "\n```"


def setup():
    conn = db.connect(":memory:")
    conn.execute("INSERT INTO pages (file, page, text) VALUES ('notes.pdf', 5, ?)", (PAGE_TEXT,))
    return conn


def test_quote_match_ignores_line_breaks_and_case():
    assert generate.quote_on_page("TALL, PEAKED T waves and a widened QRS complex", PAGE_TEXT, 85)
    assert not generate.quote_on_page("Potassium is stored mainly in the liver", PAGE_TEXT, 85)


def test_two_layer_check_keeps_only_supported_questions():
    conn = setup()
    stats = generate.generate(conn, db.load_config(), chat=fake_chat)
    assert stats == {"drafted": 4, "failed_quote": 2, "failed_checker": 1, "passed": 1}
    passed = conn.execute("SELECT * FROM questions WHERE status = 'passed'").fetchall()
    assert [r["question"] for r in passed] == ["Which ECG change is seen in hyperkalemia?"]
    reasons = {r["reject_reason"] for r in conn.execute("SELECT * FROM questions WHERE status='rejected'")}
    assert reasons == {"quote not found on cited page", "cites page 9, which was not given", "checker: not in notes"}


def test_shuffle_keeps_the_right_answer():
    d = generate.Draft.model_validate(q("Which ECG change is seen in hyperkalemia?", "x" * 20))
    options, answer = generate.shuffle_options(d)
    assert options[answer] == "Peaked T waves" and sorted(options) == sorted(d.options)
