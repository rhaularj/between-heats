"""Exercise the bot's set flow with a fake Telegram client (no network)."""
import asyncio
import json
from datetime import datetime
from types import SimpleNamespace

import bot
import db

CHAT = 42
T = datetime(2026, 10, 23, 14, 0, tzinfo=bot.TZ)


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append(SimpleNamespace(text=text, markup=reply_markup))


def tap(fake_bot, chat_data, data):
    edits = []

    async def answer():
        pass

    async def edit(text):
        edits.append(text)

    cq = SimpleNamespace(data=data, answer=answer, edit_message_text=edit,
                         message=SimpleNamespace(text=fake_bot.sent[-1].text))
    update = SimpleNamespace(callback_query=cq, effective_chat=SimpleNamespace(id=CHAT))
    context = SimpleNamespace(chat_data=chat_data, bot=fake_bot)
    asyncio.run(bot.on_answer(update, context))
    return edits


def test_full_set_flow(monkeypatch):
    conn = db.connect(":memory:")
    for i in range(7):
        conn.execute("INSERT INTO questions (file, page, topic, question, options, answer_index, explanation,"
                     " quote, status) VALUES ('n.pdf', 1, 't', ?, ?, 2, 'why', 'q', 'passed')",
                     (f"Q{i}?", json.dumps(["a", "b", "c", "d"])))
    monkeypatch.setattr(bot, "CONN", conn)
    fb, chat_data = FakeBot(), {}

    asyncio.run(bot.deliver(CHAT, chat_data, fb, T, "Team bus"))
    asyncio.run(bot.deliver(CHAT, chat_data, fb, T, "Meet day"))  # queued behind the first set
    assert len(fb.sent) == 1 and "Q1/5" in fb.sent[0].text and "Team bus" in fb.sent[0].text

    for i in range(5):
        qid = chat_data["queue"][0]["ids"][chat_data["queue"][0]["pos"]]
        edits = tap(fb, chat_data, f"a:{qid}:{2 if i else 0}")  # first answer wrong, rest right
        assert ("Not quite" if i == 0 else "Correct!") in edits[0]
    assert any("Set done: 4/5" in m.text for m in fb.sent)
    # The second set starts on its own, with different questions where possible.
    assert "Meet day" in fb.sent[-1].text and "Q1/5" in fb.sent[-1].text
    assert conn.execute("SELECT COUNT(*) FROM answers").fetchone()[0] == 5


def test_replay_waits_for_each_set(monkeypatch):
    conn = db.connect(":memory:")
    for i in range(12):
        conn.execute("INSERT INTO questions (file, page, topic, question, options, answer_index, explanation,"
                     " quote, status) VALUES ('n.pdf', 1, 't', ?, ?, 0, 'why', 'q', 'passed')",
                     (f"Q{i}?", json.dumps(["a", "b", "c", "d"])))
    monkeypatch.setattr(bot, "CONN", conn)
    events = [(T, "set", "Team bus"), (T.replace(hour=20), "weak", "Night before the quiz"),
              (T.replace(hour=21), "set", "Meet day")]
    monkeypatch.setattr(bot, "timeline", lambda cfg: list(events))
    fb, chat_data = FakeBot(), {}

    async def reply_text(text):
        fb.sent.append(SimpleNamespace(text=text, markup=None))

    update = SimpleNamespace(effective_chat=SimpleNamespace(id=CHAT), message=SimpleNamespace(reply_text=reply_text))
    asyncio.run(bot.cmd_replay(update, SimpleNamespace(chat_data=chat_data, bot=fb)))
    assert len(chat_data["queue"]) == 1  # only the first gap; the rest waits
    assert "Team bus" in fb.sent[-1].text

    def finish_set(wrong=False):
        for _ in range(5):
            s = chat_data["queue"][0]
            tap(fb, chat_data, f"a:{s['ids'][s['pos']]}:{1 if wrong else 0}")

    finish_set(wrong=True)
    texts = [m.text for m in fb.sent]
    weak_at = next(i for i, t in enumerate(texts) if "Weak spots" in t)
    meet_at = next(i for i, t in enumerate(texts) if "Meet day" in t)
    assert weak_at < meet_at  # weak-spot list arrives in timeline order, after the first set
    finish_set()
    assert "Replay finished" in fb.sent[-1].text and chat_data["replay"] is None


def test_stale_button_is_ignored(monkeypatch):
    conn = db.connect(":memory:")
    conn.execute("INSERT INTO questions (file, page, topic, question, options, answer_index, explanation, quote,"
                 " status) VALUES ('n.pdf', 1, 't', 'Q?', '[\"a\",\"b\",\"c\",\"d\"]', 0, 'x', 'q', 'passed')")
    monkeypatch.setattr(bot, "CONN", conn)
    fb, chat_data = FakeBot(), {}
    asyncio.run(bot.deliver(CHAT, chat_data, fb, T, "Bus"))
    tap(fb, chat_data, "a:1:0")
    assert tap(fb, chat_data, "a:1:0") == []  # same button again: nothing recorded
    assert conn.execute("SELECT COUNT(*) FROM answers").fetchone()[0] == 1
