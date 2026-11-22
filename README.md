# Between Heats

A study agent for Chloe Nguyen, a nursing student and varsity swimmer. It turns her own course notes into 5-question study sets and sends them on Telegram during gaps in her calendar: team bus rides and the waits between races at meets. It never sends during practice, warm-ups, races, shifts, lectures or sleep.

It costs $0. It uses OpenRouter's free models, a Telegram bot, Python and SQLite.

## How it works

```
notes.pdf -> ingest.py   -> pages table (one row per page)
          -> generate.py -> writer model drafts questions
                         -> check 1 (code): the quote must appear on the cited page
                         -> check 2 (checker model): the page must support the answer
                         -> question bank (only questions that pass both checks)
chloe.ics -> gaps.py     -> send times (bus rides + meet days, minus blocked events and sleep)
          -> bot.py / replay.py -> 5-question sets -> answers -> study.py (3-box repeats, weak spots)
```

AI only runs in `generate.py`. A 10-page notes file takes about 10 requests, and every reply is cached in `data/cache/`, so re-runs are free. Answering questions makes no AI calls.

| Job | Model (free) | Backup |
|---|---|---|
| Write questions | `nvidia/nemotron-3-ultra-550b-a55b:free` | `google/gemma-4-31b-it:free` |
| Fact-check questions | `google/gemma-4-31b-it:free` | `google/gemma-4-26b-a4b-it:free` |

Models and all calendar rules are set in `config.toml`. Free models on OpenRouter change often, so check https://openrouter.ai/models?q=free if one stops working.

## Setup

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # macOS/Linux: .venv/bin/pip
cp .env.example .env                              # then fill in the keys below
```

- `OPENROUTER_API_KEY`: from https://openrouter.ai/keys
- `TELEGRAM_BOT_TOKEN`: message @BotFather on Telegram, send `/newbot`
- `TELEGRAM_CHAT_ID`: start the bot, send `/start`, and copy the number it replies with

## Run it

```bash
python ingest.py data/notes.pdf     # store the notes, page by page
python generate.py                  # build and check the question bank (uses OpenRouter)
python gaps.py                      # print the send times found in data/chloe.ics
python replay.py                    # replay Oct 23-26 in the terminal (add --auto to simulate answers)
python bot.py                       # Telegram bot; send /replay to play the weekend in ~3 minutes
```

Telegram commands: `/now` sends a set right away, `/weak` lists weak spots, and `/replay` plays the weekend on a fake clock.

## Evaluation (definition of done)

| Check | How |
|---|---|
| 1. Sets land in gaps | `python replay.py --auto`, then `python eval.py sends` (separate audit of every send time) |
| 2. At least 95% of questions grounded | `python eval.py review`, mark each row y/n in `eval/out/review_sheet.csv`, then `python eval.py score` |
| 3. The repeat loop works | `python eval.py sends` (missed questions that came back later) |
| 4. $0 spent | screenshot of https://openrouter.ai/activity |

Run the tests (no keys or network needed): `python -m pytest -q`

## Test data

- `data/notes.pdf`: 10 pages of original sample pathophysiology notes (Ch. 7 fluid and electrolytes, Ch. 8 acid-base), written for this project. Rebuild them with `python scripts/make_sample_notes.py`.
- `data/chloe.ics`: Chloe's Oct 23-26 calendar, rebuilt from her persona screenshots. The Friday and Monday events come from her calendar. The Saturday and Sunday warm-up and race times are assumed, because her calendar only shows the all-day meet.

## Known limits

- Typed PDFs only. Handwritten or scanned pages are skipped and listed when you run `ingest.py` (reading them with a vision model is a stretch goal).
- The calendar is a fixed `.ics` file, not a live sync with her phone.
- Gaps are bus rides and meet days only, not the time between classes.
- Telegram needs a connection. A set sent with no signal arrives when the phone reconnects.
- The bot keeps its set queue in memory, so restarting the bot drops any set that's in progress.
