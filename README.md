# Coastal Cornerstone public information agent

A separate, read-only Python 3.12 service for source-verified public company information. Standard library only: no framework, package install, SDK, private CRM, arbitrary browsing, request-triggered email, quoting, booking, or remote-agent actions. The original approved [`plan.md`](plan.md) is retained unchanged. The static Manus website and its footer/discovery integration are separately managed by the parent operator.

## Safety invariant

The pinned `deepseek/deepseek-v4-flash` model can return **approved FAQ IDs and a review flag only**. The server rejects unknown/ineligible IDs, extra output fields, duplicate IDs, tools, and invalid selections. Business answers are exact strings from `data/faq.json`; multiple selected answers add only a blank-line separator. Sources come exclusively from the validated dataset. No model-generated business claims reach the API.

Normalized exact FAQ questions and unique exact approved tags avoid model calls. Validated selections are cached with the full FAQ file hash. Unsupported questions, model or pricing unavailability, and exhausted budgets get a professional source-limited fallback and a bounded private review entry where appropriate. Questions never become approved knowledge automatically.

## Start

```sh
# Python 3.12; no pip install.
DATA_DIR=/tmp/ccc-private DIGEST_ENABLED=false PORT=3000 python3 app.py
# Offline/provider-mocked tests; localhost HTTP only.
python3 -m unittest discover -s tests -v
```

The service reads actual environment variables; it does **not** auto-load `.env`. Copy variable names from `.env.example` into Railway protected variables, not a public repository. Use `DATA_DIR=/data` and a Railway persistent volume mounted at `/data`. Deploy **one replica**: SQLite is local volume state, not a distributed database. `railway.toml` sets Docker startup and `/health`; it does not create a volume, project, or secrets. The container runs as the image default user to avoid mounted-volume ownership mismatch, needs no privileged capabilities, and should not be given host mounts.

Supply the source-reviewed FAQ snapshot before production operation. An absent or invalid snapshot gives zero eligible FAQs and safe fallbacks; it does not invent facts. The supplied 45-entry snapshot is preserved and may have `review_status: pending_client_review`; runtime eligibility is controlled by the explicit `status: source_verified` and `runtime_eligible: true` fields. Client review remains a human workflow.

## Endpoints

Public: `GET /health`, `/docs`, `/openapi.json`, `/agent-card.json`, `/.well-known/agent-card.json`, `/faq`; `POST /ask`, `/mcp`. Public CORS is `*` **without credentials**. Input is UTF-8 JSON only, 8 KB maximum, and an `/ask` question of 2–1,500 characters with no extra fields. HTTP 429 includes `Retry-After`.

MCP supports JSON-RPC initialize version `2025-03-26`, initialized notifications, tools/list, and read-only tools/call (`get_faq`, `ask_company_question`). This is a documented tools subset, **not** full streamable MCP, SSE, full A2A compliance, or action-taking interoperability. Read `/docs` and `/openapi.json` for the actual schemas.

Operational access is session authenticated and not exposed as a public tool; public source code does not provide route secrecy.

## Budget and fixed providers

The hard $1 UTC-month **model** cap is integer microUSD in private SQLite, not user-configurable. `BEGIN IMMEDIATE` reservations include serialized UTF-8 input byte upper bound, 8,192 output tokens and 10% safety at configured price ceilings. In-flight and uncertain failures retain their reservation. Numeric valid provider usage settles charges; missing/invalid accounting stays uncertain. Crashed requests become uncertain, never automatically refunded. A reported charge above the bound is recorded honestly, not hidden. There are no automatic paid model retries and no recurring paid dashboard reports.

Live OpenRouter catalog checks are cached for at most five minutes and pinned to the selected model. Default ceilings are prompt `$0.000000091` and completion `$0.000000182` per token, request fee zero. They may only be lowered. Routing sends `require_parameters: true`, `max_price` per million tokens, no fallback routing, high reasoning effort, 8,192 max tokens, and JSON-only output. Fixed outbound hosts/endpoints are OpenRouter models/completions and Resend emails only; redirect following and environment proxies are disabled. Provider charges/quotas and hosting/email costs are distinct from this model cap.

Questions are limited to 5/minute and 50/UTC day per client, 60/minute and 1,000/UTC day globally; reads to 120/minute per client and 1,200/minute globally. At most three paid requests run concurrently; HTTP threads and password hashing are separately bounded. Do not set `TRUST_PROXY=true` until verifying Railway overwrites/sanitizes the forwarding header and the origin is not directly reachable. Only the **rightmost** forwarding hop is used. With proxy trust off, a shared edge address may conservatively group clients; do not misrepresent this as verified visitor identity.

## Real questions, not invented analytics

Private SQLite records sanitized actual API/MCP questions, UTC timestamp, outcome, FAQ IDs/sources, selected model, cost/reservation, protection reason, and salted IP hash—never raw IP or credentials. Basic redaction covers email, common phone formats, URLs, IPv4/IPv6 and common credential strings, but cannot guarantee anonymity or remove every name/address/contextual identifier. Public callers have no identity credential: a channel label is **not** authentication of a real AI agent identity.

Events retain 30 days, at most 10,000. The review queue deduplicates normalized redacted questions for 30 days, caps 100 new entries per UTC day and 1,000 pending entries, and never auto-approves FAQs. A queued digest reserves selected questions to prevent next-day duplication if delivery is ambiguous. Dashboard metrics describe retained events, not all-time traffic; an unused service has an empty dashboard. CSV is formula-injection-safe; JSON contains no configured keys, password hashes or session/signing salts. The vanilla dashboard uses `textContent`, CSS bars and SVG, not HTML interpretation of question text.

Optional `data/report.json` is a manually supplied **source-review draft**, not historical traffic or an automatic report. Schema and source checks are in [`docs/review-workflow.md`](docs/review-workflow.md). No report file means an honest empty state. Initial one-time build review/report generation is a separate parent-owned budget, never this runtime API.

## Email is paused

`DIGEST_ENABLED=false` by default, in the example environment and Dockerfile. No startup, request, health, or test email is sent. Activation requires owner approval and fixed `DIGEST_FROM=notifications@propeldock.com`, `DIGEST_TO=ben@cccbuild.com`, plus a valid protected `RESEND_API_KEY`. A background loop prepares a bounded daily snapshot after 09:00 America/New_York, sends no empty digest, and uses persistent date/batch idempotency. Ambiguous outcomes retain exact IDs/payload/key; retries are restricted to the original 24-hour idempotency window, after which delivery is held for human review. No new daily batch includes held questions. There is no send/test endpoint. See [`docs/operator-rules.md`](docs/operator-rules.md).

## Files and verification

`app.py` HTTP/protocol adapters; `agent.py` safe retrieval/selector; `store.py` private transactions and analytics; `digest.py` paused email; `dashboard.py` authentication/report/export helpers; `config.py`, `safety.py`, `network.py` reusable guardrails; `static/` vanilla dashboard and styling; `docs/` public and operator documentation; `tests/test_agent.py` provider-mocked fixtures.

Local verification is recorded in [`docs/validation.md`](docs/validation.md). Browser visual/manual accessibility QA, production HTTPS/forwarded-header behavior, container build, external email delivery, paid model compatibility, Git publishing, and Railway deployment are **not asserted as tested** by this implementation. No deployment mutation, Git push, external email, or paid model call was made here. Review and approve production configuration separately.
