# Coastal Cornerstone public information agent

## Approved product

Build a separate public agent-to-agent information service for Coastal Cornerstone Construction, hosted in a new Railway project and a new public GitHub repository. The Manus website remains a static site with its current homepage design, approved ICF work, and a footer link to agent documentation/discovery. Runtime knowledge comes only from a source-verified, client-reviewable FAQ dataset derived from the original and updated company websites. Public questions are rate-limited. There is no access to private CRM/customer systems and no arbitrary browsing, messaging, booking, quoting, or remote-agent action.

## Implementation

Use a small Python service with standard-library HTTP/SQLite/urllib tooling, a Dockerfile, and a Railway-mounted persistent volume. Serve GET /health, /docs, /openapi.json, /agent-card.json, /.well-known/agent-card.json, /faq, and POST /ask. Implement a documented read-only JSON-RPC tool endpoint /mcp for MCP discovery and ask_company_question/get_faq tools; do not advertise full A2A protocol compliance unless a complete, validated implementation is supplied. Documentation and discovery expose real reachable capabilities, not unsupported standards claims.

The open-weight DeepSeek V4 Flash model was selected from the live OpenRouter catalog, which advertises high effort and structured outputs. It selects eligible FAQ IDs for the question; the server returns exact curated FAQ answers and validates citations against dataset sources. This reduces free-form hallucination and unauthorized business commitments. Unknown, unsupported, unsafe, unavailable-model, or exhausted-budget requests receive a professional, non-invented response and a private review-queue entry where appropriate. Questions never become approved knowledge automatically.

Enforce the USD 1 monthly model cap with SQLite transactions and pre-request worst-case reservations, including in-flight requests and uncertain failures. Pin the configured model and maximum input/output pricing ceiling; refuse paid calls if live pricing exceeds that ceiling. FAQ/cache responses remain usable without paid calls. Apply global and per-client request limits, input-length/body-size bounds, request timeouts, fixed upstream endpoints, output-schema validation, and no model tool execution. Do not store secrets or the private database in Git.

New questions are deduplicated after normalization and basic personal-data redaction, retained privately for review, and included in a daily 09:00 America/New_York digest. Resend sender notifications@propeldock.com; recipient ben@cccbuild.com. Persistent delivery state plus a fixed idempotency key prevents duplicate daily sends. No empty digest; bounded content; questions sanitized rather than treated as instructions. Email testing is explicitly prohibited for now. Keep DIGEST_ENABLED=false for the task and expose readiness honestly; activation can follow owner approval of production delivery configuration.

## Project structure

app.py owns HTTP endpoints and protocol adapters. agent.py owns safe retrieval/model selection. store.py owns SQLite budget/rate/cache/question/digest state. digest.py owns fixed-destination email scheduling and idempotency. data/faq.json is the public source-verified knowledge snapshot, separate from private new questions. docs/ contains the operator rules, review workflow, source policy, and configuration. tests/ uses local fixtures/mocks rather than sending email. Dockerfile and railway.toml define production startup and health. .env.example lists variable names and defaults without secret values. CHANGELOG.md and feature branches retain development history.

## Website integration

Add a footer Agent access link and static machine-readable discovery referencing the verified live service URL. The public documentation explains endpoints, source grounding, supported protocols, rate limiting, and what an unavailable answer means. It does not promise guaranteed business outcomes or cite unverified facts.
