# Assignment requirements audit

| Requirement | Classification | Evidence or remaining check |
| --- | --- | --- |
| React chat and exact test IDs | Fully implemented and verified | Edge tests cover composer, keyboard control, pending and duplicate-submit behavior, exact assistant metadata, recovery from 503, and fresh session IDs. Production build passed. |
| Responsive layout, empty state and scroll | Fully implemented and verified | The Edge suite covers a 390 px mobile viewport, prompt shortcuts, automatic scrolling, and a readable 422 error. |
| Three API paths, validation and error bodies | Fully implemented and verified | Backend tests cover TCP requests, health and missing key pool, 422, 404, 503, and ordered history. |
| SQLite schema, independent sessions, prompt privacy and persistence | Fully implemented and verified | Tests use real SQLite files and reopen the database across two application lifespans. |
| Docker named volume and restart | Fully implemented and verified | GitHub Actions mounted the volume at /data and read a seeded SQLite history row over HTTP after make down and make up. |
| Multi-turn model context | Fully implemented and verified | Gemini recalled a unique notebook name in a follow-up. The production history endpoint returned both turns in order. |
| LiteLLM response cache | Fully implemented and verified | Tests use LiteLLM's local cache and cover identical cross-session replies, stored usage, different messages and histories, and prompt-specific keys. |
| Cache versus inference latency | Fully implemented and verified | A production cache hit took 1 ms of server time versus 655 ms for the matching Gemini request. Reply text and token counts matched. |
| Two-key failover and test hook | Fully implemented and verified | Production returned a live response using key_2 after a simulated key_1 failure. Simulated failure of both keys returned 503 and left no message history. |
| Request-local token metadata | Fully implemented and verified | Production returned input and output counts for both live and cached replies. |
| CORS and build-time API URL | Fully implemented and verified | The Vercel bundle targets Render. Production preflight accepted the Vercel origin. |
| Multi-stage images and Make targets | Fully implemented and verified | The Linux GitHub runner built both images and ran make up and make down. [Docker workflow run](https://github.com/dapinderbhullar/LyftrAI/actions/runs/44811950958). |
| Environment and secret hygiene | Fully implemented and verified | Placeholder sample configuration, secret ignore rules and server-only key handling. |
| Public hosting | Fully implemented and verified | Vercel and Render serve the public app and API. Render Free storage remains ephemeral. |
| Public GitHub repository | Fully implemented and verified | Pushed to main and confirmed public access through the GitHub API. |
| README and demo walkthrough | Fully implemented and verified | Setup, API, test and deployment documentation plus a timed demo walkthrough are in the repo. |
| Public voice demo and submission | Missing | The script is ready. The recording and submission are pending. |
