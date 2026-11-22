import json

import pytest

import llm


class FakeResponse:
    def __init__(self, status, payload, headers=None):
        self.status_code, self._payload, self.headers = status, payload, headers or {}
        self.ok = status < 400
        self.content = json.dumps(payload).encode()
        self.text = self.content.decode()

    def json(self):
        return self._payload


def ok(content):
    return FakeResponse(200, {"model": "m", "choices": [{"message": {"content": content}}]})


def test_retries_rate_limit_then_caches(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    replies = [FakeResponse(429, {"error": "rate"}, {"Retry-After": "1"}), ok("hello")]
    calls = []
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: calls.append(k["json"]) or replies.pop(0))

    assert llm.chat(["a:free", "b:free"], "hi", cache_dir=tmp_path) == "hello"
    assert calls[0]["models"] == ["a:free", "b:free"]  # fallback list is sent
    # Second identical call is served from the cache: no new request.
    assert llm.chat(["a:free", "b:free"], "hi", cache_dir=tmp_path) == "hello"
    assert len(calls) == 2


def test_bad_key_fails_fast(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: FakeResponse(401, {"error": "bad key"}))
    with pytest.raises(llm.LLMError, match="401"):
        llm.chat(["a:free"], "hi", cache_dir=tmp_path)


def test_parse_json_strips_code_fences():
    assert llm.parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert llm.parse_json('Sure! {"a": [1, 2]} hope that helps') == {"a": [1, 2]}
