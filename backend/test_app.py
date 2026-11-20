import socket
from contextlib import closing
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from app import app, litellm


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + (tmp_path / "test.db").as_posix())
    monkeypatch.setenv("LLM_API_KEYS", "fake-one,fake-two")
    monkeypatch.setenv("ENABLE_FAILURE_SIMULATION", "true")
    with TestClient(app) as client:
        yield client


@pytest.fixture
def provider(monkeypatch):
    def complete(*, messages, **kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Answer: " + messages[-1]["content"]))],
            usage=SimpleNamespace(prompt_tokens=len(messages) * 5, completion_tokens=3),
        )

    mock = Mock(side_effect=complete)
    monkeypatch.setattr(litellm, "completion", mock)
    return mock


def send(client, session, text="Hello", failure=None, **options):
    headers = {"X-Simulate-Failure": failure} if failure else {}
    return client.post("/chat", json={"session_id": session, "message": text, **options}, headers=headers)


def test_cache_and_history(client, provider):
    assert client.get("/health").json() == {
        "status": "ok", "keys_configured": 2, "cache_enabled": True,
    }
    live = send(client, "first", " Hello ").json()
    hit = send(client, "second").json()
    assert live["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert hit["reply"] == live["reply"]
    assert hit["metadata"] == {
        **live["metadata"], "resolution_source": "LLM_CACHE",
        "key_id": None, "fallback_attempts": 0, "latency_ms": hit["metadata"]["latency_ms"],
    }
    assert provider.call_count == 1
    follow_up = send(client, "first").json()
    assert follow_up["metadata"]["input_tokens"] == 20
    assert [message["role"] for message in provider.call_args.kwargs["messages"]] == [
        "system", "user", "assistant", "user",
    ]
    assert send(client, "third", "Different").json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    history = client.get("/sessions/first/messages").json()["messages"]
    assert len(history) == 4
    assert history[0] == {"role": "user", "content": "Hello"}
    assert history[1]["metadata"] == live["metadata"]


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_simulated_failover(client, provider, status):
    send(client, "prime")
    response = send(client, "fallback", failure=f"key_1={status}")
    assert response.status_code == 200
    assert response.json()["metadata"]["key_id"] == "key_2"
    assert response.json()["metadata"]["fallback_attempts"] == 1
    assert provider.call_args.kwargs["api_key"] == "fake-two"
    assert send(client, "normal", "Uncached").json()["metadata"]["key_id"] == "key_1"


def test_provider_exception(client, provider):
    complete = provider.side_effect

    def rate_limited(**kwargs):
        if kwargs["api_key"] == "fake-one":
            raise litellm.RateLimitError(message="rate limited", model="test", llm_provider="openai")
        return complete(**kwargs)

    provider.side_effect = rate_limited
    result = send(client, "fallback").json()["metadata"]
    assert result["key_id"] == "key_2"
    assert result["fallback_attempts"] == 1


def test_total_failure_and_invalid_input(client, provider):
    send(client, "existing")
    assert send(client, "existing", failure="*=429").json() == {"detail": "all providers unavailable"}
    failed = send(client, "new", failure="key_1=429,key_2=500")
    assert failed.status_code == 503
    assert client.get("/sessions/new/messages").status_code == 404
    assert len(client.get("/sessions/existing/messages").json()["messages"]) == 2
    for session, message in [("", "Hi"), ("a" * 129, "Hi"), ("existing", " "), ("existing", "x" * 4001)]:
        assert send(client, session, message).status_code == 422
    assert client.post("/chat", content="{", headers={"Content-Type": "application/json"}).status_code == 422
    assert provider.call_count == 1


def test_prompt_is_part_of_cache_key_and_persists(client, provider):
    send(client, "normal")
    result = send(client, "custom", system_prompt="Be brief").json()
    assert result["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    send(client, "custom", "Again")
    assert provider.call_args.kwargs["messages"][0] == {"role": "system", "content": "Be brief"}


@pytest.mark.parametrize("missing", ["session_id", "message"])
def test_required_fields(client, provider, missing):
    payload = {"session_id": "validation", "message": "Hello"}
    del payload[missing]
    response = client.post("/chat", json=payload)
    assert response.status_code == 422
    assert "detail" in response.json()
    assert client.get("/sessions/validation/messages").status_code == 404
    provider.assert_not_called()


def test_distinct_histories_do_not_share_context_or_cache(client, provider):
    send(client, "left", "My name is Ada.")
    send(client, "right", "My name is Grace.")
    assert send(client, "left", "Who am I?").json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    right = send(client, "right", "Who am I?").json()
    assert right["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    context = provider.call_args.kwargs["messages"]
    assert context[1]["content"] == "My name is Grace."
    assert all("Ada" not in message["content"] for message in context)


def test_persistence_after_new_lifespan(tmp_path, monkeypatch, provider):
    path = tmp_path / "persistent.db"
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + path.as_posix())
    monkeypatch.setenv("LLM_API_KEYS", "fake-one,fake-two")
    with TestClient(app) as first:
        response = send(first, "saved", system_prompt="Private system prompt")
        assert response.status_code == 200
    with TestClient(app) as restarted:
        history = restarted.get("/sessions/saved/messages").json()["messages"]
        assert [message["role"] for message in history] == ["user", "assistant"]
        assert "Private system prompt" not in str(history)
        assert send(restarted, "saved", "Follow-up").status_code == 200
        assert provider.call_args.kwargs["messages"][0]["content"] == "Private system prompt"


def test_simulation_disabled(tmp_path, monkeypatch, provider):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + (tmp_path / "disabled.db").as_posix())
    monkeypatch.setenv("LLM_API_KEYS", "fake-one,fake-two")
    monkeypatch.setenv("ENABLE_FAILURE_SIMULATION", "false")
    with TestClient(app) as client:
        result = send(client, "ignored", failure="*=429")
        assert result.status_code == 200
        assert result.json()["metadata"]["key_id"] == "key_1"


def test_health_requires_two_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + (tmp_path / "single.db").as_posix())
    monkeypatch.setenv("LLM_API_KEYS", "one-key")
    with TestClient(app) as client:
        assert client.get("/health").status_code == 503


def test_cors(client):
    headers = {
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-simulate-failure",
    }
    allowed = client.options("/chat", headers=headers)
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == headers["Origin"]
    denied = client.options("/chat", headers={**headers, "Origin": "https://invalid.example"})
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers


def test_endpoints_over_tcp(tmp_path, monkeypatch, provider):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + (tmp_path / "http.db").as_posix())
    monkeypatch.setenv("LLM_API_KEYS", "fake-one,fake-two")
    monkeypatch.setenv("ENABLE_FAILURE_SIMULATION", "true")
    ready = Event()

    class TestServer(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets)
            ready.set()

    server = TestServer(uvicorn.Config(app, log_level="warning"))
    with closing(socket.socket()) as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            assert ready.wait(10) and server.started
            with httpx.Client(base_url=f"http://127.0.0.1:{port}") as client:
                assert client.get("/health").status_code == 200
                live = send(client, "live", failure="key_1=429")
                assert live.status_code == 200
                assert live.json()["metadata"]["key_id"] == "key_2"
                hit = send(client, "cached")
                assert hit.json()["metadata"]["resolution_source"] == "LLM_CACHE"
                assert hit.json()["reply"] == live.json()["reply"]
                assert send(client, "failed", failure="*=429").status_code == 503
                assert client.get("/sessions/failed/messages").status_code == 404
                assert len(client.get("/sessions/live/messages").json()["messages"]) == 2
        finally:
            server.should_exit = True
            thread.join(timeout=10)
