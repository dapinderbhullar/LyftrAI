# Lyftr Chat

A multi-turn chatbot with React, FastAPI, LiteLLM and SQLite. The browser sends one message at a time, the API restores session context, and each assistant reply includes its resolution source, model, latency and token usage.

## Live URLs

| Deliverable | URL |
| --- | --- |
| Frontend | Pending deployment |
| Backend | Pending deployment |
| Public GitHub repository | [dapinderbhullar/LyftrAI](https://github.com/dapinderbhullar/LyftrAI) |
| Voice demo | Pending recording |

Deploy the backend Dockerfile on a Docker host with a persistent disk mounted at `/data`. Set `LLM_API_KEYS` to two working keys authorized for the configured `LLM_MODEL`. Set `DATABASE_URL=sqlite:////data/app.db` and `ENABLE_FAILURE_SIMULATION=true`. Use one Uvicorn worker and one replica. Use `/health` for the health check. Deploy the frontend from `frontend/` with `npm install && npm run build` and publish `dist/`. Set `VITE_API_URL` to the public HTTPS backend URL before the frontend build and set the backend's `ALLOWED_ORIGINS` to the exact HTTPS frontend origin.

To use the supplied [Render Blueprint](render.yaml), connect this repository in the Render dashboard and select **New → Blueprint**. Review the paid backend plan and persistent disk before applying. Set `LLM_API_KEYS` in the dashboard. Copy the two actual service URLs from Render, then set `ALLOWED_ORIGINS` on the backend and `VITE_API_URL` on the frontend and redeploy. [Render Blueprint reference](https://render.com/docs/blueprint-spec), [persistent disks](https://render.com/docs/disks).

## Run locally: with Docker and without

Copy `.env.example` to `.env` and fill in two provider keys for the same LiteLLM model. Docker Compose reads this file automatically. Run `make up` and open http://localhost:3000. The backend listens on http://localhost:8000. Run `make down` to stop both containers. The named volume persists across restarts. On machines without Make, use `docker compose up --build -d` and `docker compose down`.

Without Docker, use Python 3.12 and Node.js 22. Export the backend settings from `.env.example` into your shell and change `DATABASE_URL` to `sqlite:///app.db` for a writable local file. In separate terminals:

```sh
cd backend
python -m venv .venv
# Activate the environment for your shell before continuing.
python -m pip install -r requirements.txt
python -m uvicorn app:app --port 8000
```

```sh
cd frontend
npm install
npm run dev
```

Vite uses `http://localhost:8000` by default. Set `VITE_API_URL` in the frontend process environment for a different backend.

| Variable | Purpose |
| --- | --- |
| `LLM_API_KEYS` | Server-only comma-separated keys, in attempt order |
| `LLM_MODEL` | LiteLLM provider and model identifier |
| `DATABASE_URL` | SQLite file URL, with four slashes for an absolute Unix path |
| `ALLOWED_ORIGINS` | Comma-separated browser origins |
| `ENABLE_FAILURE_SIMULATION` | Enables the request-scoped failure header when set to `true` |
| `VITE_API_URL` | Public backend base URL, embedded during the frontend build |
| `PORT` | Docker backend listen port, defaults to 8000 |

## Design decisions: key fallback, caching, SQLite session storage

The backend attempts each key in order through LiteLLM with provider retries disabled. Provider exceptions and incomplete responses advance to the next key. The simulation header skips the specified keys before any provider call and bypasses cache lookup for that request. Exhausting the pool returns a JSON 503.

LiteLLM's built-in in-memory cache stores reply text and per-call usage for one hour. The key includes the LiteLLM model and complete ordered provider conversation. Session IDs and credentials stay out of the key. The cache resets on backend restart.

SQLite keeps history and session system prompts. The server reads history before inference and commits both messages together after success. A bounded set of locks serializes overlapping writes within the single backend process. SQLite WAL mode allows reads during writes. Each page load creates a fresh client session ID.

## Verification: how to see failover, cache hits and per-message token usage

| Endpoint | Contract |
| --- | --- |
| `GET /health` | Returns `status`, `keys_configured` and `cache_enabled`. Returns 503 when the database or key pool is unavailable. |
| `POST /chat` | Accepts `session_id`, `message` and optional `system_prompt`. Returns `session_id`, `reply` and `metadata` with `resolution_source`, `model`, `latency_ms`, `input_tokens`, `output_tokens`, `key_id` and `fallback_attempts`. Invalid input gives 422. Exhausting the key pool gives 503 with `detail: "all providers unavailable"`. |
| `GET /sessions/{session_id}/messages` | Returns `session_id` and ordered `messages` with role, content and assistant metadata. Unknown sessions give 404 with `detail: "session not found"`. |

Set `BASE` to your backend URL and use fresh session IDs when repeating the commands. Run with failure simulation enabled.

```sh
BASE=http://localhost:8000
curl -sS "$BASE/health"

curl -sS "$BASE/chat" -H 'Content-Type: application/json' \
  -d '{"session_id":"demo-live","message":"I have a dog named Ada."}'
curl -sS "$BASE/chat" -H 'Content-Type: application/json' \
  -d '{"session_id":"demo-cache","message":"I have a dog named Ada."}'
curl -sS "$BASE/chat" -H 'Content-Type: application/json' -H 'X-Simulate-Failure: key_1=429' \
  -d '{"session_id":"demo-live","message":"What is my dog named?"}'

curl -sS "$BASE/sessions/demo-live/messages"

curl -si "$BASE/chat" -H 'Content-Type: application/json' -H 'X-Simulate-Failure: *=429' \
  -d '{"session_id":"demo-failed","message":"Hello"}'
curl -si "$BASE/sessions/demo-failed/messages"
```

Expect live inference followed by an identical cached reply with a null key ID and the same token counts. The follow-up should use `key_2` with one fallback attempt and recall Ada. The final commands should return 503 and 404 respectively. In the UI, send a message and reload the page before repeating it to compare source, latency and per-message token usage across sessions.

Run backend tests from `backend/` with `python -m pip install -r requirements.txt pytest httpx` and `python -m pytest -q`. The tests replace the provider call while using real SQLite and LiteLLM's cache.

From `frontend/`, run `npm ci`, `npx playwright install chromium` and `npx playwright test` for the browser suite. To use installed Edge, set `PLAYWRIGHT_BROWSER_CHANNEL=msedge` before running the suite. `npm run build` verifies the production bundle.

Verification passed for 16 backend tests, 3 Edge browser tests, and the production bundle. GitHub Actions built and started both Docker services and verified SQLite history after a Compose teardown and restart. Provider-backed inference and the public deployment are pending. [Docker workflow run](https://github.com/dapinderbhullar/LyftrAI/actions/runs/44811950958).

See the [requirements audit](docs/audit.md) for verified behavior and deployment checks, and the [timed voice demo script](docs/demo.md) for exact recording commands.

## Setup Used: your editor and AI tools

Codex desktop and PowerShell were used to implement the project.

## Bonus features (if any): what you added beyond the requirements and why

The API supports a session-level system prompt so callers can customize assistant behavior. The UI provides example prompts and lets users restore a failed message to the composer.
