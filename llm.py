"""Small OpenRouter client: model fallback list, disk cache and retries.

Every response is cached on disk by request content, so re-running the
pipeline never spends free-tier requests twice.
"""
import hashlib
import json
import os
import re
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

import db

URL = "https://openrouter.ai/api/v1/chat/completions"
CACHE_DIR = db.ROOT / "data" / "cache"
MAX_TRIES = 4


class LLMError(RuntimeError):
    pass


def chat(models: list[str], prompt: str, system: str | None = None,
         cache_dir: Path = CACHE_DIR) -> str:
    """Send one prompt. OpenRouter tries `models` in order if one is busy."""
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]
    body = {"models": models, "messages": messages, "temperature": 0.3}

    key = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    cached = cache_dir / f"{key}.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))["content"]

    load_dotenv(db.ROOT / ".env")
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise LLMError("OPENROUTER_API_KEY is not set. Copy .env.example to .env and add your key.")

    headers = {"Authorization": f"Bearer {api_key}", "X-Title": "Between Heats"}
    for attempt in range(MAX_TRIES):
        retry_after = None
        try:
            resp = requests.post(URL, headers=headers, json=body, timeout=180)
        except requests.RequestException as exc:
            error = f"network error: {exc}"
        else:
            data = resp.json() if resp.content else {}
            if resp.ok and "error" not in data:
                content = (data["choices"][0]["message"].get("content") or "").strip()
                if not content:
                    raise LLMError(f"Empty reply from {data.get('model')}")
                cache_dir.mkdir(parents=True, exist_ok=True)
                cached.write_text(json.dumps({"model": data.get("model"), "content": content}),
                                  encoding="utf-8")
                return content
            error = f"HTTP {resp.status_code}: {data.get('error', resp.text[:200])}"
            if resp.status_code not in (408, 429) and resp.status_code < 500:
                raise LLMError(error)  # bad request or bad key: retrying won't help
            retry_after = resp.headers.get("Retry-After")
        if attempt < MAX_TRIES - 1:
            delay = float(retry_after) if retry_after else 5 * 2 ** attempt
            print(f"  OpenRouter busy ({error}); retrying in {delay:.0f}s")
            time.sleep(delay)
    raise LLMError(f"Gave up after {MAX_TRIES} tries: {error}")


def parse_json(text: str):
    """Pull the JSON object out of a model reply (which may include code fences)."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object in reply")
    return json.loads(text[start:end + 1])
