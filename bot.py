"""Telegram bot: delivers 5-question sets with tap-to-answer buttons.

Commands:
  /start   shows your chat id (put it in .env as TELEGRAM_CHAT_ID)
  /now     send a set right away
  /weak    show your weak spots
  /replay  play Chloe's Oct 23-26 weekend on a fake clock; each gap starts when you finish a set

Real gaps from the calendar are scheduled automatically when TELEGRAM_CHAT_ID is set
(only send times still in the future).

Usage: python bot.py
"""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

import db
import study
from replay import timeline

CFG = db.load_config()
TZ = ZoneInfo(CFG["gaps"]["timezone"])
CONN = db.connect()


def render(q: study.Question, header: str, pos: int, total: int) -> tuple[str, InlineKeyboardMarkup]:
    lines = [header, f"Q{pos}/{total} | {q.topic} (page {q.page})", "", q.text, ""]
    lines += [f"{'ABCD'[i]}. {opt}" for i, opt in enumerate(q.options)]
    buttons = [InlineKeyboardButton("ABCD"[i], callback_data=f"a:{q.id}:{i}") for i in range(4)]
    return "\n".join(lines), InlineKeyboardMarkup([buttons])


def queue_set(chat_data: dict, sim_time: datetime, label: str) -> bool:
    """Add a set to this chat's queue. Returns False if there are no questions."""
    qs = study.pick_set(CONN, CFG["study"]["set_size"], sim_time, CFG["study"]["max_repeats_per_set"])
    if not qs:
        return False
    # Mark them as asked now so a set queued right after doesn't pick the same questions.
    for q in qs:
        CONN.execute("UPDATE questions SET last_asked = ? WHERE id = ?", (sim_time.isoformat(), q.id))
    CONN.commit()
    chat_data.setdefault("queue", []).append(
        {"time": sim_time, "label": label, "ids": [q.id for q in qs], "pos": 0, "right": 0})
    return True


async def send_current(chat_id: int, chat_data: dict, bot) -> None:
    queue = chat_data.get("queue", [])
    if not queue:
        return
    s = queue[0]
    row = CONN.execute("SELECT * FROM questions WHERE id = ?", (s["ids"][s["pos"]],)).fetchone()
    header = f"{s['time']:%a %b %d %H:%M} | {s['label']}"
    text, markup = render(study._to_question(row), header, s["pos"] + 1, len(s["ids"]))
    await bot.send_message(chat_id, text, reply_markup=markup)


async def deliver(chat_id: int, chat_data: dict, bot, sim_time: datetime, label: str) -> None:
    busy = bool(chat_data.get("queue"))
    if not queue_set(chat_data, sim_time, label):
        await bot.send_message(chat_id, "No checked questions yet. Run ingest.py and generate.py first.")
        return
    log(chat_id, f"set queued for {sim_time:%a %b %d %H:%M} ({label}): questions {chat_data['queue'][-1]['ids']}")
    if not busy:
        await send_current(chat_id, chat_data, bot)


def log(chat_id: int, message: str) -> None:
    print(f"{datetime.now():%H:%M:%S} chat {chat_id}: {message}", flush=True)


async def advance_replay(chat_id: int, chat_data: dict, bot) -> None:
    """Play the next replay event. Weak-spot lists go straight out; a set waits until it is finished."""
    events = chat_data.get("replay")
    while events:
        sim_time, kind, label = events.pop(0)
        if kind == "weak":
            log(chat_id, "replay: weak-spot list sent")
            await bot.send_message(chat_id, f"{sim_time:%a %b %d %H:%M} | {label}\n\n" + study.weak_spots_text(CONN))
            continue
        await deliver(chat_id, chat_data, bot, sim_time, label)
        return
    if events is not None:
        chat_data["replay"] = None
        log(chat_id, "replay finished")
        await bot.send_message(chat_id, "Replay finished. That was Chloe's whole weekend. /weak shows the weak spots.")


async def on_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cq = update.callback_query
    await cq.answer()
    _, qid, choice = cq.data.split(":")
    queue = context.chat_data.get("queue", [])
    if not queue or queue[0]["ids"][queue[0]["pos"]] != int(qid):
        return  # an old button was tapped again
    s = queue[0]
    correct, q = study.record_answer(CONN, int(qid), int(choice), s["time"], CFG["study"]["boxes"])
    s["right"] += correct
    chat_id = update.effective_chat.id
    log(chat_id, f"answer q{qid}: {'right' if correct else 'wrong'}")
    await cq.edit_message_text(f"{cq.message.text}\n\nYou chose {'ABCD'[int(choice)]}. "
                               + study.feedback_text(correct, q))
    s["pos"] += 1
    if s["pos"] == len(s["ids"]):
        queue.pop(0)
        log(chat_id, f"set done: {s['right']}/{len(s['ids'])}")
        await context.bot.send_message(chat_id, f"Set done: {s['right']}/{len(s['ids'])}. "
                                                "The next set comes in your next gap.")
        if not queue and context.chat_data.get("replay") is not None:
            await advance_replay(chat_id, context.chat_data, context.bot)
            return
    await send_current(chat_id, context.chat_data, context.bot)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"Between Heats is ready.\nYour chat id is {update.effective_chat.id} "
        "(put it in .env as TELEGRAM_CHAT_ID).\n\n/now: a set right away\n/weak: weak spots\n"
        "/replay: play the Oct 23-26 weekend at your own pace")


async def cmd_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await deliver(update.effective_chat.id, context.chat_data, context.bot, datetime.now(TZ), "Right now")


async def cmd_weak(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(study.weak_spots_text(CONN))


async def cmd_replay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    CONN.execute("DELETE FROM answers")
    CONN.execute("UPDATE questions SET box = 1, last_asked = NULL")
    CONN.commit()
    chat_id = update.effective_chat.id
    events = timeline(CFG)
    context.chat_data["queue"] = []
    context.chat_data["replay"] = list(events)
    log(chat_id, f"replay started: {len(events)} events")
    await update.message.reply_text(
        f"Replaying Chloe's Oct 23-26 weekend: {sum(k == 'set' for _, k, _ in events)} sets on a fake clock. "
        "Each gap starts when you finish the set before it. Study history was reset for the demo.")
    await advance_replay(chat_id, context.chat_data, context.bot)


async def gap_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    await deliver(job.chat_id, context.chat_data, context.bot, *job.data)


def main() -> None:
    load_dotenv(db.ROOT / ".env")
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set. Copy .env.example to .env and add it.")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("now", cmd_now))
    app.add_handler(CommandHandler("weak", cmd_weak))
    app.add_handler(CommandHandler("replay", cmd_replay))
    app.add_handler(CallbackQueryHandler(on_answer, pattern=r"^a:"))

    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if chat_id:
        now = datetime.now(TZ)
        future = [(t, label) for t, kind, label in timeline(CFG) if kind == "set" and t > now]
        for t, label in future:
            app.job_queue.run_once(gap_job, when=t, data=(t, label), chat_id=int(chat_id))
        print(f"Scheduled {len(future)} future gap sets for chat {chat_id}.")
    print("Bot running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
