# Assignment requirements audit

| Requirement | Classification | Evidence or remaining check |
| --- | --- | --- |
| React chat and exact test IDs | Fully implemented and verified | Edge tests cover composer, keyboard control, pending and duplicate-submit behavior, exact assistant metadata, recovery from 503, and fresh session IDs. Production build passed. |
| Responsive layout, empty state and scroll | Fully implemented and verified | The Edge suite covers a 390 px mobile viewport, prompt shortcuts, automatic scrolling, and a readable 422 error. |
| Three API paths, validation and error bodies | Fully implemented and verified | Backend tests cover TCP requests, health and missing key pool, 422, 404, 503, and ordered history. |
| SQLite schema, independent sessions, prompt privacy and persistence | Fully implemented and verified | Tests use real SQLite files and reopen the database across two application lifespans. |
| Docker named volume and restart | Fully implemented and verified | GitHub Actions mounted the volume at /data and read a seeded SQLite history row over HTTP after make down and make up. |
| Multi-turn model context | Partially implemented | Tests prove the full, correct conversation is sent to LiteLLM. Real-provider memory still needs verification. |
| LiteLLM response cache | Fully implemented and verified | Tests use LiteLLM's local cache and cover identical cross-session replies, stored usage, different messages and histories, and prompt-specific keys. |
| Cache versus inference latency | Implemented but not verified | Latency is measured on both paths. A real-provider comparison is pending. |
| Two-key failover and test hook | Partially implemented | Mocked provider exception and TCP header tests passed, including cache bypass, disabled configuration, request scope, 429/5xx simulation, and no writes on failure. Real-key inference and fallback remain pending. |
| Request-local token metadata | Partially implemented | Tests verify prompt and completion counts from the provider response and cache. Actual provider-reported counts remain pending. |
| CORS and build-time API URL | Partially implemented | Local preflight tests verify allowed and denied origins. Public origin configuration remains pending. |
| Multi-stage images and Make targets | Fully implemented and verified | The Linux GitHub runner built both images and ran make up and make down. [Docker workflow run](https://github.com/dapinderbhullar/LyftrAI/actions/runs/44811950958). |
| Environment and secret hygiene | Fully implemented and verified | Placeholder sample configuration, secret ignore rules and server-only key handling. |
| Public hosting | Partially implemented | Render Free backend URL supplied. The frontend still needs deployment and the live flow needs verification. Render Free storage is ephemeral. See the Oracle Cloud migration plan for an Always Free option. |
| Public GitHub repository | Fully implemented and verified | Pushed to main and confirmed public access through the GitHub API. |
| README and demo walkthrough | Fully implemented and verified | Setup, API, test and deployment documentation plus a timed demo walkthrough are in the repo. |
| Public voice demo and submission | Missing | Requires public deployment and voice recording. |
