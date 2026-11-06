# Operator rules and production release boundaries

## Non-negotiable runtime policy

Business answers are exact eligible curated FAQ text, not model-authored business claims. Models are closed-set selectors for business facts and never execute tools. General construction queries may use the LLM to write a bounded high-level general explanation, explicitly labeled **General construction guidance**, independently model-written and unreviewed, heuristically validated against safety, price, schedule, and engineering constraints; it is not sourced from the topic-title catalog. No private CRM, customer records, engineering advice, quotes, pricing commitments, warranty commitments, availability claims, booking, arbitrary browsing, or message actions. Unsupported or unknown company details – pricing, dates, insurance, warranties, availability, founding, and similar – get a non-invented fallback referring to the published company website/contact form plus the existing bounded review queue. General construction queries are handled by the heuristically validated general guidance mechanism. No answer, follow-up, email, or action is promised, and a queue entry does not approve knowledge. The raw gate targets hateful/discriminatory/racist/sexual content, protected-group judgments, and arbitrary off-topic religion/politics; legitimate WOSB, accessibility, neutral religion-in-project-context, plumbing, male/female/sex bolts, and dimensions are not blanket-blocked. Casual profanity in legitimate construction context is sanitized professionally. Regex gating has limits and is not guaranteed complete.

The private dashboard logs actual incoming questions only, not demo traffic or inferred AI identities. No authentication credential identifies public callers. API/MCP labels name transport; salted IP hashes are limited pseudonymity, not anonymity or identity verification. Avoid names/addresses/confidential context even after basic regex redaction. Dashboard rendering uses textContent and source links validated by the server. JSON exports contain data, not executable reports or secrets; CSV cells are protected against formula prefixes. Restrict downloaded files and volume backups just like the dashboard itself.

## $1/month model ledger

Reservations are taken under SQLite BEGIN IMMEDIATE before provider network calls; price catalog GET is free/read-only and precedes the paid reservation. Input bound is serialized UTF-8 bytes, output ceiling 8,192 tokens, plus 10% safety at pinned price ceilings. The cap includes in-flight, uncertain and settled debits in the reservation's UTC month. At most three pending model calls are allowed. Timeouts, crashes and invalid accounting never automatically refund money. No automatic paid retries exist.

Valid numeric usage settles actual cost. If provider-reported cost exceeds the conservative bound, the full reported charge is recorded honestly and future requests are gated by the ledger; a local application cannot undo a third-party overcharge. Investigate externally with authorization, do not silently lower a reservation or raise the monthly cap. UTC month rollover allows the new month's ledger while preserving old-month charges. FAQ/cache answers continue when paid selection is blocked.

## Digest remains paused

Keep DIGEST_ENABLED=false during this task. Provisioned RESEND_API_KEY is not permission to test or activate email. There is no request-triggered send or test route. Owner approval and real sender configuration are required before enabling. Sender is notifications@propeldock.com; recipient is ben@cccbuild.com. The separate initial Sri credential-access email belongs to the parent, not this runtime digest.

Once explicitly enabled, the app's daily loop checks every minute and sends after 09:00 America/New_York for that local calendar date. ZoneInfo handles daylight saving. The first eligible run prepares a snapshot of pending questions created by that day's 09:00 cutoff; missed runs do not invent catch-up batches. A restart after 09:00 can process the current day's snapshot. No empty email. At most 100 questions, sanitized to 1,000 characters each, are sent in plain text as human-review data, never instructions.

Preparation persists the selected IDs, exact payload and date/batch-hash idempotency key **before** the outbound request. Selected questions become digest_pending, so a later date cannot batch them again while the old outcome is ambiguous. Only a valid successful provider ID marks the exact selected IDs sent. Failure keeps the snapshot unchanged. Concurrent sends are bounded by a persistent attempt claim; repeated attempts within 24 hours reuse the identical key/body. After the original preparation's 24-hour window, the batch becomes hold and is never automatically retried or rebatched.

For a held batch, use a human-approved offline reconciliation: check provider evidence, mark the exact IDs sent if confirmed, or deliberately authorize a new delivery outside this app's automatic path. Do not delete/replace a held batch to force a resend. No automatic operator reconciliation endpoint is provided. Readiness shows inactive, active, missing credentials, and retained delivery states without initiating a network check.

## Release checklist and limitations

The implementation target is accessible semantic HTML, keyboard focus, labels, responsive reflow, plain text rendering and no inline script. It is not a claim of ADA/Section 508 certification or complete WCAG conformance. Browser/manual assistive-technology evaluation was prohibited and not run here. Production release remains conditional on:

- Reviewed source snapshot and business/client authorization.
- Actual single-replica persistent /data mount and backup/access policy.
- Exact HTTPS PUBLIC_ORIGIN, secure cookie behavior, login/logout/CSRF verification and protected hash.
- Railway edge forwarding/header trust and blocked direct-origin bypass before TRUST_PROXY=true.
- Container build and live health/discovery/documentation reachability.
- Source-grounded model schema/routing compatibility when an independently approved paid test is allowed; mock tests are not live-provider evidence.
- Responsive browser, keyboard and screen-reader checks; no visual compliance claim before those checks.
- Explicit owner approval before email activation. No email test is allowed during this implementation.
- Authorized parent-owned Git/release/website footer operations; this task performs none.

No secrets belong in Git. SQLite is private local volume state, not multi-replica distributed storage. Transport disconnects and failures produce sanitized service errors, never credential/provider-body logs. Fixed outbound endpoints reject request-supplied URL overrides, redirects and environment proxies.
