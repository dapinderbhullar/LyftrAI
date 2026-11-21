import json
import socket
from contextlib import closing
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from app import DEFAULT_MODEL, app, litellm
from provider_errors import diagnose


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + (tmp_path / "test.db").as_posix())
    monkeypatch.setenv("GEMINI_API_KEYS", "fake-one,fake-two")
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


@pytest.mark.parametrize("fail_first_key", [False, True])
def test_gemini_adapter_sends_configured_key_and_maps_usage(client, monkeypatch, caplog, fail_first_key):
    keys = []

    def send_to_google(_client, request, **kwargs):
        assert request.url.host == "generativelanguage.googleapis.com"
        assert request.url.path.endswith("/models/gemini-3.5-flash-lite:generateContent")
        key = request.headers["x-goog-api-key"]
        keys.append(key)
        body = json.loads(request.content)
        assert body["contents"][-1]["parts"][0]["text"] == "Hello"
        if fail_first_key and key == "fake-one":
            return httpx.Response(429, request=request, json={"error": {
                "code": 429, "status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded.",
                "details": [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                             "violations": [{"quotaId": "GenerateRequestsPerDay"}]}],
            }})
        return httpx.Response(200, request=request, json={
            "candidates": [{"content": {"role": "model", "parts": [{"text": "Hello back"}]},
                            "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 2, "totalTokenCount": 7},
        })

    monkeypatch.setattr(httpx.Client, "send", send_to_google)
    response = send(client, "gemini-transport")
    assert response.status_code == 200
    assert response.json()["reply"] == "Hello back"
    metadata = response.json()["metadata"]
    assert metadata["model"] == DEFAULT_MODEL
    assert metadata["key_id"] == ("key_2" if fail_first_key else "key_1")
    assert metadata["fallback_attempts"] == int(fail_first_key)
    assert keys == (["fake-one", "fake-two"] if fail_first_key else ["fake-one"])
    if fail_first_key:
        assert '"classification": "insufficient_quota"' in caplog.text
        assert "fake-one" not in caplog.text and "fake-two" not in caplog.text
    assert (metadata["input_tokens"], metadata["output_tokens"]) == (5, 2)


def test_rejects_non_gemini_model(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "other/model")
    with pytest.raises(ValueError, match="gemini/ model identifier"):
        with TestClient(app):
            pytest.fail("Unexpected startup")


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


def test_provider_exception(client, provider, monkeypatch):
    sleep = Mock()
    monkeypatch.setattr("app.sleep", sleep)
    complete = provider.side_effect

    def rate_limited(**kwargs):
        if kwargs["api_key"] == "fake-one":
            raise rate_limit_error("rate_limit_exceeded", "RPM limit", {"Retry-After": "1"})
        return complete(**kwargs)

    provider.side_effect = rate_limited
    result = send(client, "fallback").json()["metadata"]
    assert result["key_id"] == "key_2"
    assert result["fallback_attempts"] == 1
    sleep.assert_not_called()


def rate_limit_error(code, message, headers=None):
    upstream = httpx.Response(
        429, request=httpx.Request("POST", "https://example.test"),
        json={"error": {"code": code, "type": code, "message": message}},
        headers=headers,
    )
    return litellm.RateLimitError(message, "gemini", "test", response=upstream)


@pytest.mark.parametrize(("code", "message", "expected"), [
    ("rate_limit_exceeded", "Rate limit reached on tokens per minute", "temporary_rate_limit"),
    ("insufficient_quota", "Check your plan and billing details", "insufficient_quota"),
    ("quota_exceeded", "RPM limit also applies", "insufficient_quota"),
    ("billing_hard_limit_reached", "Billing hard limit reached", "spending_limit"),
    ("budget_exceeded", "Project budget exceeded", "spending_limit"),
    ("model_not_found", "The requested model does not exist", "model_access"),
    (None, "Too many requests", "unclassified_rate_limit"),
])
def test_provider_error_classification(code, message, expected):
    diagnostic, _ = diagnose(rate_limit_error(code, message), "gemini/test", [])
    assert diagnostic["classification"] == expected
    assert diagnostic["http_status"] == 429


@pytest.mark.parametrize(("status", "error_status", "detail", "expected", "delay"), [
    (429, "RESOURCE_EXHAUSTED", {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
        "violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]},
        "temporary_rate_limit", 1.25),
    (429, "RESOURCE_EXHAUSTED", {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
        "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]},
        "insufficient_quota", 1.25),
    (429, "RESOURCE_EXHAUSTED", {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
        "violations": [{"quotaId": "GenerateRequestsPerMinute", "quotaValue": "0"}]},
        "insufficient_quota", 1.25),
    (429, "RESOURCE_EXHAUSTED", {}, "unclassified_rate_limit", None),
    (400, "FAILED_PRECONDITION", {"@type": "type.googleapis.com/google.rpc.ErrorInfo",
        "reason": "BILLING_DISABLED"}, "spending_limit", None),
    (400, "INVALID_ARGUMENT", {"@type": "type.googleapis.com/google.rpc.ErrorInfo",
        "reason": "API_KEY_INVALID"}, "invalid_key", None),
    (401, "UNAUTHENTICATED", {}, "authentication", None),
    (404, "NOT_FOUND", {}, "model_access", None),
    (503, "UNAVAILABLE", {}, "server_error", None),
    (400, "INVALID_ARGUMENT", {}, "other", None),
])
def test_google_rpc_error_details(status, error_status, detail, expected, delay):
    details = [detail]
    if delay is not None:
        details.append({"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "1.25s"})
    response = httpx.Response(status, json={"error": {
        "code": status, "status": error_status, "details": details,
    }})
    diagnostic, retry_after = diagnose(SimpleNamespace(response=response), DEFAULT_MODEL, [])
    assert diagnostic["classification"] == expected
    assert diagnostic["http_status"] == status
    assert diagnostic["error_code"] == str(status)
    assert diagnostic["error_type"] == error_status
    assert retry_after == delay


def test_provider_logs_only_safe_diagnostics(client, provider, caplog, monkeypatch):
    sleep = Mock()
    monkeypatch.setattr("app.sleep", sleep)
    provider.side_effect = rate_limit_error("insufficient_quota", "fake-one private prompt", {
        "Retry-After": "1",
        "X-RateLimit-Remaining-Requests": "0",
        "X-RateLimit-Reset-Tokens": "1m2.5s",
        "X-Request-Id": "req_example123",
        "Authorization": "Bearer fake-two",
        "Set-Cookie": "private cookie",
        "X-RateLimit-Remaining-Tokens": "private prompt",
    })
    response = send(client, "diagnostics", "private prompt")
    assert response.status_code == 503
    assert provider.call_count == 2
    sleep.assert_not_called()
    assert all(value not in caplog.text for value in (
        "fake-one", "fake-two", "private prompt", "private cookie", "Authorization",
    ))
    warning = next(record.message for record in caplog.records if record.message.startswith("Provider key_1 failed "))
    diagnostic = json.loads(warning.removeprefix("Provider key_1 failed "))
    assert diagnostic == {
        "exception": "RateLimitError", "http_status": 429, "provider": "gemini",
        "classification": "insufficient_quota", "error_code": "insufficient_quota",
        "error_type": "insufficient_quota", "retry_after": "1", "request_id": "req_example123",
        "provider_message_summary": "Provider indicated insufficient quota or exhausted credits.",
        "rate_limit_headers": {
            "x-ratelimit-remaining-requests": "0", "x-ratelimit-reset-tokens": "1m2.5s",
        },
    }


def test_provider_does_not_log_prompt_disguised_as_request_id(client, provider, caplog):
    prompt = "req_private123"
    provider.side_effect = rate_limit_error("insufficient_quota", prompt, {"X-Request-Id": prompt})
    assert send(client, "echoed-header", prompt).status_code == 503
    assert prompt not in caplog.text


@pytest.mark.parametrize(("retry_after", "retry_expected"), [("1", True), ("12", False)])
def test_transient_retry_only_after_failover(client, provider, monkeypatch, retry_after, retry_expected):
    sleep = Mock()
    monkeypatch.setattr("app.sleep", sleep)
    monkeypatch.setattr("provider_errors.uniform", lambda low, high: 0.1)
    complete = provider.side_effect
    temporary = rate_limit_error("rate_limit_exceeded", "RPM limit", {"Retry-After": retry_after})
    quota = rate_limit_error("insufficient_quota", "Insufficient quota")
    provider.side_effect = [temporary, quota, complete(messages=[{"content": "Hello"}])]
    response = send(client, "retry")
    attempted_keys = [call.kwargs["api_key"] for call in provider.call_args_list]
    if retry_expected:
        assert attempted_keys == ["fake-one", "fake-two", "fake-one"]
        sleep.assert_called_once_with(1.1)
        assert response.status_code == 200
        assert response.json()["metadata"]["key_id"] == "key_1"
    else:
        assert attempted_keys == ["fake-one", "fake-two"]
        sleep.assert_not_called()
        assert response.status_code == 503


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
    monkeypatch.setenv("GEMINI_API_KEYS", "fake-one,fake-two")
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
    monkeypatch.setenv("GEMINI_API_KEYS", "fake-one,fake-two")
    monkeypatch.setenv("ENABLE_FAILURE_SIMULATION", "false")
    with TestClient(app) as client:
        result = send(client, "ignored", failure="*=429")
        assert result.status_code == 200
        assert result.json()["metadata"]["key_id"] == "key_1"


def test_health_requires_two_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + (tmp_path / "single.db").as_posix())
    monkeypatch.setenv("GEMINI_API_KEYS", "one-key")
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
    monkeypatch.setenv("GEMINI_API_KEYS", "fake-one,fake-two")
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
