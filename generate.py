"""Build the question bank from stored pages.

1. Writer model drafts questions from 2 pages at a time (JSON, validated).
2. Check 1 (code): each question's supporting quote must appear on its cited page.
3. Check 2 (checker model, a different model family): does the page support the answer?
Only questions that pass both checks are used in study sets.

Usage: python generate.py
"""
import json
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field, ValidationError, field_validator
from rapidfuzz import fuzz

import db
import llm

WRITER_SYSTEM = (
    "You write multiple-choice study questions for a nursing student, using ONLY the notes given. "
    "Never add facts that are not in the notes. Reply with JSON only."
)

WRITER_PROMPT = """Notes (each page is marked with its page number):

{pages}

Write {count} multiple-choice questions that test understanding of these notes, spread across the pages.
Rules:
- Every fact in the question, correct answer and explanation must come from the notes.
- Wrong options must be plausible but clearly wrong according to the notes.
- "quote" must be copied word for word from the cited page (one sentence or part of one, 8-30 words) and must support the correct answer.
- "topic" is 2-4 words, e.g. "Hyperkalemia ECG".

Reply with this JSON shape:
{{"questions": [{{"question": "...", "options": ["...", "...", "...", "..."], "answer_index": 0,
  "explanation": "one sentence", "page": 1, "quote": "...", "topic": "..."}}]}}"""

CHECKER_SYSTEM = "You are a strict fact-checker for nursing study questions. Reply with JSON only."

CHECKER_PROMPT = """Source notes:

{pages}

For each question below, decide if the cited page of the notes clearly supports the marked correct answer,
and that the answer is the only correct option. If anything relies on facts that are not in the notes, it is NOT supported.

{questions}

Reply with this JSON shape:
{{"verdicts": [{{"index": 0, "supported": true, "reason": "short reason"}}]}}"""


class Draft(BaseModel):
    question: str = Field(min_length=10)
    options: list[str] = Field(min_length=4, max_length=4)
    answer_index: int = Field(ge=0, le=3)
    explanation: str = Field(min_length=5)
    page: int
    quote: str = Field(min_length=15)
    topic: str = Field(min_length=2, max_length=60)

    @field_validator("options")
    @classmethod
    def distinct(cls, v):
        if len({o.strip().lower() for o in v}) != 4:
            raise ValueError("options must be 4 different answers")
        return v


def normalize(text: str) -> str:
    text = text.lower().replace("’", "'").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text).strip()


def quote_on_page(quote: str, page_text: str, min_score: int) -> bool:
    return fuzz.partial_ratio(normalize(quote), normalize(page_text)) >= min_score


def format_pages(pages) -> str:
    return "\n\n".join(f"[PAGE {p['page']}]\n{p['text']}" for p in pages)


def draft_questions(pages, count: int, models, chat) -> list[Draft]:
    prompt = WRITER_PROMPT.format(pages=format_pages(pages), count=count)
    for attempt in range(2):
        try:
            items = llm.parse_json(chat(models, prompt, system=WRITER_SYSTEM))["questions"]
        except (ValueError, KeyError, TypeError) as exc:
            if attempt:
                raise llm.LLMError(f"Writer reply was not usable JSON: {exc}")
            prompt += "\n\nYour previous reply was not valid JSON. Reply with the JSON object only."
            continue
        drafts = []
        for item in items:
            try:
                drafts.append(Draft.model_validate(item))
            except ValidationError:
                pass  # drop malformed items, keep the rest
        return drafts
    return []


def check_questions(pages, drafts: list[Draft], models, chat) -> dict[int, tuple[bool, str]]:
    listing = "\n\n".join(
        f"Question {i} (page {d.page}): {d.question}\n"
        + "\n".join(f"  {'ABCD'[j]}. {o}" for j, o in enumerate(d.options))
        + f"\n  Marked correct: {'ABCD'[d.answer_index]}"
        for i, d in enumerate(drafts)
    )
    reply = llm.parse_json(chat(models, CHECKER_PROMPT.format(pages=format_pages(pages), questions=listing),
                                system=CHECKER_SYSTEM))
    return {int(v["index"]): (bool(v["supported"]), str(v.get("reason", "")))
            for v in reply.get("verdicts", []) if "index" in v}


def shuffle_options(d: Draft) -> tuple[list[str], int]:
    """Writers tend to put the answer first; shuffle so the position carries no hint."""
    rng = random.Random(d.question)  # deterministic per question
    order = list(range(4))
    rng.shuffle(order)
    return [d.options[i] for i in order], order.index(d.answer_index)


def process_chunk(chunk, cfg: dict, chat) -> list[tuple[Draft, str, str | None]]:
    """Draft and check the questions for one group of pages. Runs in a worker thread (no DB access)."""
    g, models = cfg["generate"], cfg["models"]
    by_page = {p["page"]: p for p in chunk}
    label = f"Pages {chunk[0]['page']}-{chunk[-1]['page']}"
    started = time.monotonic()
    drafts = draft_questions(chunk, g["questions_per_page"] * len(chunk), models["writer"], chat)

    results, to_check = [], []
    for d in drafts:
        page = by_page.get(d.page)
        if page is None:
            results.append((d, "rejected", f"cites page {d.page}, which was not given"))
        elif not quote_on_page(d.quote, page["text"], g["quote_min_score"]):
            results.append((d, "rejected", "quote not found on cited page"))
        else:
            to_check.append(d)

    verdicts = check_questions(chunk, to_check, models["checker"], chat) if to_check else {}
    for i, d in enumerate(to_check):
        ok, reason = verdicts.get(i, (False, "checker gave no verdict"))
        results.append((d, "passed" if ok else "rejected", None if ok else f"checker: {reason}"))
    print(f"{label}: {len(drafts)} drafted, {sum(r[1] == 'passed' for r in results)} passed "
          f"({time.monotonic() - started:.0f}s)")
    return results


def generate(conn, cfg: dict, chat=llm.chat) -> dict:
    pages = [dict(r) for r in conn.execute("SELECT file, page, text FROM pages ORDER BY file, page")]
    if not pages:
        raise SystemExit("No pages stored. Run: python ingest.py data/notes.pdf")

    step = cfg["generate"]["pages_per_call"]
    chunks = [pages[i:i + step] for i in range(0, len(pages), step)]
    workers = cfg["generate"].get("parallel", {}).get("workers", 1)
    print(f"Building questions from {len(pages)} pages in {len(chunks)} groups, {workers} at a time...")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        all_results = list(pool.map(lambda c: process_chunk(c, cfg, chat), chunks))

    conn.execute("DELETE FROM answers")
    conn.execute("DELETE FROM questions")
    stats = {"drafted": 0, "failed_quote": 0, "failed_checker": 0, "passed": 0}
    for chunk, results in zip(chunks, all_results):
        files = {p["page"]: p["file"] for p in chunk}
        for d, status, reason in results:
            stats["drafted"] += 1
            if status == "passed":
                stats["passed"] += 1
            elif reason and reason.startswith("checker"):
                stats["failed_checker"] += 1
            else:
                stats["failed_quote"] += 1
            options, answer = shuffle_options(d)
            conn.execute(
                "INSERT INTO questions (file, page, topic, question, options, answer_index, explanation,"
                " quote, status, reject_reason) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (files.get(d.page, chunk[0]["file"]), d.page, d.topic, d.question, json.dumps(options),
                 answer, d.explanation, d.quote, status, reason),
            )
    conn.commit()
    return stats


if __name__ == "__main__":
    s = generate(db.connect(), db.load_config())
    print(f"\nDrafted {s['drafted']} | failed quote check {s['failed_quote']} | "
          f"failed checker {s['failed_checker']} | passed {s['passed']}")
