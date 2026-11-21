# Lyftr Chat

A multi-turn chatbot with React, FastAPI, LiteLLM, the Gemini Developer API, and SQLite. Each reply includes its resolution source, model, latency, and token usage.

## Live URLs

| Deliverable | URL |
| --- | --- |
| Public GitHub repository | [dapinderbhullar/LyftrAI](https://github.com/dapinderbhullar/LyftrAI) |
| Render backend | [lyftrai-backend.onrender.com](https://lyftrai-backend.onrender.com) |
| Vercel frontend | [lyftr-ai-dusky.vercel.app](https://lyftr-ai-dusky.vercel.app/) |

The public API previously passed health and CORS checks. The Gemini migration and voice demo still need live verification.

For a Render Docker service, leave **Root Directory** and **Docker Command** blank, set **Dockerfile Path** to `backend/Dockerfile`, and set **Docker Build Context Directory** to `backend`. Use one worker and `/health` as the health probe. Render provides `PORT`.

Set these values in the backend service's **Environment** settings before deploying the migration:

- `GEMINI_API_KEYS` — two or more Gemini keys separated by commas. Remove the previous provider key variable once the migration is deployed.
- `LLM_MODEL=gemini/gemini-3.5-flash-lite`
- `DATABASE_URL=sqlite:////data/app.db`
- `ALLOWED_ORIGINS=https://lyftr-ai-dusky.vercel.app`
- `ENABLE_FAILURE_SIMULATION=true`

### Gemini keys and quota

Create or select a project in [Google AI Studio](https://aistudio.google.com/apikey) and obtain two Gemini API keys. Store them in the backend environment as one comma-separated value. The order assigns `key_1`, `key_2`, and subsequent IDs. To rotate a key, replace its entry and restart or redeploy the backend.

Google lists free-tier text inference for Gemini 3.5 Flash-Lite in eligible projects. Check the active requests-per-minute, tokens-per-minute, and daily limits in AI Studio. **Keys in the same Google project share its quota.** Failover between those keys does not increase the project's free allowance. [Gemini pricing](https://aistudio.google.com/docs/pricing#gemini-3.5-flash-lite), [rate limits](https://aistudio.google.com/docs/rate-limits), [LiteLLM Gemini configuration](https://docs.litellm.ai/docs/providers/gemini).

For the frontend, import this repository into Vercel on Hobby, select Vite and set the root directory to `frontend`. Set the production variable `VITE_API_URL=https://lyftrai-backend.onrender.com` before deploying. The build command is `npm run build` and output directory is `dist`. Once the frontend URL is assigned, set Render's `ALLOWED_ORIGINS` to that exact HTTPS origin and redeploy the backend. Render Static Sites can use the same Vite settings. The [Render Blueprint](render.yaml) describes a new pair of free Render services.

### Known limitations

Render Free uses an ephemeral filesystem. SQLite history is available while the instance is running and is lost on spin-down, restart, or redeploy. Cold starts can delay the first request. Docker Compose still persists history in its named volume on a durable host. The [Oracle Cloud Always Free migration plan](docs/oracle-migration.md) describes how to preserve SQLite storage without purchasing a Render disk. [Render Free service limits](https://render.com/docs/free).

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
| `GEMINI_API_KEYS` | Server-only comma-separated keys, in attempt order |
| `LLM_MODEL` | Gemini LiteLLM identifier, defaults to `gemini/gemini-3.5-flash-lite` |
| `LITELLM_LOCAL_MODEL_COST_MAP` | Use LiteLLM's bundled model metadata to avoid an external fetch during import. Defaults to `True` in the backend image. |
| `DATABASE_URL` | SQLite file URL, with four slashes for an absolute Unix path |
| `ALLOWED_ORIGINS` | Comma-separated browser origins |
| `ENABLE_FAILURE_SIMULATION` | Enables the request-scoped failure header when set to `true` |
| `VITE_API_URL` | Public backend base URL, embedded during the frontend build |
| `PORT` | Docker backend listen port, defaults to 8000 |

## Design decisions: key fallback, caching, SQLite session storage

The backend tries keys in order through LiteLLM. A provider error or incomplete reply advances to the next key. After both keys fail, a confirmed temporary throttle can receive one retry, with jitter and a delay of at most two seconds. The backend skips that retry if the provider's `Retry-After` requires a longer wait. Billing and quota errors receive no extra retry. The simulation header skips the specified keys and bypasses cache lookup. If no attempt succeeds, the API returns a JSON 503.

Provider failures emit a structured warning with the exception class, status, and a sanitized classification. Recognized provider codes, retry headers, and request IDs are included when available.

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

GitHub Actions built both services and verified SQLite history after a Compose teardown and restart. [Docker workflow run](https://github.com/dapinderbhullar/LyftrAI/actions/runs/44815957530).

See the [requirements audit](docs/audit.md) for verified behavior and deployment checks, and the [timed voice demo script](docs/demo.md) for exact recording commands.


