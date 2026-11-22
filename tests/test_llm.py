import json

import pytest
import requests

import db
import llm

CFG = db.load_config()


class FakeResponse:
    def __init__(self, status, payload, headers=None):
        self.status_code, self._payload, self.headers = status, payload, headers or {}
        self.ok = status < 400
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def ok(content):
    return FakeResponse(200, {"choices": [{"message": {"content": content}}]})


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test")
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)


def fake_post(replies, calls):
    def post(url, headers, json, timeout):
        calls.append(json["model"])
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
    return post


def test_falls_back_to_next_model_then_caches(tmp_path, monkeypatch, env):
    calls = []
    replies = [FakeResponse(503, {"error": "busy"}), requests.Timeout(), ok("hello")]
    monkeypatch.setattr(llm.requests, "post", fake_post(replies, calls))

    assert llm.chat(["a", "b"], "hi", cache_dir=tmp_path, cfg=CFG) == "hello"
    assert calls == ["a", "a", "b"]  # two tries on a, then b
    # Same request again is served from the cache: no new call.
    assert llm.chat(["a", "b"], "hi", cache_dir=tmp_path, cfg=CFG) == "hello"
    assert len(calls) == 3


def test_retry_after_429(tmp_path, monkeypatch, env):
    calls = []
    replies = [FakeResponse(429, {"error": "rate"}, {"Retry-After": "2"}), ok("done")]
    monkeypatch.setattr(llm.requests, "post", fake_post(replies, calls))
    assert llm.chat(["a"], "hi", cache_dir=tmp_path, cfg=CFG) == "done"
    assert calls == ["a", "a"]


def test_bad_key_fails_fast(tmp_path, monkeypatch, env):
    calls = []
    monkeypatch.setattr(llm.requests, "post", fake_post([FakeResponse(401, {"error": "bad key"})], calls))
    with pytest.raises(llm.LLMError, match="401"):
        llm.chat(["a", "b"], "hi", cache_dir=tmp_path, cfg=CFG)
    assert calls == ["a"]


def test_parse_json_strips_code_fences():
    assert llm.parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert llm.parse_json('Sure! {"a": [1, 2]} hope that helps') == {"a": [1, 2]}
