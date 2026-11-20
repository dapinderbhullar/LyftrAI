# Assignment requirements audit

| Requirement | Classification | Evidence or remaining check |
| --- | --- | --- |
| React chat and exact test IDs | Fully implemented and verified | Edge tests cover composer, keyboard control, pending and duplicate-submit behavior, exact assistant metadata, recovery from 503, and fresh session IDs. Production build passed. |
| Responsive layout, empty state and scroll | Implemented but not verified | Responsive CSS, example buttons, and scroll-to-latest behavior are in source. |
| Three API paths, validation and error bodies | Fully implemented and verified | Backend tests cover TCP requests, health and missing key pool, 422, 404, 503, and ordered history. |
| SQLite schema, independent sessions, prompt privacy and persistence | Fully implemented and verified | Tests use real SQLite files and reopen the database across two application lifespans. |
| Docker named volume and restart | Implemented but not verified | Compose mounts the named volume at /data. The Docker workflow checks both services and reads a seeded history row after make down and make up. |
| Multi-turn model context | Partially implemented | Tests prove the full, correct conversation is sent to LiteLLM. Real-provider memory still needs verification. |
| LiteLLM response cache | Fully implemented and verified | Tests use LiteLLM's local cache and cover identical cross-session replies, stored usage, different messages and histories, and prompt-specific keys. |
| Cache versus inference latency | Implemented but not verified | Latency is measured on both paths. A real-provider comparison is pending. |
| Two-key failover and test hook | Partially implemented | Mocked provider exception and TCP header tests passed, including cache bypass, disabled configuration, request scope, 429/5xx simulation, and no writes on failure. Real-key inference and fallback remain pending. |
| Request-local token metadata | Partially implemented | Tests verify prompt and completion counts from the provider response and cache. Actual provider-reported counts remain pending. |
| CORS and build-time API URL | Partially implemented | Local preflight tests verify allowed and denied origins. Public origin configuration remains pending. |
| Multi-stage images and Make targets | Implemented but not verified | Docker and Make unavailable on the Windows host. The GitHub workflow exercises both images and the Make targets. |
| Environment and secret hygiene | Fully implemented and verified | Placeholder sample configuration, secret ignore rules and server-only key handling. |
| Public hosting | Missing | Render Blueprint prepared. Requires a hosting account, approval for a persistent disk on a paid backend, and two working keys. |
| Public GitHub repository | Implemented but not verified | User supplied a repository. Verify publication and latest commit from GitHub. |
| README and demo walkthrough | Fully implemented and verified | Setup, API, test and deployment documentation plus a timed demo walkthrough are in the repo. |
| Public voice demo and submission | Missing | Requires public deployment and voice recording. |
