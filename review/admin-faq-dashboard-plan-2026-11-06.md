# Admin FAQ and Question Intelligence Re-plan

Date: 2026-11-06

## Confirmed planning-stage changes

- Sequenced work as requested: 2 initial planning loops, 2 skeptic loops, 2 updated planning loops, 6 coding loops, and 2 final testing/fix loops.
- Kept planning isolated from production; no live code, data, FAQ, or deployment changes occur in this stage.
- Added append-only capture and separate admin classification/answer records so visitor text is never silently rewritten.
- Added four explicit review states: Ignore, Needs answer, FAQ candidate, Sensitive-private.
- Put all 100 draft questions into a non-runtime review queue; none can answer visitors until approved.
- Made manual public publication idempotent, auditable, previewable, and rollback-capable for both /faq/ and /ai/.
- Preserved existing 50 FAQ runtime behavior, API/MCP contracts, 30-day retention, private dashboard boundary, and $1/month runtime cap.
- Added clickable chat rows, full conversation breadcrumbs, review filters, search, bulk actions, answer history, mobile focus/keyboard requirements, and public-site breadcrumb consistency.
- Reserved six coding loops for implementation and two final Kimi loops for real test failures and targeted fixes.

## Consolidated revised plan

# Stage 6 — Final Planning Pass: Code Boundaries & Release Sequencing
**Coastal Cornerstone Construction — Chat Agent Enhancement (Pass 6 of 6)**

This pass converts the Stage 5 reconciled spec into (a) explicit code boundaries, (b) a release sequence with per-release rollback, and (c) eight reserved implementation stages: **six coding loops (L1–L6)** and **two testing/fix loops (T1–T2)**. **No code is written in this pass. No mechanism that publishes content without an authenticated admin's explicit, logged, step-up-authenticated action may be introduced in any loop.**

---

## 1. Gate Restatement (binding on all loops)

> Nothing reaches `/faq/` or `/ai/` — no content, no template change, no knowledge-artifact regeneration — except through the Stage 5 §4 pipeline, triggered by an authenticated admin who has (1) previewed each item, (2) passed step-up re-authentication, and (3) confirmed a dialog listing every item. There is no auto-publish, no scheduled publish, no publish-on-approve, no combined approve-and-publish action. Any loop that finds itself needing one of these for convenience stops and escalates instead.

---

## 2. Code Boundaries

### 2.1 Repository boundary (unchanged, restated)

| Zone | Contents | Rules |
|---|---|---|
| **Public agent repo** | Public chat API, `/ai/` agent, `/faq/` rendering, classifier rules + synthetic tests | No credentials, no draft FAQ file, no real chat fixtures (P5, P6). CI guard blocks committing the 100-question source file or anything matching its path/hash. |
| **Private dashboard code** | Admin auth, queue/drafts UI, publish pipeline, reveal endpoint, exports, audit log viewer | Never linked from public templates; generic 404s; robots exclusion (all unchanged from today). |
| **Private data (outside both repos)** | SQLite DB, 100-question draft file, backups, env-var credentials | Importer reads the draft file from a private path at run time; the file is never copied into a repo. |

### 2.2 Module map — new vs. touched vs. forbidden

| Module | Status | Boundary contract |
|---|---|---|
| `public_chat_api` (ingestion, `/ai/` endpoints) | **Touched — minimally** | Only change: classification invoked **after** the write commits, wrapped in fail-open (B5). Request/response shapes, status codes, latency budget: **bit-identical**. |
| `public_faq_render` (`/faq/`) | **Touched** | Read query switches from legacy `faqs` to `faq_items WHERE status='published'` **only at R4 cutover**, behind a config flag, after count-parity verification (B1). Breadcrumbs added as template-only change. |
| `agent_knowledge` (artifact `/ai/` reads) | **Touched** | Regenerated only by the publish pipeline (Stage 5 §4). Never reads `draft`/`in_review`/`approved_not_public` rows. |
| `migrations/` | **New** | Ledger-first (000), idempotent, each with tested down-script; CI up→down→up gate (B8). |
| `classifier/` | **New** | Heuristic v1, versioned rules, time-budgeted, ReDoS-audited regexes, synthetic fixtures only. Emits `classification_pending` on any failure. |
| `retention_sweep` | **Touched — extended** | Order: delete classifications by `message_id` → delete messages → purge/redact sensitive-derived items → orphan-count check → result to Overview card (B2, B6). |
| `faq_domain` (`faq_items`, `faq_versions`, state machine) | **New** | Single source of truth (B9/R1). All transitions are single-row updates, each logged, each with its Stage 5 §2.3 inverse. Live published content never edited in place (A4). |
| `importer` | **New** | One-shot, idempotent (dedupe on question hash), reads private draft file, lands 100 items in `in_review`. |
| `admin_auth` | **Touched** | Adds: CSRF tokens on all admin POSTs, `SameSite=Lax` cookies, 15-min idle timeout, login throttle/lockout, failure logging, step-up re-auth window (B3, B10, A2). Existing credential mechanism unchanged. |
| `publish_pipeline` | **New** | Implements Stage 5 §4 exactly: preconditions → confirm → DB transaction → artifact regeneration → read-back verification → auto-revert on failure. Used by publish **and** unpublish. |
| `sensitive_reveal` | **New** | Server-side withholding; separate authenticated GET; per-message audit log; `Cache-Control: no-store` (P1). |
| `exports` | **Touched** | Default excludes sensitive; opt-in per export (never persisted), typed confirmation, step-up re-auth, logged with row count, warning banner row (P3). |
| `audit_log` | **New** | Append-only at application layer; references + ≤200-char previews; **never full sensitive bodies** (B2). |
| `dashboard_ui` (templates/static) | **Touched** | Server-rendered; canonical status vocabulary (Stage 5 §2.2) everywhere; breadcrumbs; WCAG 2.2 AA per Stage 2 §6. |
| **Forbidden to touch** | Public API request/response contracts; session/cookie names used by existing clients; the 30-day sweep's message-deletion semantics (extended, not replaced); main git history (no rewrites); credential storage. |

---

## 3. Release Sequencing

Five releases. Each is independently reversible, behind a config flag where behavior changes, and gated by its verification column. **R4 is the only release that changes anything a public visitor can see — and even it publishes no new content; it only re-sources existing published FAQs.**

| Release | Contents | Flag / gate | Rollback | Verification gate |
|---|---|---|---|---|
| **R0 — Foundations** | Migration 000 ledger; `PRAGMA foreign_keys = ON` per connection (B6); B7 write-audit (named-column inserts); SQLite version floor verified on host (B8); CI up→down→up harness | No behavior change | Down-scripts; pragma revert | CI cycle green on production-shaped anonymized fixture |
| **R1 — Schema & backfill** | Migrations 001–005; `faq_items` + `faq_versions` + `audit_log`; existing 50 FAQs copied in as `published`/`legacy`; 100 drafts imported as `in_review` | Public read path **unchanged** (still reads legacy table) | Down-scripts; legacy table untouched until R4 | **Public FAQ count before == after** (B1); import count == 100; dedupe check |
| **R2 — Classifier & retention** | Fail-open classification on ingestion; `classification_pending` retry pass; extended sweep with scrub + orphan check | Classifier on; retry pass on sweep run | Classifier flag off (writes unaffected by design, B5) | Fault-injection test: classifier killed mid-run → public chat write succeeds identically; sweep orphan count == 0 on Overview |
| **R3 — Admin workflow** | Login hardening, CSRF, step-up auth; queue/drafts as filters over `faq_items`; full state machine; version history; audit log; sensitive reveal endpoint; export changes; breadcrumbs (private) | Dashboard-only; no public surface change | Feature flags per module; prior dashboard templates restorable | Keyboard walkthrough login → review → approve (no publish yet); CSRF negative tests; lockout test |
| **R4 — Publish pipeline & public cutover** | Publish/unpublish pipeline with read-back verification + auto-revert; `/faq/` read-path cutover to `faq_items`; agent artifact regeneration; public breadcrumbs | Cutover flag; pipeline requires step-up auth | Cutover flag back to legacy read; unpublish pipeline | Read-back verification passing; pipeline failure-injection (kill artifact write → DB auto-reverts, error banner shows); Sri or Ben performs one real publish + one real unpublish in production |

**Sequencing rule:** R_n does not start until R_(n−1)'s verification gate has passed in production for at least one full sweep cycle (24h). R3 and R4 may overlap in development but not in deployment.

---

## 4. Reserved Implementation Stages

### Coding loops L1–L6

Each loop: **scope, files touched, acceptance criteria, explicit out-of-scope.** Loops map to releases but are sized to be reviewable in one sitting by Sri or Ben.

| Loop | Maps to | Scope | Acceptance criteria | Out of scope (stop-and-escalate if needed) |
|---|---|---|---|---|
| **L1 — Migrations & schema** | R0, R1 | Migrations 000–005; ledger; FK pragma; B7 write-audit fixes; backfill of 50; importer for 100 | CI up→down→up green; rehearsal on anonymized dump; count parity; import idempotent on re-run | Any change to public read paths; any UI |
| **L2 — Classifier** | R2 | Heuristic v1 rules; fail-open wrapper on ingestion; `classification_pending` + retry pass; ReDoS audit; synthetic test fixtures | Fault-injection: public write succeeds with classifier dead/slow; per-message time budget enforced; zero real chat data in fixtures | Auto-promotion of candidates to queue (promotion stays a human action); any ML/external service |
| **L3 — Retention & privacy plumbing** | R2 | Extended sweep (classifications → messages → sensitive-derived scrub); orphan verification → Overview card; audit-log preview truncation; backup-retention decision written into operator docs (Stage 5 §6 — pick one, write it down) | Orphan count 0 surfaced on Overview; sensitive-derived items gone at source expiry; UI copy matches the chosen backup policy exactly | Changing the 30-day message window; deleting non-sensitive drafts |
| **L4 — Admin security** | R3 | CSRF on all admin POSTs; cookie flags; 15-min idle timeout; login backoff/lockout + failure logging; step-up re-auth (5-min window) for publish/unpublish/export-with-sensitive; sensitive reveal endpoint (server-side withholding, per-message logging, `no-store`) | Negative tests: POST without token rejected; 5 failures → lockout; reveal logged per admin per message; step-up expiry enforced | Any change to credential storage; any new role model |
| **L5 — FAQ domain & workflow** | R3 | `faq_items` state machine with all Stage 5 §2.3 transitions and inverses; append-only `faq_versions`; audit log writes; approve-time sensitive re-scan (blocks with warning); duplicate flag-only linking; merge-against-published creates new draft revision (A4); save-conflict side-by-side (R7) | Every transition logged with actor + prior state; no transition without inverse; published content never edited in place; un-approve and restore work | Publish pipeline itself (L6); any bulk approve |
| **L6 — Dashboard UI & publish pipeline** | R3, R4 | Queue/drafts/published filters; status chips in canonical vocabulary; breadcrumbs (private + public templates); click-to-reveal wiring; export UI with per-export opt-in + typed confirmation; publish pipeline (preconditions → per-item preview check → confirm dialog → DB transaction → artifact regeneration → read-back verification → auto-revert); `/faq/` cutover flag; WCAG 2.2 AA per Stage 2 §6 | Pipeline failure-injection passes (kill artifact write → auto-revert + banner); batch >10 soft warning; un-previewed items excluded and named; accessibility checks per Stage 2 §6 verification block | Any auto/scheduled/combined publish mechanism — **explicitly forbidden**; public API changes |

### Testing/fix loops T1–T2 (reserved, post-implementation)

| Loop | Timing | Scope | Exit criteria |
|---|---|---|---|
| **T1 — Full verification** | After L6, before R4 cutover | Keyboard walkthrough of the full loop (login → review → approve → publish → rollback); one screen-reader pass on Chat detail and Review Queue; automated contrast/lint in CI; migration rehearsal final run; publish/unpublish failure-injection suite; CSRF/lockout/step-up negative tests; retention sweep end-to-end with orphan check; backup-retention policy confirmed in writing | Every Stage 5 §12 blocker (B1–B10) and finding (P1–P7, A1–A5) re-verified as resolved; accessibility regressions treated as publish-blockers, same as functional ones |
| **T2 — Fix & release-gate sign-off** | After T1 | Fix everything T1 found; re-run failed checks; Sri **and** Ben each perform a supervised dry-run: approve one item, publish it, unpublish it, confirm both surfaces reverted; operator README finalized (login-hardening disclaimer, backup policy, rollback runbook) | Both admins sign off; rollback runbook tested end-to-end; R4 cutover scheduled |

---

## 5. Cross-Cutting Invariants (checked in every loop's review)

1. **Public API contracts:** request/response shapes, status codes, and error bodies unchanged — verified by a contract test run in L2, L6, T1.
2. **$1/month cap:** no new external services, no email infra, no paid APIs; presence/conflict uses simple polling on existing infra.
3. **Auditability:** every mutation in L4–L6 writes an audit row with actor, action, entity, prior state — no exceptions.
4. **Rollback:** every release has a tested down path; every content action has its Stage 5 §2.3 inverse.
5. **No credentials in code or plan artifacts;** synthetic fixtures only in the public repo.
6. **Main history never rewritten.**
7. **Manual gate:** the only path to public is the Stage 5 §4 pipeline, human-triggered, step-up-authenticated, per-item-previewed, logged, and verified on both surfaces.

---

## 6. Items Carried Into Implementation (must not be lost)

| Item | Owner loop |
|---|---|
| Backup-retention decision (≤30-day rotation **or** honest "N days in backups" copy) — pick one, write it down | L3, confirmed T2 |
| Verify existing app sets `PRAGMA foreign_keys = ON`; if absent, log as pre-existing bug and enable | L1 |
| Confirm 100-question draft file lives outside the public repo + CI/pre-commit guard | L1 |
| SQLite version floor (≥3.35.0 if down-scripts use `DROP COLUMN`) verified on host | L1 |
| Audit log documented as admin accountability, not tamper-proof forensics (P7) | L5, README in T2 |
| Stage 2 §9 resolutions stand: flag-only duplicates, no email, soft warning at 10, rejected items persist collapsed | L5/L6 |

---

**End of planning.** Passes 1–6 produced no production code changes. Implementation begins at L1 only on Sri or Ben's go-ahead, and the first public-visible change (R4) occurs only after T2 sign-off — and even then, no *content* goes public until an admin explicitly publishes it through the gated pipeline.

## Pass 1 — initial-architecture

# Stage 1 — Initial Architecture Plan
**Coastal Cornerstone Construction — Chat Agent Enhancement (Pass 1 of 6)**

---

## 1. Context & Constraints (Locked)

| Constraint | Architectural Implication |
|---|---|
| SQLite compatibility | All migrations must be SQLite-safe (no `ALTER COLUMN`, use additive `CREATE TABLE` / `ADD COLUMN` only) |
| 30-day retention | New tables must either join the existing retention sweep or be explicitly exempt (FAQ/audit data is exempt; raw chat data is not) |
| Public repo, no credentials | No secrets in code/config; admin auth stays env-var driven; classification rules must not embed private data |
| $1/month runtime cap | No external LLM/API calls for classification — rule-based/heuristic classifier runs in-process |
| Public API contracts preserved | Existing endpoints unchanged; all new endpoints are additive and admin-only |
| Non-rewritten main history | All work lands as new commits; migrations are forward-only with rollback scripts, never destructive |
| Manual approval before public publish | Publish is a distinct, human-triggered state transition — never automatic, never time-based |
| No production code changes during planning | This pass produces documents only |

---

## 2. Module Map

### 2.1 Existing (unchanged contracts)
- **Public site**: `/faq/`, `/ai/` (chat widget)
- **Public API**: chat session/message ingestion endpoints
- **Private dashboard**: Overview/Chats, chat detail, CSV/JSON export, FAQ list (50 approved)
- **Admin auth**: session-based login for Sri and Ben

### 2.2 New / Extended Modules

| # | Module | Type | Responsibility |
|---|---|---|---|
| M1 | **Capture completeness audit** | Extension | Verify every chat entry (user + agent + system events) is persisted; close any gaps in current ingestion |
| M2 | **Message classifier** | New (in-process, heuristic) | Tag each message: `ignore`, `needs_answer`, `faq_candidate`, `sensitive_private` |
| M3 | **Classification store** | New table | Persist classification + confidence + rule version per message |
| M4 | **Draft answer workspace** | New | Admins draft/edit answers against flagged messages; full version history |
| M5 | **FAQ review queue** | New | Queue containing (a) classifier-suggested candidates, (b) all 100 draft-only FAQs imported for review |
| M6 | **FAQ draft importer** | New (one-time + rerunnable) | Idempotent import of the 100-question draft file into the review queue — **never** directly into approved state |
| M7 | **Publish pipeline** | New | Explicit manual action: approved FAQ → public `/faq/` content + `/ai/` agent knowledge; two-step (approve → publish) |
| M8 | **Clickable conversation rows** | Extension | Chats list rows link to existing chat detail view |
| M9 | **Breadcrumbs** | Extension | Dashboard (all private pages) + public site (`/faq/`, `/ai/`) |
| M10 | **UI/UX refresh** | Extension | Layout, navigation, queue ergonomics; scoped to templates/static assets |
| M11 | **Audit log** | New table | Every admin action: login, classify override, draft edit, approve, publish, export |

---

## 3. Data Flow

### 3.1 Chat capture & classification (automatic, private)
```
Visitor (/ai/) → Public chat API (unchanged contract)
   → messages table (existing, 30-day retention)
   → M2 classifier (on write, synchronous, <5ms heuristic)
   → classifications table (message_id, label, rule_version, created_at)
   → if label = faq_candidate → review_queue entry (status: pending)
   → if label = sensitive_private → hidden from exports by default; flagged in UI
```

### 3.2 Admin answer drafting (manual, private)
```
Admin (Sri/Ben) → login (existing auth)
   → Dashboard → Chats (clickable rows, M8) → chat detail
   → flagged message → "Draft answer" (M4)
   → draft_versions table (append-only history)
   → optionally promote draft → review_queue as FAQ candidate
```

### 3.3 FAQ lifecycle (manual gates — explicit)
```
[100 draft FAQs] --M6 importer--> review_queue (status: pending_review)
[classifier candidates] --------> review_queue (status: pending_review)

review_queue --admin edits--> draft_versions (history)
             --admin approves--> faqs table (status: approved, NOT public)
             --admin publishes (separate explicit action)--> M7 publish pipeline
                  → public /faq/ content updated
                  → /ai/ agent knowledge updated
                  → audit_log entry (who, when, what, prior version for rollback)
```

**No path from any queue state to public visibility without two distinct human actions (approve, then publish).**

### 3.4 Retention
```
Nightly sweep (existing) → deletes messages > 30 days
   → classifications rows cascade-delete with their messages
   → review_queue entries sourced from expired messages are marked source_expired
     (the drafted answer text survives; the raw chat does not)
   → faqs, draft_versions, audit_log: EXEMPT from retention (business records)
```

---

## 4. Roles & Permissions

| Capability | Visitor | Admin (Sri, Ben) |
|---|---|---|
| Use `/ai/` chat, view `/faq/` | ✅ | ✅ |
| View dashboard, chats, classifications | ❌ | ✅ |
| See `sensitive_private` content | ❌ | ✅ (flagged, excluded from default exports) |
| Draft/edit answers, view history | ❌ | ✅ |
| Import/approve/reject FAQ candidates | ❌ | ✅ |
| **Publish to public site/agent** | ❌ | ✅ (explicit per-item or batch action, logged) |
| Export CSV/JSON | ❌ | ✅ (sensitive excluded unless explicitly included) |

Both admins hold identical permissions (no role split needed at this scale; audit log provides accountability).

---

## 5. Database Migrations (SQLite-safe, forward-only)

| Migration | Change | Rollback |
|---|---|---|
| `001_classifications` | `CREATE TABLE classifications (id, message_id FK, label TEXT CHECK(...), rule_version TEXT, created_at)`; index on `message_id`, `label` | `DROP TABLE` (no data loss to core chat) |
| `002_draft_versions` | `CREATE TABLE draft_versions (id, entity_type, entity_id, body TEXT, author, created_at)` — append-only | `DROP TABLE` |
| `003_review_queue` | `CREATE TABLE review_queue (id, source_type, source_id, question, answer_draft, status TEXT DEFAULT 'pending_review', created_at, updated_at)` | `DROP TABLE` |
| `004_faq_status` | `ALTER TABLE faqs ADD COLUMN status TEXT DEFAULT 'approved'`; `ADD COLUMN published_at NULL`; `ADD COLUMN published_by NULL` | Columns ignored by old code (additive = backward compatible); rollback script nulls them |
| `005_audit_log` | `CREATE TABLE audit_log (id, actor, action, entity, entity_id, before_json, after_json, created_at)` | `DROP TABLE` |

**Migration principles:** additive only; each ships with a tested down-script; old code runs cleanly against new schema (backward compatible); no data rewrites of existing rows.

---

## 6. Minimal Change Strategy

1. **Zero changes to public API request/response shapes.** Classification happens server-side after the existing write path.
2. **Reuse existing auth** for all new admin routes; new routes live under the existing private prefix and inherit the same "hidden from public site" property (no links, no sitemap, `robots` exclusion, auth-gated).
3. **Classifier is heuristic v1** (keyword/pattern rules: profanity/spam → ignore; question marks + unmatched FAQ → needs_answer; recurring question cluster → faq_candidate; PII patterns (email, phone, address, payment terms) → sensitive_private). Rule set is versioned and data-driven so it can be tuned without schema changes. No external API calls — protects the $1/month cap.
4. **FAQ publish reuses the existing FAQ rendering path** — publishing flips a status flag; public `/faq/` queries `status = 'published'`; `/ai/` knowledge source reads the same filtered set. Rollback = flip status back (audit log retains prior state).
5. **UI work is template/static-asset scoped** — breadcrumbs, clickable rows, queue views; no routing contract changes.
6. **Importer is idempotent** (dedupe on question hash) so it can be rerun safely.

---

## 7. Risk Register (Top Items)

| Risk | Mitigation |
|---|---|
| Classifier mislabels sensitive data as FAQ candidate | `sensitive_private` check runs **first** and is exclusionary; publish requires human approval anyway |
| 100-FAQ import accidentally goes live | Importer can only write `pending_review`; publish path is a separate code path requiring explicit action |
| Retention sweep deletes data referenced by queue | Queue stores its own copy of question/answer text; source link is soft |
| Migration breaks existing dashboard | Additive-only schema; old code ignores new columns/tables |
| Public repo leaks private logic | Classification rules contain patterns, not captured data; dashboard routes remain unlinked and authed |

---

## 8. Six-Pass Roadmap Position

- **Pass 1 (this):** Architecture baseline ✅
- **Pass 2:** Data model & migration specs in detail (field-level)
- **Pass 3:** Classifier rule set + review queue workflow spec
- **Pass 4:** Admin UX spec (drafting, history, breadcrumbs, clickable rows, UI refresh)
- **Pass 5:** Publish/approval pipeline, audit & rollback spec
- **Pass 6:** Final review — constraints compliance checklist, test plan, rollout order

---

**Approval gate reminder:** Nothing in this plan auto-publishes. Public `/faq/` and `/ai/` change only via an authenticated admin's explicit publish action, recorded in the audit log with rollback state preserved.

## Pass 2 — initial-product-ux

# Stage 2 — Initial Product/UX Plan
**Coastal Cornerstone Construction — Chat Agent Enhancement (Pass 2 of 6)**

---

## 1. Scope of This Plan

This pass is an **independent product/UX baseline** — it treats the Stage 1 architecture as input but reasons from the operator's chair outward. It covers:

- Day-to-day operator workflow (Sri & Ben)
- Private dashboard information architecture and screen-by-screen UX
- Public breadcrumbs (`/faq/`, `/ai/`)
- FAQ review queue ergonomics (the 100-draft import + classifier candidates)
- Accessibility targets and verification

**Non-negotiables carried forward:** public `/faq/` and `/ai/` content changes only after an explicit, authenticated, human approve → publish action; private dashboard and private API remain unlinked from the public site and auth-gated; no code is written in this pass; zero public API contract changes; no credentials anywhere in the plan.

---

## 2. Personas & Operator Reality

### 2.1 Sri and Ben — dual admins, identical permissions
Small construction business. Neither is a full-time content manager. The design consequences:

| Reality | UX Consequence |
|---|---|
| Intermittent usage (maybe weekly) | Queue shows "what changed since your last visit" — no assumed daily habit |
| Shared responsibility, no handoff protocol | Every item shows owner-of-record via audit log ("Ben approved 3 days ago"); no silent state |
| Mobile usage likely (job sites) | Dashboard must be usable on a 375px viewport for review/approve; bulk drafting can remain desktop-first |
| Non-technical operators | No jargon: "Needs answer" not "unmatched intent"; no exposed rule syntax |
| Time-boxed sessions | Every list is filterable to "what needs me right now" in ≤2 clicks from login |

### 2.2 Site visitors
Homeowners researching coastal construction — often on phones, often anxious about cost/timeline. FAQ and chat must read as calm, plain, trustworthy.

---

## 3. Operator Workflow — End to End

### 3.1 The core loop (target: under 10 minutes per session)

```
Login → Overview ("What needs me")
   ├─→ Chats (clickable rows) → Chat detail → Draft answer → Save
   ├─→ Review Queue → Edit draft → Approve  (state: approved, NOT public)
   └─→ Approved list → Publish (explicit, confirm dialog) → Public /faq/ + /ai/
```

**Two gates are visually and mechanically distinct:**
- **Approve** = "this answer is correct and safe." Regular action button, reversible.
- **Publish** = "put this in front of the public right now." Separate screen/section, confirmation dialog showing a diff of what the public will see, typed or checked acknowledgment for batch publishes.

No inline "Approve & Publish" shortcut button. Combined actions are a known source of accidental publishes; the extra click is the safeguard.

### 3.2 Session workflow in detail

**Step 1 — Overview (landing after login)**
Cards, ordered by urgency:
1. **Sensitive flags** — count of messages classified `sensitive_private` in last 7 days (review for PII handling; excluded from default exports).
2. **Needs answer** — count of unanswered flagged messages, oldest age shown ("Oldest: 4 days").
3. **Review queue** — pending count, split: *Imported drafts (100 → n remaining)* vs. *From chats (n)*.
4. **Approved, awaiting publish** — count + a direct link. This card exists so approvals never silently pile up unpublished.
5. Recent activity feed (audit log, last 10 entries, human-readable: "Sri published 'Do you handle hurricane-rated windows?'").

**Step 2 — Chats**
- Rows are **entirely clickable** (full-row link semantics, not just a title link) with visible hover/focus affordance.
- Each row: visitor snippet (first user message, truncated), timestamp, message count, classification badges (colored + labeled, never color-alone).
- Filters: classification, date range, has-draft, sensitive-excluded-by-default toggle.
- 30-day retention is **surfaced honestly in the UI**: a persistent note "Chat records are kept for 30 days. Drafted answers are kept permanently."

**Step 3 — Chat detail**
- Full conversation thread, chronological.
- Each message shows its classification chip; admin can **override** the classification (override is logged).
- "Draft answer" attaches to a flagged message; the draft editor opens with the message quoted above it.
- Sensitive messages render behind a click-to-reveal shield with a visible "Sensitive — excluded from exports" marker. Never rendered by default, even for admins — reduces shoulder-surf and screenshot risk.

**Step 4 — Drafting**
- Editor: question (editable), answer body (plain text + minimal formatting: paragraphs, lists, links), autosave indicator, explicit Save.
- **History panel** beside the editor: every saved version, who wrote it, when, with one-click "Restore this version" (restore creates a new version — history is append-only, never destroyed).
- From a draft: **Send to review queue** or, if it answers a recurring question, **Propose as FAQ**.

**Step 5 — Review queue**
- Single queue, two clearly labeled source tabs: **Imported drafts (100)** and **From chats**.
- Bulk triage: select → Reject (with optional reason) or Move-to-drafting. **No bulk Approve, and never bulk Publish.** Approve requires opening the item and reading it — the open-and-read is the review.
- Each item: question, current answer draft, source (import date / linked chat), age, last editor.
- Progress indicator for the import: "47 of 100 reviewed" — gives Sri and Ben a finish line.

**Step 6 — Approve → Publish**
- Approving moves the item to **Approved — awaiting publish** (private; not visible anywhere public).
- The Publish screen lists approved items with a **public preview toggle** showing exactly how the FAQ entry will render on `/faq/`.
- Publish action: per-item or selected batch → confirmation dialog listing titles → on confirm, items go live on `/faq/` and become available to the `/ai/` agent knowledge in the same transaction; audit log records actor, timestamp, item IDs, and prior state.
- **Unpublish/rollback** is one click from the same screen (restores prior published state or removes the item), also logged. Rollback must be as easy as publish or people will fear publishing.

### 3.3 Edge workflows
- **Duplicate FAQ detected** (new candidate ≈ existing FAQ): inline warning with a link to the existing entry; options: merge, replace draft, or keep both.
- **Chat source expired** (30-day sweep removed the underlying chat): queue item remains, marked "Original chat expired — draft preserved."
- **Two admins editing the same item**: last-save-wins is unacceptable. Show "Ben is editing this now" presence lock (soft, overridable after idle timeout), and on save conflict offer a side-by-side of both versions.
- **Sensitive content in a drafted answer**: warn on save if the draft body matches sensitive patterns (email, phone, address) — warn, don't block; some contact info is legitimately public.

---

## 4. Information Architecture

### 4.1 Private dashboard (all auth-gated, unlinked from public site, excluded from robots/sitemap)

```
Dashboard
├── Overview                (landing; "what needs me")
├── Chats
│   └── Chat detail         (thread + classifications + drafting)
├── Review Queue
│   ├── Imported drafts
│   └── From chats
├── FAQs
│   ├── Drafts (workspace + history)
│   ├── Approved — awaiting publish
│   └── Published (live; unpublish/rollback)
├── Activity (audit log, filterable by actor/action)
└── Exports (CSV/JSON; sensitive excluded unless explicitly included)
```

### 4.2 Breadcrumbs — private

Every private page shows its path, e.g.:
`Dashboard › Review Queue › Imported drafts › "What are your payment terms?"`
Breadcrumbs are links at every level except the current page. They mirror the IA above exactly — no orphan pages.

### 4.3 Breadcrumbs — public

Public pages get their own, **completely separate** breadcrumb trail that never references the dashboard:

- `/faq/`: `Home › FAQ`
- `/ai/`: `Home › Ask us` (or the page's public title)
- A FAQ item anchor/deep-link (if used): `Home › FAQ › [Question]`

**Hard rule:** no public breadcrumb, link, redirect, error page, or 404 body may reveal the dashboard path, route names, or existence. A mistyped private URL returns the same generic 404 as any other missing public URL.

---

## 5. UI/UX Refresh Principles

Scoped to templates and static assets; no routing or API contract changes.

1. **One primary action per screen.** Secondary actions demoted to menus.
2. **State is always visible.** Every FAQ/queue item carries an explicit status chip from a fixed vocabulary: `Draft`, `In review`, `Approved — not public`, `Published`, `Rejected`. The phrase "not public" appears on every approved-unpublished item — this is the standing reminder of the manual gate.
3. **Density with air.** Construction-admin users skim; rows at comfortable touch height (≥44px) even on desktop tables.
4. **Plain language.** Button labels are verbs: "Save draft," "Send to review," "Approve," "Publish to site," "Take off site."
5. **Destructive/irreversible actions are visually distinct.** Publish = prominent; Unpublish/Delete = danger styling + confirm.
6. **No dark patterns.** Rejection reasons optional; nothing auto-advances state.
7. **Consistent classification color language** across Overview, Chats, detail, and queue — with text labels always accompanying color.

---

## 6. Accessibility Plan

Target: **WCAG 2.2 AA** for dashboard and public pages.

| Area | Requirement |
|---|---|
| Keyboard | Full task completion without a mouse: row activation, drafting, approve, publish-confirm dialog (focus trapped, Esc closes, focus restored) |
| Focus | Visible focus indicator on all interactive elements, ≥3:1 contrast against adjacent colors |
| Screen readers | Chat threads as semantic lists with speaker labels; status chips announced as text ("Status: approved, not public"); breadcrumb nav uses `nav` + ordered list + `aria-current` on the current page |
| Color | Classification/status never conveyed by color alone — icon + text label; all text ≥4.5:1 |
| Forms | Every input has a visible label (not placeholder-only); errors identified in text and linked to the field |
| Motion | No auto-playing animation; any transition respects reduced-motion preferences |
| Tables | Chat/queue tables use real header associations; clickable rows expose an explicit accessible name ("Open chat from March 3, 14 messages") |
| Touch | All targets ≥44×44px, including mobile dashboard |
| Click-to-reveal (sensitive) | Operable by keyboard and announced as "Sensitive content, hidden. Activate to reveal." |

**Verification (per release):** keyboard walkthrough of the core loop (login → review → approve → publish → rollback), one screen-reader pass on Chat detail and Review Queue, automated contrast/lint check in CI. Accessibility regressions block publish UI changes, same as functional ones.

---

## 7. Public-Facing Changes (still behind the manual gate)

Nothing in this section ships to the public automatically. Each is staged privately and goes live only via the publish action:

- `/faq/` renders only `Published` FAQs; new entries appear solely through publish.
- `/ai/` agent knowledge reads the same published set — no draft or approved-unpublished content can leak into agent responses.
- Public breadcrumbs (`Home › FAQ`, `Home › Ask us`) ship with the next content publish or independently as a template-only update — either way, reviewed by Sri or Ben before deploy.

---

## 8. Constraints Compliance Check

| Constraint | How this plan honors it |
|---|---|
| Manual approval before public | Two distinct human actions (approve, publish), confirm dialogs, visible "not public" state, no combined shortcut |
| Private dashboard/API hidden | Separate breadcrumb trees, no public links, generic 404s, robots exclusion (unchanged from today) |
| Public API contracts preserved | Zero changes; all UX work is server-rendered templates/static assets |
| 30-day retention | Surfaced in UI copy; drafts/FAQs preserved beyond source chat expiry |
| Auditability | Activity feed is a first-class nav item; every override/approve/publish/rollback logged with actor and prior state |
| Rollback | One-click unpublish/restore; version history is append-only |
| $1/month cap | No new external services; presence/conflict features use simple polling on existing infra |
| No credentials | Plan references no secrets; auth remains as-is |
| No production code changes this pass | Document only |

---

## 9. Open Questions for Pass 3+

1. Should classifier candidates enter the queue pre-merged with near-duplicate existing FAQs, or flagged only? (Recommendation: flag-only; merging is a human call.)
2. Do Sri and Ben want an email/digest nudge when "Needs answer" exceeds an age threshold — or is the Overview card enough given the $1/month cap? (Recommendation: Overview card only; no email infra.)
3. Batch publish size limit? (Recommendation: soft warning above 10 items; no hard cap.)
4. Should rejected items auto-expire from the queue after N days, or persist indefinitely? (Recommendation: persist, collapsed by default — rejection is a decision worth keeping visible.)

---

**Gate restated:** This plan contains no mechanism — automatic, scheduled, or incidental — by which any content reaches `/faq/` or `/ai/` without an authenticated admin's explicit, logged publish action.

## Pass 3 — skeptic-privacy-safety

# Stage 3 — Skeptic Review: Privacy & Safety Critique
**Coastal Cornerstone Construction — Chat Agent Enhancement (Pass 3 of 6)**

**Verdict:** Both baseline plans are directionally sound and the two-gate (approve → publish) model is the right spine. However, there are **five hard blockers** — including one that would silently empty the public FAQ page and one that breaks the 30-day retention promise — plus a set of auth/CSRF and cache-consistency gaps that must be resolved in Passes 4–5 before any implementation pass.

---

## 1. Blockers (must be resolved before Pass 6 sign-off)

| ID | Severity | Finding | Plans Affected | Required Fix |
|---|---|---|---|---|
| **B1** | 🔴 Critical | **Migration 004 empties the public FAQ.** `ALTER TABLE faqs ADD COLUMN status TEXT DEFAULT 'approved'` gives the existing 50 live FAQs `status='approved'`, but the new public query filters `status='published'`. The moment the new read path ships, `/faq/` renders zero items and `/ai/` loses its knowledge base. | Arch §5, §6.4 | Migration must **backfill existing rows to `published`** (they are already live; this records reality, it does not publish anything new). Alternatively the read path treats pre-migration rows as published. Either way: add a post-migration verification step — "public FAQ count before == after" — as a release gate. |
| **B2** | 🔴 Critical | **Retention leak through exemption copies.** The 30-day sweep deletes messages, but (a) `review_queue` stores its **own copy** of question text, (b) `draft_versions` may quote sensitive messages, (c) `audit_log.before_json/after_json` will contain message/draft bodies. All three are retention-exempt. Net effect: sensitive chat content persists **forever** while the UI claims "kept for 30 days." This is a privacy promise the system doesn't keep. | Arch §3.4, §5; UX §3.2 | (1) On source-message expiry, **scrub sensitive-derived copies**: queue items sourced from `sensitive_private` messages are purged or redacted, not just marked `source_expired`. (2) Audit log stores **references + metadata** (actor, action, entity ID, diff hash, truncated preview) — never full sensitive bodies. (3) Drafts inherit a sensitivity flag from their source message; sensitive drafts get a defined retention (e.g., purge 90 days after resolution). (4) State the real policy in UI copy. |
| **B3** | 🔴 Critical | **No CSRF protection specified anywhere.** Every new admin mutation — classify override, draft save, approve, publish, unpublish, export-with-sensitive — is a state-changing POST. Neither plan mentions CSRF tokens. A single malicious page visited by Sri or Ben could publish FAQs. | Both | Mandatory: synchronizer-token CSRF on **all** admin POSTs, `SameSite=Lax` (or Strict) session cookies as defense-in-depth, and `Origin`/`Referer` checks on the publish endpoint specifically. Publish additionally requires **step-up re-authentication** (password re-entry) — see B6/F3. |
| **B4** | 🔴 Critical | **Publish/rollback is not actually transactional across both surfaces.** Arch §3.3 says `/faq/` and `/ai/` knowledge update "in the same transaction," but the agent knowledge is almost certainly a file, cache, or in-memory snapshot — not a SQLite row. Risks: (a) partial publish (FAQ live, agent stale, or vice versa), (b) **rollback that doesn't roll back** — unpublish flips the DB flag but the agent keeps answering with the removed content from cache. | Arch §3.3, §6.4; UX §3.1 | Define the publish pipeline explicitly in Pass 5: DB flag flip → regenerate agent knowledge artifact → **verify both surfaces** (read-back check) → only then report success. Unpublish must invalidate/regenerate the same artifact. If verification fails, auto-revert the DB flag and alert. Rollback is only real when both surfaces are confirmed reverted. |
| **B5** | 🔴 Critical | **Classifier is on the public write path with no failure containment.** Arch §3.1 runs classification synchronously on message ingestion. A classifier exception (catastrophic regex backtracking on adversarial input, bug in a new rule version) would fail the **public chat API write** — a direct public API contract regression. | Arch §3.1, §6.3 | **Fail-open, always.** Chat persistence must succeed even if classification throws; classification failure logs an error and leaves the message unclassified (a `classification_pending` state the queue can retry). Add a per-message time budget with regexes audited for ReDoS. Public API behavior must be bit-identical whether the classifier is healthy, slow, or dead. |

---

## 2. Privacy Findings (non-blocking but required fixes)

| ID | Finding | Fix |
|---|---|---|
| **P1** | **Click-to-reveal is unspecified at the server layer.** If the "shield" (UX §3.2 Step 3) is CSS hiding content already in the HTML, the sensitive text is in page source, browser cache, and any screenshot of dev tools. | Sensitive message bodies are **withheld server-side**; the detail page renders only the marker. Reveal is a separate authenticated request, **audit-logged per admin per message**, and re-shields on navigation. |
| **P2** | **Heuristic PII detection has false negatives.** "Sensitive check runs first" (Arch §6.3) helps, but a miss means PII flows into the review queue as an FAQ candidate and sits one distracted approval away from publication. | (1) Human gate already exists — keep it, and add a **second automated sensitive-pattern scan at approve time and again at publish time** (defense in depth; a match blocks the transition with a warning, not just at ingest). (2) Publish confirmation dialog flags any item whose text matches sensitive patterns. (3) Accept residual risk explicitly: heuristics reduce, not eliminate. |
| **P3** | **"Include sensitive in export" is a standing footgun** (UX §4.1, Arch §4). One checkbox produces an uncontrolled PII file on a laptop. | Default-off **per export, never persisted**; requires a typed confirmation; the export itself is audit-logged (actor, timestamp, row count, whether sensitive was included). Add a visible warning banner on the exported file's first row. |
| **P4** | **Backups undermine the 30-day claim.** SQLite backups/snapshots taken before a sweep retain deleted messages indefinitely. | Align backup retention with data retention: backups rotate on a ≤30-day cycle, or the retention promise is restated as "30 days in live systems, up to N days in encrypted backups." Pick one and write it down in Pass 5. |
| **P5** | **The 100-question draft file's location is unstated.** If it lives in (or gets committed to) the **public agent repository**, the drafts are already public — and if any contain internal pricing/terms, that's an existing exposure. | Confirm in Pass 5: the draft file and the importer's source data live **outside** the public repo (or in a private path never deployed). Add a CI check or pre-commit guard against committing it. |
| **P6** | **Test fixtures risk leaking real data.** Tuning classifier rules invites copy-pasting real chat snippets as test cases — into a public repo. | Policy, stated in Pass 5: **synthetic fixtures only**; rule tests use invented examples. Code review checklist item. |
| **P7** | **Audit log is append-only but admin-editable at the DB layer.** Fine at this scale, but the plans overstate it as tamper-proof. | Document honestly: audit log provides accountability between Sri and Ben, not forensic integrity against someone with server access. Optional hardening: periodic hash-chained digest exported off-box. Defer if it threatens the $1 cap. |

---

## 3. Accidental-Publication Findings

| ID | Finding | Fix |
|---|---|---|
| **A1** | **Batch publish confirmation lists titles only** (UX §3.1 Step 6). An admin can batch-publish items they've never read — the checkbox acknowledgment becomes ritual, not review. | Batch publish requires each included item to have been **individually opened and previewed** (system tracks previewed-at per item per admin; un-previewed items are excluded from the batch with a notice). Keep the soft 10-item warning. |
| **A2** | **Publish needs step-up auth.** A hijacked or left-unlocked admin session can publish everything in one sitting. CSRF tokens don't help against an unattended unlocked laptop on a job site. | Publish (and export-with-sensitive) requires **password re-entry**; re-auth is valid for a short window (e.g., 5 minutes) and is itself audit-logged. Short idle timeout (15 min) on admin sessions generally. |
| **A3** | **"Approve" reversibility is assumed but unspecified.** UX says approve is reversible — reversible to *what*? Back to `pending_review`? Does it notify the other admin? | Pass 5 must define the full state machine with every transition, actor, and inverse: `pending_review → approved → published`, plus `approved → pending_review` (un-approve, logged), `published → approved` (unpublish, logged, cache-invalidated per B4). No transition without a defined inverse except Reject (which is terminal-but-visible). |
| **A4** | **Duplicate-merge path could overwrite live content.** "Replace draft" against an existing **published** FAQ (UX §3.3) is a de facto publish if it edits the live entry. | Merges/replacements against published FAQs create a **new draft revision** that itself must traverse approve → publish. Live content is never edited in place. |
| **A5** | **Presence lock is soft and overridable** (UX §3.3) — fine — but the save-conf

## Pass 4 — skeptic-operations-compatibility

# Stage 4 — Skeptic Review: Operations & Compatibility Critique
**Coastal Cornerstone Construction — Chat Agent Enhancement (Pass 4 of 6)**

**Verdict:** The spine (two-gate publish, additive schema, heuristic classifier) survives scrutiny, and Stage 3 correctly caught the FAQ-emptying migration and the retention leak. But both baselines and the Stage 3 review share a systemic blind spot: **they specify states, not operations.** Nobody owns the retry queue, the migration ledger, the login throttle, or the monthly hygiene loop. There are **six new blockers** below, plus category findings on migration mechanics, duplicate handling, admin confusion, exports, rollback realism, and failure modes. Stage 3's own fixes also introduce un-costed schema and workflow gaps that Pass 5 must absorb.

---

## 1. New Blockers (numbering continues from Stage 3's B1–B5)

| ID | Severity | Finding | Required Fix |
|---|---|---|---|
| **B6** | 🔴 Critical | **SQLite foreign keys are off by default.** Arch §3.4 claims "classifications rows cascade-delete with their messages." That only happens if every connection sets `PRAGMA foreign_keys = ON` **and** the FK is declared `ON DELETE CASCADE`. The existing retention sweep predates these tables and almost certainly deletes messages directly. Result: orphaned classification rows referencing deleted messages — a silent data-integrity failure and a retention-promise violation (classification rows may embed message-derived signals). | Enable FK enforcement per connection (verify the existing app does this — if not, that's a pre-existing bug to log); declare cascades explicitly; **and** make the sweep defensively delete classifications by `message_id` before deleting messages. Add a post-sweep verification query (orphan count must be 0) whose result is surfaced on the Overview card, not buried in logs. |
| **B7** | 🔴 Critical | **Additive columns can still break old code.** "Old code ignores new columns" (Arch §5) is true for `SELECT *` reads but **false for positional writes**: any existing `INSERT INTO faqs VALUES (...)` without an explicit column list fails or misaligns the moment migration 004 lands. Nobody has audited the existing codebase for this. | Pre-migration audit: grep all writes to `faqs`; require named-column inserts everywhere (fix forward if found). Migration rehearsal against an anonymized production dump is a release gate, not a courtesy. |
| **B8** | 🔴 Critical | **No migration ledger, no version floor, untested down-scripts.** The five migrations have no `schema_migrations` tracking table (rerun behavior undefined), no stated SQLite version floor (`DROP COLUMN` in rollback scripts requires ≥3.35.0; older hosts will fail mid-rollback), and no CI harness that runs migrate → rollback → migrate. "Each ships with a tested down-script" is asserted, not mechanized. | Add migration `000_schema_migrations` (ledger: id, applied_at, checksum). Document the SQLite version floor and verify it on the host before Pass 6. CI gate: full up/down/up cycle on a production-shaped fixture. |
| **B9** | 🔴 Critical | **Three state stores, no single lifecycle owner.** An FAQ answer can simultaneously live in `draft_versions` (workspace), `review_queue` (pending), and `faqs` (approved/published) — three tables with three status vocabularies (`pending_review` vs. UX's "In review"; draft workspace has no status at all). Arch and UX use different words for the same states. This guarantees "where did my item go?" confusion for two intermittent, non-technical admins, and makes every transition a multi-table write with no defined transaction boundary. | Pass 5 must collapse this to **one FAQ entity with one status column** as the source of truth; the review queue and draft workspace become **views/filters over that entity**, not separate stores. One canonical status vocabulary used identically in schema, UI copy, and audit log: `draft → in_review → approved_not_public → published` (+ `rejected`, terminal-visible). Every transition is a single-row update, logged. |
| **B10** | 🔴 Critical | **Admin login has no brute-force protection — and the repo is public.** The agent repository stays public, which means the admin login route, session mechanics, and route names are readable by anyone. "Hidden dashboard" is obscurity, not a control; the actual control is auth, and no plan mentions rate limiting, lockout, or login-attempt logging. Two human admins with env-var passwords is a soft target. | Login endpoint: exponential backoff + temporary lockout after N failures, all attempts audit-logged (including failures — the current audit spec only logs successful logins). State plainly in

## Pass 5 — updated-plan-reconcile

# Stage 5 — Reconciled Implementation-Ready Plan
**Coastal Cornerstone Construction — Chat Agent Enhancement (Pass 5 of 6)**

This pass merges Stages 1–4 into a single authoritative specification. Where stages conflicted, the **more conservative** option wins (more human gates, less data retained, simpler schema). All blockers B1–B10 and findings P1–P7, A1–A5 are resolved inline and indexed in §12. **No code is written in this pass. Nothing auto-publishes.**

---

## 1. Contradiction Resolution Summary

| # | Conflict | Resolution (conservative) |
|---|---|---|
| R1 | Three FAQ stores (`draft_versions`, `review_queue`, `faqs`) with three vocabularies (B9) | **One `faq_items` entity, one status column.** Queue and draft workspace become filtered views. `review_queue` table from Arch §5 is **dropped from the plan**; `draft_versions` survives only as the append-only version-history table keyed to `faq_items`. |
| R2 | Migration 004 default `approved` would empty public FAQ (B1) | Backfill existing 50 rows to `published` in the same migration; post-migration count check is a release gate. |
| R3 | "30-day retention" vs. exempt copies in queue/drafts/audit (B2) | Retention policy rewritten (§6): derived copies of sensitive content are scrubbed on source expiry; audit log stores references + truncated previews, never full sensitive bodies. |
| R4 | "Same transaction" publish across DB + agent artifact (B4) | Explicit 5-step pipeline with read-back verification and auto-revert (§4). |
| R5 | Synchronous classifier on public write path (B5) | Fail-open: chat write never depends on classifier; `classification_pending` retry state. |
| R6 | Stage 2 open questions (§9 of UX plan) | Resolved in §9: flag-only duplicates, no email, soft batch warning at 10, rejected items persist collapsed. |
| R7 | Stage 3 A5 (truncated): soft presence lock + save conflict | Soft lock with idle expiry; on conflict, **no silent last-save-wins** — saver is shown a side-by-side and must explicitly choose; both versions retained in history. |
| R8 | Stage 4 B10 (truncated): login hardening | Rate limiting + lockout + failure logging, specified in §5.3; obscurity explicitly disclaimed as a control. |

---

## 2. Canonical Data Model (revised)

### 2.1 Entities

| Table | Purpose | Notes |
|---|---|---|
| `messages` (existing) | Chat capture, 30-day retention | Unchanged schema |
| `classifications` | One label per message, versioned rules | FK `message_id ON DELETE CASCADE`; sweep also deletes defensively (B6) |
| `faq_items` | **Single source of truth** for every FAQ answer: imported drafts, chat-derived candidates, existing 50 | One `status` column (§2.2); `source_type` ∈ {`legacy`, `import`, `chat`}; `source_message_id` nullable soft link; `is_sensitive_derived` flag |
| `faq_versions` | Append-only version history for `faq_items` | Every save = new row; restore = new row copying old body; never updated or deleted |
| `audit_log` | Actor, action, entity, entity_id, timestamps, **references + truncated previews (≤200 chars, sensitive bodies never stored)** | Append-only at application layer |
| `schema_migrations` | Migration ledger: id, applied_at, checksum | New migration 000 (B8) |

### 2.2 Canonical status vocabulary (schema = UI copy = audit log)

```
draft                  — workspace only; never in review, never public
in_review              — in the review queue (imported 100 start here; chat candidates start here)
approved_not_public    — reviewed and approved; UI always renders the words "not public"
published              — live on /faq/ and in /ai/ knowledge
rejected               — terminal but visible; collapsed by default; restorable to in_review
```

Message-level classification labels (unchanged from Arch): `ignore`, `needs_answer`, `faq_candidate`, `sensitive_private`, plus `classification_pending` (B5 retry state).

### 2.3 State machine — every transition, actor, inverse

| Transition | Trigger | Actor | Inverse |
|---|---|---|---|
| → `draft` | Admin creates draft from chat detail | Admin | — |
| `draft → in_review` | "Send to review" | Admin | `in_review → draft` (withdraw, logged) |
| → `in_review` | Importer (100 FAQs) or classifier candidate promotion | System (import) / Admin (promote) | — |
| `in_review → approved_not_public` | "Approve" — requires item opened; **sensitive re-scan runs; match blocks with warning** (P2) | Admin | `approved_not_public → in_review` (un-approve, logged) (A3) |
| `approved_not_public → published` | Publish pipeline §4 — requires step-up re-auth + per-item preview | Admin | `published → approved_not_public` (unpublish, logged, artifact regenerated per §4) |
| `in_review → rejected` | "Reject" (optional reason) | Admin | `rejected → in_review` (restore, logged) |
| any → any on **published** item's content | Edit | Admin | Edits to a published item create a **new draft revision** that must re-traverse approve → publish. **Live content is never edited in place** (A4). |

No transition lacks a defined inverse. No bulk Approve. No bulk Publish without per-item preview (A1). No combined "Approve & Publish" action exists anywhere.

---

## 3. Permissions Matrix (final)

| Capability | Public visitor | Admin (Sri, Ben — identical) |
|---|---|---|
| Use `/ai/`, view `/faq/` | ✅ | ✅ |
| View dashboard, chats, classifications | ❌ | ✅ |
| Reveal `sensitive_private` content | ❌ | ✅ — server-side reveal endpoint, **per-message audit-logged**, re-shields on navigation (P1) |
| Override message classification | ❌ | ✅ (logged) |
| Draft/edit answers, view/restore history | ❌ | ✅ |
| Import, approve, reject, un-approve, restore | ❌ | ✅ (logged) |
| **Publish / unpublish** | ❌ | ✅ — **step-up password re-entry required**, per-item preview required, logged with prior state (A2) |
| Export CSV/JSON (default) | ❌ | ✅ — sensitive excluded |
| Export **with** sensitive | ❌ | ✅ — per-export opt-in (never persisted), typed confirmation, step-up re-auth, logged with row count (P3) |

No role split. Accountability via audit log, which is documented honestly as **accountability between admins, not tamper-proof forensics** against someone with server access (P7).

---

## 4. Publication Gate — Exact Pipeline (resolves B4)

Publish and unpublish use the same pipeline shape:

1. **Preconditions checked:** admin step-up re-authenticated within 5-minute window; every item in the batch has a recorded `previewed_at` by this admin; sensitive re-scan passes (match → item excluded with notice).
2. **Confirm dialog:** lists every item title; batch >10 shows soft warning; un-previewed items are excluded and named.
3. **DB update:** flip `status` (+ `published_at`, `published_by`) in a single SQLite transaction.
4. **Regenerate agent knowledge artifact** (file/cache snapshot read by `/ai/`) from `status = 'published'`.
5. **Read-back verification:** query `/faq/` data source and reload the agent artifact; confirm both reflect the new set. **On any failure: revert the DB flags, regenerate the artifact again, surface an error banner on Overview, and log the incident.** Success is reported only after both surfaces verify.

Rollback = the same pipeline run in reverse. Rollback is only reported complete when **both** surfaces are confirmed reverted. `/faq/` and `/ai/` can never diverge silently — verification is part of the action, not a monitoring afterthought.

---

## 5. Security Controls (resolves B3, B10, P1)

### 5.1 CSRF & session
- Synchronizer-token CSRF on **every** admin POST (classify override, save, approve, reject, publish, unpublish, export, reveal).
- Session cookies `SameSite=Lax`, `HttpOnly`, `Secure`.
- `Origin`/`Referer` check on publish, unpublish, and export-with-sensitive endpoints.
- Admin idle timeout: 15 minutes.

### 5.2 Step-up re-authentication
Required for: publish, unpublish, export-with-sensitive. Password re-entry grants a 5-minute window; each step-up is audit-logged.

### 5.3 Login hardening (B10)
- Exponential backoff + temporary lockout after 5 consecutive failures per account.
- **All** login attempts (success and failure) audit-logged with timestamp and source IP.
- Stated plainly in the operator README: the dashboard is "hidden" by convention only; the public repo exposes route names; **authentication and throttling are the actual controls.**

### 5.4 Sensitive content handling (P1)
- Sensitive message bodies are **withheld server-side**; chat detail renders only the marker.
- Reveal is a separate authenticated GET, audit-logged (actor, message_id, timestamp), never cached (`Cache-Control: no-store`), re-shielded on navigation.

---

## 6. Retention & Privacy Policy — the real one (resolves B2, P4)

| Data | Retention |
|---|---|
| Chat messages | 30 days, hard sweep |
| Classifications | Cascade/deleted with their message; post-sweep orphan check must return 0, result surfaced on Overview (B6) |
| Queue/draft items derived from `sensitive_private` messages | **Purged or redacted when the source message expires** — not merely marked `source_expired` |
| Non-sensitive drafts & FAQ items | Indefinite (they are the product) |
| `is_sensitive_derived` drafts unresolved after 90 days | Purged |
| Audit log | Indefinite, but stores **no sensitive bodies** — references, metadata, truncated previews only |
| Backups | Rotated on a ≤30-day cycle to match live retention. If the host cannot guarantee this, the UI copy and operator docs must say: "30 days in live systems, up to N days in encrypted backups." **One of these two is chosen and written down before Pass 6 — no ambiguity.** |

UI copy in Chats is updated to match the chosen policy exactly. The privacy promise the UI makes is the promise the system keeps.

Additional privacy controls:
- **P2:** sensitive-pattern scan runs at ingest, **again at approve, again at publish**. Matches block the transition with a warning.
- **P5:** the 100-question draft file and importer source live **outside the public repo**; a CI/pre-commit guard blocks committing it. Confirmed before Pass 6.
- **P6:** classifier rule tests use **synthetic fixtures only**; code-review checklist item.

---

## 7. Classifier Spec (resolves B5)

- Heuristic v1, versioned, data-driven rules; no external calls ($1 cap intact).
- Order: `sensitive_private` first (exclusionary) → spam/profanity → `ignore` → unmatched question → `needs_answer` → recurring cluster → `faq_candidate`.
- **Fail-open:** classification runs after the chat write commits. Any exception or timeout → message saved with `classification_pending`; a retry pass (on next admin session or sweep run) reprocesses. Public API behavior is bit-identical whether the classifier is healthy, slow, or dead.
- All regexes audited for catastrophic backtracking; per-message classification time budget enforced.
- Near-duplicate candidates vs. existing FAQs: **flag-only**, inline link to the existing entry; merge is a human decision, and merging against a published FAQ creates a new draft revision (A4).

---

## 8. Migrations (revised, resolves B1, B6, B7, B8)

| # | Change | Notes |
|---|---|---|
| `000_schema_migrations` | Ledger table (id, applied_at, checksum) | All migrations idempotent and tracked |
| `001_classifications` | As Arch §5 + `ON DELETE CASCADE` + `classification_pending` in CHECK | Requires `PRAGMA foreign_keys = ON` per connection — **verify existing app; if absent, log as pre-existing bug and enable** |
| `002_faq_items` | Single FAQ entity (replaces old 003 review_queue); `status` CHECK with canonical vocabulary | — |
| `003_faq_versions` | Append-only history (renamed from draft_versions) | — |
| `004_migrate_existing_faqs` | Copy existing 50 FAQs into `faq_items` with `status='published'`, `source_type='legacy'`; import 100 drafts with `status='in_review'`, `source_type='import'` (idempotent, dedupe on question hash) | **Release gate: public FAQ count before == after** |
| `005_audit_log` | As Arch §5, minus full-body storage | — |

**Pre-migration gates:**
- **B7:** grep all writes to `faqs`; named-column inserts required everywhere; fix forward any positional `INSERT`.
- **B8:** document SQLite version floor (≥3.35.0 if any down-script uses `DROP COLUMN`); verify on host; CI runs full up → down → up cycle on a production-shaped (anonymized) fixture.
- Migration rehearsal against an anonymized production dump is a **release gate**, not a courtesy.

---

## 9. Resolved Open Questions (from Stage 2 §9)

1. **Duplicate handling:** flag-only; merge is manual; merges against published items create new draft revisions.
2. **Email/digest nudges:** **No.** Overview card only — no email infrastructure ($1 cap, operational simplicity).
3. **Batch publish limit:** soft warning above 10; no hard cap; per-item preview requirement stands regardless of batch size.
4. **Rejected item expiry:** persist indefinitely, collapsed by default; restorable to `in_review`.

---

## 10. UX Deltas from Stage 2 (consequences of R1/B9)

- **Review Queue and Drafts are filters over `faq_items`**, not separate stores. Nav becomes: Overview · Chats · Review Queue (`in_review`) · Drafts (`draft`) · Approved — not public · Published · Activity · Exports. "Where did my item go?" is answered by the status chip, which uses the exact §2.2 vocabulary everywhere.
- Import progress indicator ("47 of 100 reviewed") counts `source_type='import'` items still `in_review`.
- "Original chat expired" marker appears only on **non-sensitive** items whose source message aged out; sensitive-derived items are gone per §6.
- Save-conflict flow (R7): soft presence lock ("Ben is editing"), idle-expiring; on conflict, side-by-side chooser, both versions kept.
- Everything else in Stage 2 (breadcrumbs with strict public/private separation, generic 404s, click-to-reveal now server-enforced, WCAG 2.2 AA plan, clickable rows, retention copy) stands, with copy updated to §6.

---

## 11. Operations (Stage 4's "states, not operations" gap)

| Loop | Owner mechanism |
|---|---|
| Retention sweep | Existing job, extended: delete classifications by message_id → delete messages → scrub sensitive-derived items → orphan-count verification → result on Overview card |
|
