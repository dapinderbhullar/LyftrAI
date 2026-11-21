import json
import logging
import os
import sqlite3
from contextlib import asynccontextmanager, closing
from datetime import datetime, timezone
from hashlib import sha256
from threading import Lock
from time import perf_counter, sleep
from typing import Annotated

import litellm
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from litellm.caching import Cache
from pydantic import BaseModel, StringConstraints

from provider_errors import diagnose, retry_delay

logger = logging.getLogger(__name__)
litellm.suppress_debug_info = True
DEFAULT_PROMPT = "You are a helpful assistant."
SESSION_LOCKS = [Lock() for _ in range(64)]


def connect(app):
    db = sqlite3.connect(app.state.database, timeout=10)
    db.row_factory = sqlite3.Row
    return db


@asynccontextmanager
async def lifespan(app):
    url = os.getenv("DATABASE_URL", "sqlite:///app.db")
    if not url.startswith("sqlite:///") or not url[10:] or url[10:] == ":memory:":
        raise ValueError("DATABASE_URL must point to a SQLite file")
    app.state.database = url[10:]
    app.state.keys = [key.strip() for key in os.getenv("LLM_API_KEYS", "").split(",") if key.strip()]
    app.state.model = os.getenv("LLM_MODEL", "openai/gpt-4o-mini")
    app.state.simulate = os.getenv("ENABLE_FAILURE_SIMULATION", "").lower() == "true"
    app.state.cache = Cache(type="local", ttl=3600)
    with closing(connect(app)) as db, db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, system_prompt TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS history ON messages(session_id, id);
        """)
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv(
        "ALLOWED_ORIGINS", "http://localhost:3000"
    ).split(",") if origin.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Simulate-Failure"],
)


@app.exception_handler(Exception)
async def internal_error(request, exc):
    logger.error("Request failed: %s", type(exc).__name__)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


class ChatRequest(BaseModel):
    session_id: Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"\S")]
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    system_prompt: str | None = None


def history(db, session_id):
    return db.execute(
        "SELECT role, content, metadata FROM messages WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()


@app.get("/health")
def health():
    try:
        with closing(connect(app)) as db:
            db.execute("SELECT id FROM messages LIMIT 1").fetchone()
    except sqlite3.Error:
        raise HTTPException(503, "database unavailable") from None
    if len(app.state.keys) < 2:
        raise HTTPException(503, "key pool unavailable")
    return {"status": "ok", "keys_configured": len(app.state.keys), "cache_enabled": True}


@app.get("/sessions/{session_id}/messages")
def session_messages(session_id: str):
    with closing(connect(app)) as db:
        rows = history(db, session_id)
    if not rows:
        raise HTTPException(404, "session not found")
    messages = []
    for row in rows:
        message = {"role": row["role"], "content": row["content"]}
        if row["metadata"] is not None:
            message["metadata"] = json.loads(row["metadata"])
        messages.append(message)
    return {"session_id": session_id, "messages": messages}


def simulated_failures(request):
    failures = set()
    if app.state.simulate:
        for pair in request.headers.get("X-Simulate-Failure", "").split(","):
            key_id, _, status = pair.strip().partition("=")
            if status in {"429", "500", "502", "503"}:
                failures.add(key_id)
    return failures


def infer(messages, failures):
    state = app.state
    provider_args = {"model": state.model, "messages": messages}
    payload = json.dumps(provider_args, sort_keys=True, separators=(",", ":"))
    cache_key = sha256(payload.encode()).hexdigest()
    # An injected error exercises live routing even when this prompt is already cached.
    if not failures:
        cached = state.cache.get_cache(cache_key=cache_key)
        if cached is not None:
            return cached, "LLM_CACHE", None, 0

    def attempt(key, key_id):
        try:
            response = litellm.completion(
                **provider_args, api_key=key, caching=False, num_retries=0, timeout=15
            )
            reply = response.choices[0].message.content
            usage = response.usage
            if (
                not reply or not reply.strip() or usage is None
                or usage.prompt_tokens is None or usage.completion_tokens is None
            ):
                logger.warning("Provider %s returned an incomplete response", key_id)
                return None, None
            result = {
                "reply": reply,
                "input_tokens": usage.prompt_tokens,
                "output_tokens": usage.completion_tokens,
            }
        except Exception as exc:
            protected = (*state.keys, *(message["content"] for message in messages))
            diagnostic, retry_after = diagnose(exc, state.model, protected)
            logger.warning("Provider %s failed %s", key_id, json.dumps(diagnostic))
            delay = retry_delay(retry_after) if diagnostic["classification"] == "temporary_rate_limit" else None
            return None, delay
        state.cache.add_cache(json.dumps(result), cache_key=cache_key)
        return result, None

    retry = None
    for index, key in enumerate(state.keys, start=1):
        key_id = f"key_{index}"
        if "*" in failures or key_id in failures:
            continue
        result, delay = attempt(key, key_id)
        if result is not None:
            return result, "LIVE_INFERENCE", key_id, index - 1
        if retry is None and delay is not None and not failures:
            retry = (key, key_id, delay)

    if retry is not None:
        key, key_id, delay = retry
        sleep(delay)
        result, _ = attempt(key, key_id)
        if result is not None:
            return result, "LIVE_INFERENCE", key_id, len(state.keys) - 1
    raise HTTPException(503, "all providers unavailable")


@app.post("/chat")
def chat(body: ChatRequest, request: Request):
    started = perf_counter()
    session_id = body.session_id
    with SESSION_LOCKS[hash(session_id) % len(SESSION_LOCKS)], closing(connect(app)) as db:
        session = db.execute("SELECT system_prompt FROM sessions WHERE id = ?", (session_id,)).fetchone()
        prompt = body.system_prompt
        if prompt is None:
            prompt = session["system_prompt"] if session else DEFAULT_PROMPT
        messages = [{"role": "system", "content": prompt}]
        messages.extend({"role": row["role"], "content": row["content"]} for row in history(db, session_id))
        messages.append({"role": "user", "content": body.message})
        result, source, key_id, attempts = infer(messages, simulated_failures(request))
        reply = result["reply"]
        metadata = {
            "resolution_source": source,
            "model": app.state.model,
            "latency_ms": int((perf_counter() - started) * 1000),
            "input_tokens": result["input_tokens"],
            "output_tokens": result["output_tokens"],
            "key_id": key_id,
            "fallback_attempts": attempts,
        }
        created_at = datetime.now(timezone.utc).isoformat()
        with db:
            db.execute(
                "INSERT INTO sessions VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET system_prompt = excluded.system_prompt",
                (session_id, prompt),
            )
            db.executemany(
                "INSERT INTO messages(session_id, role, content, metadata, created_at) VALUES (?, ?, ?, ?, ?)",
                [
                    (session_id, "user", body.message, None, created_at),
                    (session_id, "assistant", reply, json.dumps(metadata), created_at),
                ],
            )
    return {"session_id": session_id, "reply": reply, "metadata": metadata}
