"""Small client for NVIDIA's free API (build.nvidia.com): model fallback, disk cache and retries.

The API is OpenAI-compatible. Models are tried in the order given; if one is busy
or times out, the next one is used. Every reply is cached on disk by request
content, so re-running the pipeline never spends requests twice.
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

CACHE_DIR = db.ROOT / "data" / "cache"
TRIES_PER_MODEL = 2


class LLMError(RuntimeError):
    pass


def chat(models: list[str], prompt: str, system: str | None = None,
         cache_dir: Path = CACHE_DIR, cfg: dict | None = None) -> str:
    """Send one prompt and return the reply text, trying `models` in order."""
    settings = (cfg or db.load_config())["llm"]
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]
    key = hashlib.sha256(json.dumps({"models": models, "messages": messages}, sort_keys=True).encode()).hexdigest()
    cached = cache_dir / f"{key}.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))["content"]

    load_dotenv(db.ROOT / ".env")
    api_key = os.environ.get(settings["api_key_env"])
    if not api_key:
        raise LLMError(f"{settings['api_key_env']} is not set. Copy .env.example to .env and add your key.")

    url = settings["base_url"].rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    errors = []
    for model in models:
        body = {"model": model, "messages": messages, "temperature": 0.3, "max_tokens": settings["max_tokens"]}
        for attempt in range(TRIES_PER_MODEL):
            retry_after = None
            try:
                resp = requests.post(url, headers=headers, json=body, timeout=settings["timeout_seconds"])
            except requests.RequestException as exc:
                error = f"{model}: {type(exc).__name__}"
            else:
                if resp.ok:
                    content = (resp.json()["choices"][0]["message"].get("content") or "").strip()
                    if content:
                        cache_dir.mkdir(parents=True, exist_ok=True)
                        cached.write_text(json.dumps({"model": model, "content": content}), encoding="utf-8")
                        return content
                    error = f"{model}: empty reply"
                else:
                    error = f"{model}: HTTP {resp.status_code} {resp.text[:200]}"
                    if resp.status_code in (401, 403):
                        raise LLMError(error)  # bad key: other models won't help
                    if resp.status_code not in (408, 429) and resp.status_code < 500:
                        break  # this model rejects the request; try the next model
                    retry_after = resp.headers.get("Retry-After")
            errors.append(error)
            if attempt < TRIES_PER_MODEL - 1:
                delay = float(retry_after) if retry_after else 10
                print(f"  {error}; retrying in {delay:.0f}s")
                time.sleep(delay)
        print(f"  Moving on from {model}")
    raise LLMError("All models failed: " + " | ".join(errors))


def parse_json(text: str):
    """Pull the JSON object out of a model reply (which may include code fences)."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object in reply")
    return json.loads(text[start:end + 1])
