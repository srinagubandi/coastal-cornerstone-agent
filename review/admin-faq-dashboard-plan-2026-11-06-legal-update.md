# Admin FAQ, Dashboard, Terms and Privacy Re-plan

Date: 2026-11-06

## Restarted-plan updates

- Restarted the full six-stage planning sequence with the approved Terms and Privacy work included.
- Added a dedicated legal-copy implementation loop for `/privacy/` and `/terms/`, using the actual site behavior and official Florida sources.
- Kept the public FAQ/AI publication gate separate from legal-page publishing; FAQ content still requires preview, step-up authentication, itemized confirmation, audit, read-back, and rollback.
- Terms/Privacy copy is treated as a lawyer-review draft: plain language, no invented claims, no warning banner, and no claim of lawyer approval.
- Preserved append-only chat capture, four review states, 100-question non-runtime queue, admin answer history, breadcrumbs, private dashboard boundary, 30-day retention, public API/MCP contracts, and $1/month runtime cap.
- Reserved six coding loops and two final Kimi testing/fix loops, plus the required Claude final release review before production deployment.

## Consolidated restarted plan

# Stage 6 — Code Boundaries & Release Sequence
**Coastal Cornerstone Construction — Question-Intelligence Dashboard + Public Site**

*Planning artifact only. No code is written in this document. This stage converts the Stage 5 reconciled baseline (D1–D20, BQ-1–BQ-7) into six bounded coding loops (K1–K6), two test/fix loops (T1–T2), and one mandatory final release review (R1) before any production deployment. Manual public FAQ publication approval remains an explicit hard gate in every loop that touches the publish path. Terms/Privacy work remains limited to the approved two-page draft update and carries its own human publish gate (D16).*

**Preconditions before K1 starts:**
1. Stage 5 §9 truncation note resolved: any Stage 3/Stage 4 findings beyond the truncation points are appended and reconciled. If none exist, that is recorded as a decision.
2. BQ collection launched in parallel (owner task, not a coding loop). BQ answers gate specific loops per §3 — they do not gate K1.
3. Staging environment exists with a copy of the production database (required by D8, D18).

---

## 1. Loop Architecture & Sequencing Rationale

```
K1 (data foundation) ──► K2 (capture/classification) ──► K3 (queue/import)
      │                          │                            │
      └──────────────────────────┴────────────────────────────▼
                                                    K4 (publish/versioning)
                                                             │
                                                    K5 (exports/retention)
                                                             │
                                                    K6 (UX + legal pages)
                                                             │
                                              T1 (functional/contract) ──► T2 (rollback/security/legal)
                                                             │
                                                    R1 (Claude release review)
                                                             │
                                                    Production deploy (maintenance window)
                                                             │
                                                    Post-deploy verification
                                                             │
                                                    Legal-page publish (human action, D16 — separate from deploy)
```

**Sequencing logic:**
- K1 first: every later loop writes to tables K1 creates, and D8/D18 make migration discipline the foundation everything else is rehearsed against.
- K2 before K3: classification labels (and the D13 suspension trigger) must exist before queue items can derive from conversations.
- K3 before K4: publish operates on queue items; versioning (D2) operates on what publish produces.
- K5 after K4: export scope (D4) and sweeper scope (D17) are defined against the final table set.
- K6 last among coding loops: it is presentation-only over stabilized behavior, plus Loop H legal pages, which depend on verified facts (BQ-1–BQ-5) that the earlier loops' build time allows the owners to gather.
- **Strict boundary rule:** later loops may not reopen earlier loops' merged work except through a logged change request approved by Sri or Ben. Fixes discovered in T1/T2 are the only exception, and they are scoped to the loop that introduced the defect.

---

## 2. Global Boundaries — Binding on Every Loop

**No loop may ever:**
1. Change public API/MCP contracts, agent safeguards, or guardrails (hard constraint).
2. Introduce auto-publish, scheduled publish, or batch publish of FAQs or legal pages (Loop D / D16).
3. Add delete functionality to the admin UI (D20). The retention sweeper is the only deletion path, and it touches chat records only (D17).
4. Add an export preview (D6) or expand export scope beyond sessions/messages/classifications (D4).
5. Add new public routes, a warning banner, or any behavior change under cover of the legal-page work (H-4).
6. Send `Sensitive-private` content to any external provider (D1).
7. Introduce credentials, secrets, or connection strings into the repository (hard constraint).
8. Rewrite main history; all work lands as additive, reviewable commits (hard constraint).
9. Add any paid service, dependency with recurring cost, or infrastructure that threatens the $1/month runtime cap. OpenRouter call volume stays bounded by D1 (non-sensitive items only).
10. Claim or imply legal review/approval anywhere in copy, UI, or commit messages.

**Every loop must:**
- Ship migrations per D8 (ordered, idempotent, tested down-path, `schema_migrations` row, pre-migration file backup).
- Emit the audit events its features define, into `audit_log` (append-only, sweeper-exempt per D17).
- Re-run the capture-completeness gate after any migration (F-4.5).
- Keep capture fire-and-forget: no loop may put capture on the critical path of a chat response (D7).

---

## 3. The Six Coding Loops

### K1 — Data Foundation & Operational Safety
**Depends on:** staging + production DB copy. **Blocked by:** nothing. **Informs:** BQ-5 (metadata enumeration happens here as a read-only inventory, not a schema change).

| | |
|---|---|
| **In scope** | `schema_migrations` table + migration runner convention (D8); additive migrations for `classifications`, `faq_drafts`, `answer_history`, `faq_approved` (versioning columns per D2), `legal_pages`, `audit_log`; WAL mode enablement or documented exception (D7); pre-migration file-backup procedure with versioned backup location (D8); backup-retention mechanism chosen and implemented per D9 (≤30-day lifetime, chat-table exclusion, or key destruction — one, recorded as a decision); read-only inventory of actual `sessions.metadata` contents to answer BQ-5 |
| **Out of scope** | Any classification logic, any UI, any queue/publish/export behavior, any metadata schema change (minimization, if BQ-5 warrants it, is a separate approved migration in K6 at the latest, before Privacy §2 is finalized) |
| **Deliverables** | Migrations applied on staging; backup/restore procedure documented; BQ-5 inventory recorded |
| **Exit gate** | Migration apply → revert → reapply cycle passes on the staging copy (first half of D18(d)); backup file verified restorable; capture-completeness gate re-run green post-migration |

### K2 — Capture Hardening & Classification
**Depends on:** K1. **Blocked by:** BQ-7 (owner confirmation of D1 flow) — build may proceed on the D1 default; if BQ-7 comes back as "LLM classifies all content," the flow changes here and Privacy §4/§5 copy rules change in K6.

| | |
|---|---|
| **In scope** | Fire-and-forget capture writes with short timeout + logged failure path (D7); local rules/heuristics classifier; OpenRouter-assisted classification for non-sensitive-labeled content only (D1); human-only re-classification path for `Sensitive-private`; the four labels (`Ignore` / `Needs answer` / `FAQ candidate` / `Sensitive-private`); D13 trigger: re-label to `Sensitive-private` auto-suspends linked drafts and blocks their publish path, logged |
| **Out of scope** | Queue UI, promote action, import (K3); any publish logic (K4); snippet masking presentation (K6 — but K2 must store labels so masking is possible) |
| **Deliverables** | Classification pipeline per D1; audit events for classification and re-classification; suspension trigger wired and logged |
| **Exit gate** | Test evidence: sensitive-labeled content never reaches OpenRouter (logged request inspection); capture failure during a chat leaves the chat response unaffected; D13 suspension fires on re-label |

### K3 — Draft Queue, Import & Promote
**Depends on:** K2. **Blocked by:** BQ-6 (draft-file format → field mapping) for the import path only; promote path can proceed in parallel.

| | |
|---|---|
| **In scope** | `faq_drafts` state machine per D3 (`New` → `In progress` → `Ready for approval` → `Published` / `Rejected`, plus `Possible duplicate`, `Suspended — source reclassified`); transactional, idempotent 100-draft import (single transaction, `source = 'draft_file'` + stable identifier, re-import skip, authenticated + audit-logged — D10); explicit admin promote action from `FAQ candidate` conversations (D19); duplicate flagging at import and promote against `faq_approved` and `faq_drafts` (D11); conflict-checked saves with stale-version rejection + "changed by {admin} at {time}" notice (D12); append-only `answer_history` writes |
| **Out of scope** | Publish confirmation and versioning transitions (K4); visual polish of queue screens (K6 — K3 ships functional, plain UI) |
| **Deliverables** | Working queue with all entry paths; import audit event (actor, row count, file identifier); conflict detection demonstrable with two concurrent sessions |
| **Exit gate** | Import of the real 100-row file on staging: exactly 100 rows, re-import adds zero; duplicate flags appear where expected; concurrent-edit test shows rejection, never silent overwrite |

### K4 — Approval, Publish & Versioning (Manual Gate Loop)
**Depends on:** K3. **Blocked by:** nothing.

| | |
|---|---|
| **In scope** | D2 versioning: published FAQs immutable; edit creates linked draft; approval publishes version *n+1* superseding *n*; one live version per identity; rollback = re-publish *n*; publish confirmation showing exact text, last editor, last edit time, and duplicate warning with forced **Replace / Publish as separate** choice (D11, D12); publish preconditions: not `Suspended`, duplicate choice made (D13, D11); state-dependent destructive actions, disabled-with-reason (D20); confirmation copy: "This will make the answer visible on the public FAQ page" (D3); unpublish path; all transitions audit-logged with approver, timestamp, version |
| **Out of scope** | Legal-page publish (K6 — same gate pattern, separate implementation per D16); any change to how `/faq/` renders beyond reading the single live version |
| **Deliverables** | The complete manual publish gate; version history with restore; audit trail for every transition |
| **Exit gate** | On staging: publish → visible on `/faq/`; unpublish → absent; version *n+1* publish → restore *n* → `/faq/` shows *n* (rehearsal input to D18(a)/(b)); no code path exists that publishes without the authenticated confirmation |

### K5 — Exports & Retention
**Depends on:** K4 (final table set). **Blocked by:** nothing.

| | |
|---|---|
| **In scope** | CSV/JSON export scoped to sessions, messages, classifications only (D4); CSV formula-injection sanitization (D5); no preview — generate + download + log (D6); `Sensitive-private` excluded by default with the distinct typed/re-checked inclusion control, logged as `export_sensitive_included` (D15, F-4.16); export UI handling notice: file not covered by 30-day automatic deletion (D15); read-only export queries (D7); retention sweeper scoped to chat records only — sessions, messages, their classifications — at 30 days, with sweeper runs themselves audit-logged (D17); verification that `audit_log`, `faq_*`, `answer_history`, `legal_pages`, `schema_migrations` are unreachable by the sweeper |
| **Out of scope** | Any content-backup export of drafts/FAQs (explicitly future scope, D4); backup-infrastructure changes beyond what K1's D9 mechanism requires |
| **Deliverables** | Export flow with friction and logging; sweeper with scoped unit evidence |
| **Exit gate** | Exported CSV opened in a spreadsheet shows sanitized cells; sensitive inclusion requires the distinct control and logs it; sweeper dry-run report lists only chat-record rows; export queries hold no write lock (WAL verified under concurrent capture) |

### K6 — Admin UX & Legal Pages (Loop H)
**Depends on:** K3–K5 (presentation layer over stabilized behavior). **Blocked by:** BQ-1, BQ-2, BQ-3, BQ-4, BQ-5 for legal drafting; UX portion is unblocked.

| | |
|---|---|
| **In scope — UX** | Snippet & breadcrumb hygiene (D14): metadata-only rows until classified; `Sensitive-private` rows show "content hidden — open to view"; full-text tooltips only on FAQ/draft question fields at `Ready for approval`+; chat-derived drafts labeled `Draft {id}`; conversation breadcrumbs use opaque ID; clickable conversation rows → full chat detail; breadcrumbs per Stage 2 §B; conflict-notice UI (D12); publish-confirmation presentation (content defined in K4); Stage 2 §A.3 presentation items minus export preview. **Presentation only — zero behavior changes.** |
| **In scope — Legal (Loop H)** | Draft updated `/terms/` and `/privacy/` per H-1/H-2 rules: verified facts only (BQ-1–BQ-5); named providers (Projul, Railway, OpenRouter, Resend, Manus) only as actually used; 30-day deletion language scoped to "chat records **in our systems**" including

## Pass 1 — initial-architecture

# Stage 1 — Initial Architecture
**Coastal Cornerstone Construction — Question-Intelligence Dashboard + Public Site**
*Planning artifact only. No code, no production changes. Manual FAQ publication approval remains explicit. Terms/Privacy work is limited to the approved draft update.*

---

## 1. Scope Baseline (what this architecture must support)

**Existing (current state):**
- Chat agent captures sessions/messages with 30-day retention (SQLite).
- Private admin dashboard: Overview/Chats, chat detail view, CSV/JSON exports, 50 approved FAQs, 100-question draft FAQ file.
- Admin login for Sri and Ben.
- Public site routes: `/faq/`, `/ai/`, `/privacy/`, `/terms/`.

**Approved build scope:**
1. Capture every chat entry (no sampling/drops).
2. Classification: `Ignore`, `Needs answer`, `FAQ candidate`, `Sensitive-private`.
3. Authenticated admin draft/edit answers with full edit history.
4. Load 100 drafts into a review queue.
5. Clickable conversation rows → full chat detail; breadcrumbs; general UI/UX improvements.
6. **Manual approval/publish gate before any public FAQ change.**
7. **Legal-copy loop:** draft and publish updated Florida-oriented `/terms/` and `/privacy/` reflecting *actual* behavior only.

**Hard constraints (carried through every loop):** preserve public API/MCP contracts and safeguards; 30-day retention; SQLite compatibility; auditability; rollback; no credentials in repo/logs; ≤ $1/month runtime; non-rewritten main history; official Florida sources only for legal facts; no lawyer-approval claims; no invented facts; no behavior changes; no separate warning banner; no indemnity language conflicting with actual data flows.

---

## 2. System Overview

```
PUBLIC SURFACE                          PRIVATE SURFACE
┌─────────────────────────┐             ┌──────────────────────────────┐
│ /ai/ chat agent         │             │ Admin dashboard (Sri, Ben)   │
│ /faq/ (published FAQs)  │             │  ├─ Overview / Chats         │
│ /privacy/  /terms/      │             │  ├─ Chat detail (clickable   │
│ Projul contact form     │             │  │   rows, breadcrumbs)       │
│ phone / text / email    │             │  ├─ Review queue (100 drafts)│
└───────┬─────────────────┘             │  ├─ Answer draft/edit + hist.│
        │                               │  ├─ FAQ approval/publish     │
        ▼                               │  └─ CSV/JSON export          │
┌─────────────────────────┐             └───────────┬──────────────────┘
│ Capture pipeline        │                         │
│ (append-only, every     │                         │
│  chat entry)            │                         │
└───────┬─────────────────┘                         │
        ▼                                           ▼
┌──────────────────────────────────────────────────────────┐
│ SQLite (single store)                                    │
│  sessions · messages · classifications · faq_drafts ·    │
│  faq_approved · answer_history · audit_log · legal_pages │
└──────────────────────────────────────────────────────────┘
        ▲ retention sweeper (30-day purge, logged)
EXTERNAL PROVIDERS (unchanged contracts):
Railway (hosting) · OpenRouter (LLM) · Resend (email) · Manus (agent runtime)
```

---

## 3. Loop Boundaries

Each loop has explicit inputs, outputs, an owner, and a gate. Loops are isolated so a failure or rollback in one does not corrupt another.

### Loop A — Capture
- **Input:** every chat entry on `/ai/` (user + agent messages, session metadata).
- **Output:** append-only rows in `sessions`/`messages`; audit log entry.
- **Boundary:** write-only from the public side; no classification, no deletion, no editing here. Must not alter the public API/MCP request/response contract — capture is a side effect, never a blocker (capture failure must not break the chat response; it must log and alert).
- **Gate:** capture completeness check (every message row accounted for) before Stage 2 closes.

### Loop B — Classification
- **Input:** captured messages.
- **Output:** one label per message/conversation: `Ignore` | `Needs answer` | `FAQ candidate` | `Sensitive-private`.
- **Boundary:** classification never deletes or hides data from admins; `Sensitive-private` items are excluded from FAQ candidacy and exports-by-default, and flagged for the retention sweeper like everything else (no extended retention).
- **Gate:** labels are reversible (re-classify allowed, history kept in `audit_log`).

### Loop C — Answer Drafting (admin)
- **Input:** `Needs answer` / `FAQ candidate` items; the 100-question draft file.
- **Output:** draft answers in `faq_drafts`; every edit appended to `answer_history` (who — Sri or Ben — what, when, prior value).
- **Boundary:** drafts are never public. Editing a draft never touches `faq_approved`.
- **Gate:** authentication required; history is append-only (no rewrite of prior versions).

### Loop D — FAQ Review & Publish (**manual approval — explicit**)
- **Input:** drafts from Loop C.
- **Output:** on explicit human approval, a row moves to `faq_approved` and `/faq/` content updates.
- **Boundary:** **no auto-publish, no batch-publish without per-item or explicitly-confirmed-batch human action.** Publish and unpublish are both supported (rollback = unpublish/restore prior approved version).
- **Gate:** approval event recorded in `audit_log` with approver identity and timestamp. This gate is a hard stop: implementation cannot proceed past it without a recorded human action.

### Loop E — Export
- **Input:** captured/classified data.
- **Output:** CSV/JSON downloads (existing feature, preserved).
- **Boundary:** authenticated only; exports respect `Sensitive-private` handling; export events logged.

### Loop F — Retention
- **Input:** all records older than 30 days.
- **Output:** purge + audit log entry (counts, not content).
- **Boundary:** 30-day window is fixed by constraint; applies uniformly, including `Sensitive-private`. Purge is the only deletion path. Legal pages and approved FAQs are content, not chat records, and are out of this loop's scope.

### Loop G — UI/UX
- **Input:** dashboard screens.
- **Output:** clickable conversation rows → full chat detail; breadcrumbs on all admin detail views; general usability improvements.
- **Boundary:** presentation-only; no data-model or contract changes permitted inside this loop.

### Loop H — Legal-Copy (dedicated loop for `/privacy/` and `/terms/`)
- **Input:** current pages; verified inventory of actual site behavior; official Florida sources for factual legal context.
- **Output:** updated draft pages → published pages (single approved update).
- **Boundary:** strictly limited to the approved draft update of these two pages. No other legal pages, no banners, no behavior changes, no new data flows introduced to "match" the copy — copy must match the system, not the reverse.
- **Gate:** factual-alignment checklist (Section 5) must pass before publish; publish is one reversible commit with rollback to prior page versions.

---

## 4. Data Model Sketch (SQLite-compatible, no code)

| Table | Purpose | Key fields |
|---|---|---|
| `sessions` | chat sessions | id, started_at, metadata |
| `messages` | every chat entry | id, session_id, role, content, created_at |
| `classifications` | labels + history | message/conversation id, label, labeled_by, labeled_at |
| `faq_drafts` | review queue (incl. 100 drafts) | id, question, draft_answer, status, source |
| `faq_approved` | published FAQs (50 existing + newly approved) | id, question, answer, approved_by, approved_at, version |
| `answer_history` | append-only edit history | draft_id, editor, old_value, new_value, edited_at |
| `audit_log` | all mutations, approvals, purges, exports, publishes | actor, action, target, timestamp |
| `legal_pages` | versioned page content for `/privacy/`, `/terms/` | slug, version, content, published_at, published_by |

All tables: plain SQLite types, no extensions, migrations are additive and reversible.

---

## 5. Legal-Copy Loop — Detail (Loop H)

**Factual inventory the copy must match (approved facts only):**
- Contact via Projul form; direct calls, texts, email.
- Public FAQ agent on `/ai/`; chat records retained 30 days, then deleted.
- Providers: Railway (hosting), OpenRouter (LLM processing), Resend (email delivery), Manus (agent runtime).
- Cookies/analytics/tracking: state the *actual current status* — to be verified in Stage 2 before drafting; if none, say so plainly rather than copying boilerplate.
- Marketing communications: describe only what is actually sent and how to opt out.
- Intellectual property, third-party links, service limits, project agreements (separate contracts govern construction work), incident-response language (plain description of what happens if a data incident occurs — no invented SLAs).

**Rules for this loop:**
1. Florida-oriented framing sourced only from current official Florida sources (e.g., Florida Statutes via Online Sunshine, Florida Bar public resources) for factual context — citations optional, accuracy mandatory.
2. No claim of legal review or approval. The user's statement that a lawyer will review later is an internal note only — it does **not** appear on the pages.
3. No invented facts (no fake addresses, registration numbers, response-time promises, or security certifications).
4. No indemnity, warranty, or liability language that conflicts with the actual data flows above.
5. Plain, professional tone; no separate warning banner; no dark-pattern disclosures.
6. Versioned publish with one-step rollback to the prior page version.

---

## 6. Constraint → Mechanism Ledger

| Constraint | Mechanism |
|---|---|
| Preserve public API/MCP contracts | Capture is side-effect-only; contract tests in Stage 2 gate |
| Safeguards preserved | No changes to agent guardrails in any loop |
| 30-day retention | Loop F sweeper, logged, uniform |
| SQLite compatibility | Additive reversible migrations only |
| Auditability | `audit_log` on every mutation/approval/purge/export/publish |
| Rollback | Versioned FAQs and legal pages; unpublish/restore paths; per-loop isolation |
| No credentials | Existing auth unchanged; secrets stay in environment, never in repo/logs/exports |
| ≤ $1/month runtime | No new always-on services; classification batched; SQLite stays |
| Non-rewritten main history | Append-only history tables; migrations additive |
| Manual FAQ approval | Loop D hard gate, logged approver |
| No lawyer-approval claims | Copy rule in Loop H |
| No invented facts / no behavior change | Factual-alignment checklist before legal publish |

---

## 7. Implementation Gates (must pass before any production change)

1. **Contract gate:** public API/MCP behavior identical before/after (test evidence).
2. **Capture gate:** 100% of chat entries captured in staging.
3. **Approval gate:** FAQ publish path proven to require a recorded human action.
4. **Retention gate:** purge verified at 30 days in staging.
5. **Rollback gate:** FAQ unpublish and legal-page restore demonstrated.
6. **Legal-alignment gate:** Section 5 checklist signed off against verified behavior (including actual cookie/analytics status).
7. **Cost gate:** projected runtime ≤ $1/month.

---

## 8. Non-Goals (explicitly out of scope)

- Auto-publishing FAQs; changing agent behavior or safeguards; extending/reducing retention; new providers; new public routes; cookie-consent tooling or banners; migrating off SQLite; rewriting git history; any legal copy beyond the two approved pages.

## 9. Open Questions for Stage 2

1. Verified current status of cookies/analytics/tracking (needed before legal drafting).
2. Exact current marketing-communication behavior (what is sent, via Resend?, opt-out mechanism).
3. Whether classification runs inline (async batch preferred for cost) and which OpenRouter model fits the budget.
4. Confirm the 100-draft file format for queue import mapping.

**Stage 1 complete. Awaiting go-ahead to proceed to Stage 2 planning; no code written, no production changes made.**

## Pass 2 — initial-product-ux-and-legal

# Stage 2 — Initial Product, UX & Legal Baseline
**Coastal Cornerstone Construction — Question-Intelligence Dashboard + Public Site**
*Planning artifact only. No code, no production changes. Manual FAQ publication approval remains explicit. Terms/Privacy work remains limited to the approved draft update of those two pages.*

This stage defines three independent baselines: (A) dashboard workflow, (B) navigation & breadcrumbs, (C) plain-language Terms/Privacy information architecture. Each maps back to Stage 1 loops and gates.

---

## A. Dashboard Workflow Baseline (Loops B, C, D, E, G)

### A.1 Information architecture (admin)

```
Dashboard (authenticated: Sri, Ben)
├── Overview                    → counts, recent activity, queue health
├── Chats                       → conversation list (clickable rows)
│   └── Chat detail             → full transcript + classification controls
├── Review Queue                → 100 imported drafts + new FAQ candidates
│   └── Draft detail            → question, draft answer, edit, history
├── FAQs (Approved)             → 50 published items, versioned
│   └── FAQ detail              → view, edit-as-new-draft, unpublish
├── Exports                     → CSV/JSON download (logged)
└── Audit Log (read-only)       → mutations, approvals, purges, publishes
```

### A.2 Core workflows (numbered, gate-annotated)

**W1 — Triage a conversation**
1. Admin opens **Chats**; rows show: started time, message count, current classification, snippet.
2. Click row → **Chat detail** (full transcript, chronological, role-labeled).
3. Admin sets/changes classification: `Ignore` | `Needs answer` | `FAQ candidate` | `Sensitive-private`.
4. Re-classification is allowed; every change appends to `audit_log` (actor, old label, new label, timestamp). *(Loop B — reversible labels.)*
5. `Sensitive-private` items: excluded from FAQ candidacy and default exports; still subject to the same 30-day purge. No special retention.

**W2 — Work the review queue**
1. **Review Queue** lists the 100 imported drafts (source: draft file) plus any `FAQ candidate` items promoted from W1.
2. Queue item states: `New` → `In review` → `Ready for approval` → (`Approved` | `Rejected`).
3. Open item → **Draft detail**: question, current draft answer, source conversation link (if any).
4. Edit answer → save. Every save appends to `answer_history` (editor identity, prior value, new value, timestamp). History is viewable inline; prior versions are never overwritten. *(Loop C.)*
5. Mark `Ready for approval` — this is a *readiness signal only*, not publication.

**W3 — Approve and publish a FAQ (HARD MANUAL GATE — Loop D)**
1. From a `Ready for approval` draft, admin clicks **Approve & publish**.
2. Confirmation step shows the exact question + answer text that will go public.
3. On explicit confirm: row created/versioned in `faq_approved`; `/faq/` updates; `audit_log` records approver (Sri or Ben), timestamp, version.
4. **No auto-publish. No scheduled publish. Batch publish, if ever offered, requires per-item confirmation or an explicitly confirmed batch action — each item still logged individually.**
5. **Rollback path:** `Unpublish` (removes from `/faq/`, keeps record) or `Restore prior version` (re-publishes earlier approved version). Both are logged. *(Rollback gate, Stage 1 §7.5.)*

**W4 — Export**
1. **Exports** screen: choose CSV or JSON, date range, include/exclude `Sensitive-private` (excluded by default).
2. Download; event logged (actor, format, range, row count). *(Loop E.)*

**W5 — Audit review**
1. **Audit Log** is read-only, filterable by actor/action/date. No edit or delete controls exist in UI. *(Auditability constraint.)*

### A.3 UX improvement list (Loop G — presentation-only)

| # | Improvement | Constraint check |
|---|---|---|
| 1 | Clickable conversation rows → chat detail | No data-model change |
| 2 | Breadcrumbs on all detail views (see §B) | Presentation-only |
| 3 | Classification badge + one-click re-label on chat detail | Writes to existing classification loop only |
| 4 | Queue filters: status, source (import vs. chat), editor | Query-only |
| 5 | Inline answer-history accordion on draft detail | Read-only rendering of `answer_history` |
| 6 | Confirmation dialog on publish/unpublish showing exact text | Supports manual-approval gate |
| 7 | Empty-state copy on each screen (what it is, what to do next) | Copy only |
| 8 | Consistent primary/secondary/destructive button hierarchy (destructive = unpublish, reject) | Presentation-only |
| 9 | "Back to list" preserves filters/scroll | Client-side state only |
| 10 | Sensitive-private items visually flagged, never shown in export preview by default | Reinforces Loop B boundary |

**Explicitly not in UX scope:** changes to agent guardrails, public chat behavior, retention, auth mechanism, or any new always-on service (cost cap).

---

## B. Navigation & Breadcrumbs Baseline

### B.1 Admin breadcrumbs (pattern: `Dashboard / Section / Item`)

| View | Breadcrumb trail |
|---|---|
| Overview | `Dashboard` |
| Chats | `Dashboard / Chats` |
| Chat detail | `Dashboard / Chats / Conversation {id or date}` |
| Review Queue | `Dashboard / Review Queue` |
| Draft detail | `Dashboard / Review Queue / Draft {id}` |
| Draft detail (from a chat) | `Dashboard / Chats / Conversation {id} / Linked Draft {id}` |
| Approved FAQs | `Dashboard / FAQs` |
| FAQ detail | `Dashboard / FAQs / {question, truncated}` |
| Exports | `Dashboard / Exports` |
| Audit Log | `Dashboard / Audit Log` |

Rules: every crumb except the current page is a link; truncated labels carry full text in tooltip/title; breadcrumbs reflect the path taken (chat-originated drafts show the chat trail).

### B.2 Public breadcrumbs

| Page | Trail |
|---|---|
| `/faq/` | `Home / FAQ` |
| `/ai/` | `Home / AI Assistant` |
| `/privacy/` | `Home / Privacy` |
| `/terms/` | `Home / Terms` |

Public breadcrumbs are static, single-level, and add no tracking parameters. No new public routes are introduced.

---

## C. Terms & Privacy Information Architecture (Loop H)

*Draft structure only. Final copy is written in a later stage, after the factual-alignment checklist passes. Florida-oriented framing sourced only from current official Florida sources (e.g., Florida Statutes via Online Sunshine). No lawyer-review claims anywhere. Plain, professional tone. No separate warning banner.*

### C.1 `/privacy/` — section outline

| # | Section | Content rule (must match verified behavior) |
|---|---|---|
| 1 | Introduction / who we are | Business name; contact route. No invented addresses or registration numbers. |
| 2 | What we collect | (a) Contact details submitted via the Projul form; (b) direct calls, texts, emails; (c) chat messages sent to the `/ai/` assistant. Nothing beyond this list. |
| 3 | How we use it | Respond to inquiries, provide estimates/project communication, improve FAQ content. No invented uses. |
| 4 | The AI assistant & chat records | Plain statement: chats are processed by third-party LLM infrastructure and stored for **30 days**, then deleted. No extended-retention carve-outs. |
| 5 | Service providers | Named: **Railway** (hosting), **OpenRouter** (AI processing), **Resend** (email delivery), **Manus** (agent runtime), **Projul** (contact form). Each described by function only. |
| 6 | Cookies, analytics & tracking | **BLOCKED — Stage 1 Open Question 1.** State the verified actual status. If none: say so plainly. No boilerplate copied in anticipation. |
| 7 | Marketing communications | **BLOCKED — Stage 1 Open Question 2.** Describe only what is actually sent, via what channel, and the actual opt-out method. |
| 8 | Data sharing | No sale of personal information (only if true — verify); sharing limited to the providers in §5 as needed to operate the site. |
| 9 | Data retention | 30 days for chat records; contact/project records per actual practice (verify before drafting — do not invent a period). |
| 10 | Security & incident response | Plain description of what happens if a data incident occurs (notify affected individuals consistent with applicable Florida law — factual framing from official sources only). **No invented SLAs, certifications, or guaranteed response times.** |
| 11 | Your choices | Opt out of marketing; request deletion of contact info via stated contact route. Only mechanisms that actually exist. |
| 12 | Third-party links | Not responsible for third-party sites' practices. |
| 13 | Children's privacy | Site not directed at children (standard, factual). |
| 14 | Changes to this policy | How updates are posted; "last updated" date. |
| 15 | Contact | Actual contact route only. |

### C.2 `/terms/` — section outline

| # | Section | Content rule |
|---|---|---|
| 1 | Acceptance of terms | Using the site = acceptance. Plain statement. |
| 2 | Who we are / site purpose | Informational site + AI FAQ assistant + contact routes for a Florida construction business. |
| 3 | The AI assistant | Informational only; answers may be incomplete or inaccurate; not a quote, contract, or professional advice; direct contact for project specifics. **No disclaimer that overreaches into indemnity conflicting with actual data flows.** |
| 4 | No contract via website | Estimates, scopes, and construction work are governed by **separate written project agreements**; website/chat content does not create a contract. |
| 5 | Service limits | Services offered in the business's actual Florida service area (verify — do not invent counties); availability may change. |
| 6 | Intellectual property | Site content © Coastal Cornerstone Construction; no reproduction without permission. Standard, factual. |
| 7 | Third-party links & embedded services | Projul form and linked sites governed by their own terms. |
| 8 | Acceptable use | No misuse of the chat assistant, no unlawful use, no scraping/abuse. Proportionate, plain. |
| 9 | Disclaimers & limitation of liability | Standard "as is" framing for website content; **must not promise or disclaim anything inconsistent with the actual data practices described in `/privacy/`**; no indemnity demands on users beyond lawful, plain scope. |
| 10 | Governing law | Florida, United States. (Factual, Florida-oriented per approved scope.) |
| 11 | Changes to these terms | Posting updates; "last updated" date. |
| 12 | Contact | Actual contact route only. |

### C.3 Drafting rules (carried from Stage 1 §5, restated as checklist)

1. ☐ Cookie/analytics/tracking status **verified** before §6 is drafted.
2. ☐ Marketing-communication behavior **verified** before §7 is drafted.
3. ☐ Every provider named actually in use; every data flow described actually exists.
4. ☐ No invented addresses, registration numbers, certifications, SLAs, or response times.
5. ☐ No claim or implication of legal review/approval on the pages.
6. ☐ No indemnity/warranty/liability language conflicting with actual data flows.
7. ☐ Florida factual context sourced from current official Florida sources only.
8. ☐ Plain, professional tone; no warning banner; no dark patterns.
9. ☐ Both pages versioned in `legal_pages`; publish is one reversible commit; one-step rollback to prior versions demonstrated before publish. *(Legal-alignment gate + rollback gate.)*

---

## D. Traceability — Stage 2 → Stage 1 Gates

| Stage 2 item | Gate it feeds (Stage 1 §7) |
|---|---|
| W3 publish workflow + confirmation dialog | #3 Approval gate |
| Unpublish / restore-prior-version paths | #5 Rollback gate |
| W4 export defaults (Sensitive-private excluded) | #1 Contract/safeguards, auditability |
| Breadcrumbs & UX list (presentation-only) | #1 Contract gate (no contract surface touched) |
| C.1/C.2 outlines + C.3 checklist | #6 Legal-alignment gate |
| No new services anywhere in §A–C | #7 Cost gate |

---

## E. Open Questions Carried Into Stage 3 (blocking items marked)

1. **[BLOCKS legal drafting]** Verified cookies/analytics/tracking status.
2. **[BLOCKS legal drafting]** Actual marketing-communication behavior and opt-out mechanism.
3. **[BLOCKS legal drafting]** Actual retention practice for contact/project records (non-chat).
4. **[BLOCKS legal drafting]** Actual Florida service-area description for Terms §5.
5. 100-draft file format → queue import field mapping (`question`, `draft_answer`, `source`).
6. Classification execution model: async batch via OpenRouter (preferred for cost) — model selection within $1/month cap.
7. Whether chat-originated FAQ candidates enter the queue automatically as `New` or require an admin "promote" action (recommend: explicit promote — keeps queue deliberate).

**Stage 2 complete. No code written, no production changes made. Manual FAQ publication approval remains an explicit hard gate; Terms/Privacy work remains limited to the approved two-page draft update and is blocked pending the four verified-fact items above. Awaiting go-ahead for Stage 3.**

## Pass 3 — skeptic-privacy-and-legal

# Stage 3 — Skeptic Review: Privacy & Legal
**Coastal Cornerstone Construction — Question-Intelligence Dashboard + Public Site**
*Critique of Stage 1 (architecture) and Stage 2 (product/UX/legal) baselines. Planning artifact only. No code, no production changes. Manual FAQ publication approval remains an explicit hard gate. Terms/Privacy work remains limited to the approved two-page draft update.*

Findings are grouped by review category. Each has: **severity** (Blocker / High / Medium / Low), **location**, **issue**, **correction**. Corrections are folded into the Stage 4 baseline; nothing here authorizes implementation.

---

## 1. Privacy Leaks

### F-1.1 — Exports create uncontrolled copies that outlive retention — **High**
- **Location:** Stage 1 Loop E; Stage 2 W4.
- **Issue:** Downloaded CSV/JSON files persist indefinitely on admin devices while the privacy copy will claim chat records are deleted at 30 days. The "include Sensitive-private" toggle makes this worse: one click produces a durable file of the most sensitive content. The system cannot enforce or even observe post-download handling.
- **Correction:**
  1. Keep `Sensitive-private` excluded by default; including it requires a **second explicit confirmation** naming the consequence, and is logged as a distinct audit action (`export_sensitive_included`).
  2. Export UI carries a plain handling notice: "This file contains chat records. It is not covered by the site's 30-day automatic deletion. Delete it when no longer needed." (UI copy only — not a banner on public pages.)
  3. Privacy copy must be scoped precisely: "chat records **in our systems** are deleted after 30 days" — never an unqualified "all data is deleted."

### F-1.2 — Conversation-list snippets can leak sensitive content pre-classification — **High**
- **Location:** Stage 2 W1 step 1 (Chats list shows "snippet").
- **Issue:** New conversations are unclassified on first view. A snippet of a `Sensitive-private` message (health, financial, minor's info) renders in the list for both admins before any label exists. After labeling, the snippet still renders unless masked.
- **Correction:** List rows show metadata only (time, message count, classification badge) plus snippet **only after** classification, and never for `Sensitive-private` rows (show a "content hidden — open to view" placeholder). Snippet rendering is a presentation rule in Loop G; no data-model change.

### F-1.3 — Classification sends chat content to OpenRouter — undisclosed secondary processing — **Blocker (legal alignment)**
- **Location:** Stage 1 Loop B; Stage 2 Open Question 6.
- **Issue:** Batch classification via OpenRouter means every chat message — including `Sensitive-private` content — is sent to a third-party LLM a *second* time for a *different purpose* than answering the user. The Stage 2 privacy outline (§4–§5) describes OpenRouter only as "AI processing" for the assistant. As drafted, the copy would understate the actual data flow — exactly the "invented/mismatched facts" failure the legal loop exists to prevent.
- **Correction (choose one, record as decision):**
  - **(a) Preferred:** classify with local rules/heuristics first; send to OpenRouter only items already labeled non-sensitive, and disclose in Privacy §4: "chat content is also processed to help us improve our FAQ, using the same AI provider." Update C.1 §4 content rule accordingly.
  - **(b)** If LLM classification of all content is required, Privacy §4/§5 must state it plainly. Either way, **C.3 checklist gains item: "classification data flow matches Privacy §4."**
  - Never send `Sensitive-private` content for LLM re-classification after labeling; re-classification of those items is human-only.

### F-1.4 — Session metadata is undefined — possible undisclosed collection — **Blocker (legal alignment)**
- **Location:** Stage 1 §4 `sessions.metadata`; Stage 2 C.1 §2.
- **Issue:** "Metadata" is unspecified. If it includes IP address, user agent, referrer, or timestamps beyond what §2 lists, the privacy copy's "What we collect" is incomplete. If it includes nothing, the field is dead weight.
- **Correction:** Add **blocking open question**: enumerate the exact contents of `sessions.metadata`. Privacy §2 may only list what is verified. Default posture: collect the minimum; drop any field not operationally needed (cheaper and safer than disclosing it).

### F-1.5 — Cookie/tracking verification must cover storage beyond cookies — **High**
- **Location:** Stage 1 Open Question 1; Stage 2 C.1 §6.
- **Issue:** The chat widget likely needs session continuity, which may use `localStorage`/`sessionStorage` even with zero cookies. A privacy page saying "we use no cookies or tracking" while the widget stores session tokens in the browser would be misleading. Railway/Manus infrastructure may also set platform cookies.
- **Correction:** Expand the verification item to: **cookies, localStorage/sessionStorage, analytics scripts, pixels, server-side access-log practice, and any provider-set cookies on public pages.** §6 describes the verified result in plain terms ("we do not use analytics or advertising trackers; the chat assistant stores a session identifier in your browser so the conversation continues" — only if true).

### F-1.6 — Export "preview" is unscoped and a leak surface — **Medium**
- **Location:** Stage 2 §A.3 row 10 ("never shown in export preview by default").
- **Issue:** An export-preview feature appears nowhere in the data model or workflows. It adds a new render path for bulk sensitive data in the browser.
- **Correction:** Remove export preview from scope. Export = generate + download + log. (Also reduces cost-gate surface.)

### F-1.7 — Breadcrumb/tooltip text can carry content — **Low**
- **Location:** Stage 2 §B.1 ("FAQ detail — {question, truncated}", tooltips carry full text).
- **Issue:** FAQ questions are public-safe, but the same tooltip pattern applied to chat-originated drafts could surface user content in page titles/browser history.
- **Correction:** Tooltips/full-text titles only on FAQ and draft *question* fields that have reached `Ready for approval`; chat-derived drafts use `Draft {id}` only. Conversation breadcrumbs use opaque ID, not date (date + business name in browser history is a soft identifier).

---

## 2. Accidental Publication

### F-2.1 — Legal-page publish has no explicit human gate — **Blocker**
- **Location:** Stage 1 Loop H ("single approved update"); Stage 2 C.3 item 9.
- **Issue:** Loop H defines a factual-alignment gate but never names the **human publish action**. "Publish is one reversible commit" could be read as an automated step once the checklist passes — the same class of failure the FAQ manual gate exists to prevent.
- **Correction:** Add to Loop H: publish requires an **explicit authenticated confirmation by Sri or Ben**, showing the full final page text, recorded in `audit_log` (`legal_page_published`, actor, slug, version

## Pass 4 — skeptic-operations-and-compatibility

# Stage 4 — Skeptic Review: Operations & Compatibility
**Coastal Cornerstone Construction — Question-Intelligence Dashboard + Public Site**
*Critique of Stages 1–3 from the operations and compatibility side. Planning artifact only. No code, no production changes. Manual FAQ publication approval remains an explicit hard gate. Terms/Privacy work remains limited to the approved two-page draft update.*

**Carried forward from Stage 3 (still open, still binding):** F-1.3 (classification data flow vs. Privacy §4 — Blocker), F-1.4 (`sessions.metadata` enumeration — Blocker), F-1.5 (storage/tracking verification scope), F-2.1 (legal-page publish requires an explicit authenticated human confirmation by Sri or Ben, showing full final text, logged as `legal_page_published` with actor, slug, version, timestamp — Blocker). Stage 4 findings are additive; nothing here supersedes them.

Findings use the same format: **severity** (Blocker / High / Medium / Low), location, issue, correction.

---

## 1. Migration

### F-4.1 — No migration versioning or rehearsal requirement — **Blocker**
- **Location:** Stage 1 §4 ("migrations are additive and reversible"); Stage 1 §7 gates.
- **Issue:** "Additive and reversible" is asserted, not mechanized. SQLite has no built-in migration tracking. Without a `schema_migrations` table and ordered, idempotent migration files, there is no way to prove which schema version production is on, and "reversible" is untestable. Re-running a migration by hand could double-apply changes.
- **Correction:**
  1. Add `schema_migrations` (version, applied_at, checksum) to the data model.
  2. Every migration ships with a tested down-path; "reversible" means *demonstrated in staging*, not "should be reversible."
  3. New gate evidence: Stage 1 Gate #5 (rollback) must include a migration apply→revert→reapply cycle on a copy of the production database.

### F-4.2 — No pre-migration backup step — **Blocker**
- **Location:** Stage 1 §4; all loops touching schema.
- **Issue:** SQLite is a single file. Any migration failure without a file-level backup risks the only copy of sessions, messages, FAQs, and audit history. "Rollback" of a half-applied migration against a corrupted file is not rollback.
- **Correction:** Mandatory pre-migration step: copy the database file to a versioned backup location before any migration runs; backup retention for backups is an operational decision (note: backups containing chat records must themselves respect the 30-day deletion posture or be encrypted/short-lived — see F-4.3).

### F-4.3 — Backups silently break the 30-day retention promise — **Blocker (legal alignment)**
- **Location:** Stage 1 Loop F; Stage 2 C.1 §9; F-4.2 (created here).
- **Issue:** Loop F purges chat records from the live database at 30 days. If database backups (taken for migration safety or routine ops) retain chat content longer, the privacy copy's "deleted after 30 days" is false in practice — the same class of mismatch as Stage 3 F-1.1 (exports).
- **Correction:**
  1. Backup lifetime must be ≤ 30 days, or backups must exclude chat tables, or backups must be encrypted with keys rotated/destroyed on the same schedule.
  2. Privacy §9 copy rule updated: "chat records in our systems, including backups, are deleted within 30 days" — only if the chosen mechanism makes it true. Add to C.3 checklist: "backup retention matches Privacy §9."

### F-4.4 — 100-draft import is not idempotent — **High**
- **Location:** Stage 1 Loop C; Stage 2 Open Question 5.
- **Issue:** Importing the 100-question draft file is a one-time bulk operation. If it fails partway (timeout, bad row, encoding issue) and is re-run, the queue gets duplicates with no way to tell which rows are originals. There is no defined failure behavior.
- **Correction:**
  1. Import runs as a single transaction: all 100 rows or none.
  2. Each imported row carries `source = 'draft_file'` plus a stable source identifier (row number or content hash) so re-imports can be detected and skipped.
  3. Import event logged in `audit_log` (actor, row count, file identifier). Import is an authenticated admin action, not a script run outside the audit trail.

### F-4.5 — SQLite concurrency during migration and normal operation unaddressed — **Medium**
- **Location:** Stage 1 §2 (single store); Loop A (capture on every chat).
- **Issue:** Public chat capture writes continuously. A migration or a long export query holding a write lock can block capture inserts; if capture blocks the chat response, that violates the Loop A boundary (capture must never break chat). Default SQLite journal mode makes writer-blocking likely.
- **Correction:**
  1. Specify WAL mode (or document why not) so reads don't block writes.
  2. Capture writes must be fire-and-forget with a short timeout and a logged failure path (already a Loop A boundary — now an explicit operational requirement).
  3. Migrations run during a maintenance window with capture queued or briefly paused-with-logging, never silently dropped. **Capture completeness gate (#2) must be re-run after any migration.**

---

## 2. Duplicate FAQ Handling

### F-4.6 — No deduplication between the 100 drafts and the 50 approved FAQs — **High**
- **Location:** Stage 1 Loop C/D; Stage 2 W2/W3.
- **Issue:** The 100-question draft file almost certainly overlaps the 50 approved FAQs (same business, same questions). Publishing a draft that duplicates an approved FAQ produces two public answers to the same question — possibly contradictory ones. The publish gate (W3) confirms *text*, not *uniqueness*.
- **Correction:**
  1. Import step flags candidate duplicates (exact and near match on question text) against `faq_approved`; flagged drafts enter the queue with status `Possible duplicate` and a link to the existing approved item.
  2. W3 publish confirmation gains a duplicate warning: if the question matches an existing approved FAQ, the admin must choose **Replace (new version of existing)** or **Publish as separate** — both logged. Replace uses the versioning path (F-4.7), never a second live row for the same question.
  3. Dedupe is a *warning*, not an auto-merge — the human gate stays human.

### F-4.7 — "Version" semantics for approved FAQs are undefined — **High**
- **Location:** Stage 1 §4 `faq_approved.version`; Stage 2 W3 rollback path.
- **Issue:** "Restore prior version" is promised, but the model doesn't say whether editing an approved FAQ creates a new version row in place, a new draft that supersedes on approval, or a fork. Ambiguity here makes rollback behavior unpredictable — the exact thing the rollback gate must demonstrate.
- **Correction (decision recorded):** Approved FAQs are immutable once published. Editing an approved FAQ creates a **new draft linked to the approved item**; approving that draft publishes it as `version n+1` of the *same* FAQ identity and supersedes version *n* (which remains in the table, unpublished, restorable). One live version per FAQ identity at all times. Rollback = re-publish version *n*, which supersedes *n+1*. Every transition logged.

### F-4.8 — Chat-originated FAQ candidates can duplicate queue drafts — **Medium**
- **Location:** Stage 2 W1→W2 promotion; Stage 3 open item 7.
- **Issue:** A `FAQ candidate` promoted from chat may ask the same thing as one of the 100 imported drafts. Two admins could then draft two answers in parallel.
- **Correction:** Same duplicate-flag mechanism as F-4.6, applied at promote time against both `faq_drafts` and `faq_approved`. Promotion remains an explicit admin action (confirming Stage 3's recommendation).

---

## 3. Admin Confusion

### F-4.9 — Two admins, one draft: concurrent-edit behavior undefined — **High**
- **Location:** Stage 2 W2 step 4; Stage 1 §4 `answer_history`.
- **Issue:** Sri and Ben can open the same draft simultaneously. Last-write-wins silently destroys one editor's work; the append-only history records both saves but the *current* draft reflects only one. Worse: one admin could mark `Ready for approval` while the other is mid-edit, and the other admin could then approve text neither fully reviewed.
- **Correction:**
  1. Draft saves are conflict-checked: saving against a stale version returns "this draft was changed by {other admin} at {time} — review their changes" with the history accordion opened. No silent overwrite.
  2. The W3 publish confirmation shows **last editor and last edit time** alongside the text, so the approver can see if the text changed since they last looked.
  3. No locking system (cost/complexity); conflict detection on save is sufficient for two admins.

### F-4.10 — Status vocabulary collision: "Approved" the queue state vs. "approved" the FAQ table — **Medium**
- **Location:** Stage 2 W2 states; Stage 1 §4 `faq_approved`.
- **Issue:** A draft in state `Approved` (queue) and a row in `faq_approved` (published) sound identical but are different things at different times. Misreading this is how accidental publication happens in practice — an admin thinks "approved" means "already live."
- **Correction:** Rename queue terminal states to `Published` and `Rejected`. UI copy on the publish confirmation says explicitly: "This will make the answer visible on the public FAQ page." (Reinforces, never replaces, the manual gate.)

### F-4.11 — Classification labels vs. queue status live on different objects with no stated relationship — **Medium**
- **Location:** Stage 1 Loops B/C; Stage 2 W1/W2.
- **Issue:** A conversation is labeled `FAQ candidate`; a draft exists in the queue. If the conversation is later re-labeled `Sensitive-private` (Stage 3 F-1.3 requires human-only re-classification for these), what happens to the draft derived from it? Undefined — and the dangerous default is "nothing," leaving sensitive-derived content in the publish pipeline.
- **Correction:** Re-labeling a conversation to `Sensitive-private` **automatically suspends** any linked drafts (status `Suspended — source reclassified`) and blocks their publish path until an admin explicitly unlinks the draft from the source conversation or discards it. Logged. This is a hard publish-gate precondition, not a warning.

### F-4.12 — Unpublish vs. Reject vs. Delete: destructive-action semantics unclear — **Low**
- **Location:** Stage 2 §A.3 row 8 (destructive = unpublish, reject).
- **Issue:** Three similar-sounding actions with different blast radii. Reject on a published FAQ is impossible; unpublish on a draft is meaningless; nothing is ever truly deleted (retention sweeper excepted).
- **Correction:** Action availability is state-dependent and shown disabled-with-reason otherwise: drafts can be `Rejected`; published FAQs can be `Unpublished`; nothing in the admin UI deletes. One-line confirmation copy per action stating exactly what changes publicly.

---

## 4. Exports

### F-4.13 — CSV formula injection from user chat content — **High**
- **Location:** Stage 1 Loop E; Stage 2 W4.
- **Issue:** Chat messages are attacker-controlled text. A message beginning with `=`, `+`, `-`, or `@` becomes a live formula when the CSV is opened in a spreadsheet — a known exfiltration/code-execution vector against the admin's own machine. JSON export is unaffected; CSV is the risk.
- **Correction:** CSV export sanitizes cell values (prefix dangerous leading characters). Documented as an export-contract behavior; since exports are admin-only and the format contract is internal, this does not touch the public API/MCP contract gate.

### F-4.14 — Export scope is undefined: which tables, which fields — **High**
- **Location:** Stage 1 Loop E ("captured/classified data"); Stage 2 W4.
- **Issue:** "CSV/JSON exports" exist today, but the approved scope adds classifications, drafts, and history without saying whether exports now include them. If exports silently grow to include draft answers and edit history, the export surface (and the F-1.1 leak surface) expands without a decision. If they don't, admins may assume drafts are backed up via export when they aren't.
- **Correction:** Define export contents explicitly: **sessions, messages, classifications only** (the existing behavior, preserved). Drafts, answer history, approved FAQs, and audit log are *not* in the standard export. If a separate content-backup export is wanted later, it's a new approved scope item, not a silent addition.

### F-4.15 — Export generation can block the single-writer database — **Medium**
- **Location:** Stage 1 Loop E; F-4.5.
- **Issue:** A 30-day full export scans the largest tables. Under the wrong journal mode this stalls capture writes from live chats.
- **Correction:** Covered by the F-4.5 fix (WAL + read-only export queries). Export queries run read-only; export row counts are capped by the 30-day window, so size is bounded by design.

### F-4.16 — Stage 3's sensitive-export second confirmation needs a defined interaction — **Low**
- **Location:** Stage 3 F-1.1 correction 1.
- **Issue:** "Second explicit confirmation" is specified as a requirement but not as an interaction; vague confirmations become checkbox theater.
- **Correction:** The confirmation requires typing or re-checking an explicit statement ("Include sensitive-private conversations in this export") — a distinct control from the format/range selections, logged as `export_sensitive_included` per Stage 3.

---

## 5. Rollback

### F-4.17 — Rollback is specified per-feature but never as a tested end-to-end procedure — **Blocker**
- **Location:** Stage 1 §7 Gate #5; Stage 2 W3; Stage 2 C.3 item 9.
- **Issue:** FAQ unpublish, version restore, legal-page restore, and migration revert are each described, but Gate #5 has no defined *evidence standard*. "Demonstrated" could mean anything from a unit test to a staging walkthrough. Rollback that hasn't been rehearsed against realistic data is a hope, not a gate.
- **Correction:** Gate #5 evidence standard defined: on a staging copy of production data, execute and log (a) FAQ publish → unpublish → verify absent from `/faq/`; (b) FAQ version *n+1* publish → restore *n* → verify `/faq/` shows *n*; (c) legal-page publish → restore prior version → verify public page content; (d) migration apply → revert → reapply (F-4.1). All four must pass with audit-log entries proving each transition. No production change until all four pass.

### F-4.18 — The audit log itself has no rollback or protection story — **High**
- **Location:** Stage 1 §4 `audit_log`; Stage 2 W5.
- **Issue:** Auditability is a hard constraint, but nothing protects `audit_log` from the migration path (F-4.1/F-4.2) or from being included in the 30-day sweeper by mistake. If the sweeper ever purges audit rows, the purge itself becomes unauditable — the worst possible audit failure.
- **Correction:**
  1. Loop F boundary amended: the retention sweeper applies to **chat records (sessions, messages, and their classifications) only**. `audit_log`, `faq_*`, `answer_history`, and `legal

## Pass 5 — updated-plan-reconcile

# Stage 5 — Reconciled Implementation-Ready Plan
**Coastal Cornerstone Construction — Question-Intelligence Dashboard + Public Site**

*This document reconciles Stages 1–4 into a single implementation-ready baseline. Planning artifact only. No code is written here; no production changes are authorized by this document. Manual public FAQ publication approval remains an explicit hard gate. Terms/Privacy work remains limited to the approved two-page draft update and runs as a separately reviewable loop (Loop H) with its own human publish gate and rehearsed rollback.*

*Note on sources: Stage 3 was truncated at F-2.1 and Stage 4 at F-4.18. Both findings are completed here from their carried-forward summaries (Stage 4 header for F-2.1; the visible logic of F-4.18). If the original passes contained additional findings beyond the truncation points, they must be appended to §9 before implementation begins.*

---

## 1. Reconciliation Summary — Decisions Now Locked

The following decisions resolve ambiguities and findings from Stages 1–4. They are binding on implementation unless explicitly reopened by Sri or Ben.

| # | Decision | Source |
|---|---|---|
| D1 | **Classification data flow:** local rules/heuristics classify first. Only content already labeled non-sensitive is sent to OpenRouter for LLM-assisted classification. `Sensitive-private` items are never sent for LLM re-classification; re-labeling them is human-only. Privacy §4 will disclose FAQ-improvement processing plainly. *(Owner confirmation required — see BQ-7.)* | F-1.3 (a) |
| D2 | **Approved FAQ versioning:** published FAQs are immutable. Editing one creates a new linked draft; approval publishes it as version *n+1* of the same FAQ identity, superseding *n*. One live version per identity at all times. Rollback = re-publish *n*, superseding *n+1*. Every transition logged. | F-4.7 |
| D3 | **Queue terminal states renamed:** `Published` / `Rejected` (not "Approved"), to eliminate collision with the `faq_approved` table. Publish confirmation copy states: "This will make the answer visible on the public FAQ page." | F-4.10 |
| D4 | **Export scope fixed:** sessions, messages, classifications only — the existing behavior, preserved. Drafts, answer history, approved FAQs, and audit log are excluded. Any future content-backup export is new approved scope, never a silent addition. | F-4.14 |
| D5 | **CSV formula-injection sanitization:** dangerous leading characters (`=`, `+`, `-`, `@`) are prefixed on CSV export. Internal export contract only; public API/MCP contracts untouched. | F-4.13 |
| D6 | **No export preview.** Export = generate + download + log. | F-1.6 |
| D7 | **SQLite operational posture:** WAL mode (or documented exception); capture writes are fire-and-forget with short timeout and logged failure; export queries are read-only; migrations run in a maintenance window with capture queued or paused-with-logging, never silently dropped. | F-4.5, F-4.15 |
| D8 | **Migration discipline:** `schema_migrations` table (version, applied_at, checksum); ordered idempotent migration files; every migration ships a tested down-path; file-level database backup before any migration. | F-4.1, F-4.2 |
| D9 | **Backup/retention alignment:** backups containing chat records live ≤ 30 days, or exclude chat tables, or are encrypted with keys destroyed on the same schedule. Privacy §9 copy may only claim what the chosen mechanism makes true. | F-4.3 |
| D10 | **100-draft import:** single transaction (all 100 or none); each row carries `source = 'draft_file'` + stable identifier (row number or content hash); re-imports detected and skipped; import is an authenticated, audit-logged admin action. | F-4.4 |
| D11 | **Duplicate handling:** import flags exact/near matches against `faq_approved` (status `Possible duplicate`, linked to existing item). Promote-time check against both `faq_drafts` and `faq_approved`. At publish, a match forces an explicit choice: **Replace (new version)** or **Publish as separate** — both logged. Dedupe warns; it never auto-merges. | F-4.6, F-4.8 |
| D12 | **Concurrent-edit protection:** stale-version saves are rejected with "changed by {admin} at {time}" and the history accordion opened. No silent overwrite. Publish confirmation shows last editor and last edit time. No locking system. | F-4.9 |
| D13 | **Sensitive-source suspension:** re-labeling a conversation to `Sensitive-private` automatically suspends linked drafts (`Suspended — source reclassified`) and blocks their publish path until an admin explicitly unlinks or discards them. Logged. Hard publish-gate precondition. | F-4.11 |
| D14 | **Snippet & breadcrumb hygiene:** chat list rows show metadata only until classified; `Sensitive-private` rows never show snippets ("content hidden — open to view"). Full-text tooltips only on FAQ/draft question fields at `Ready for approval` or later; chat-derived drafts use `Draft {id}`; conversation breadcrumbs use opaque ID, not date. | F-1.2, F-1.7 |
| D15 | **Sensitive export friction:** `Sensitive-private` excluded by default; including it requires a distinct explicit control (typed or re-checked statement: "Include sensitive-private conversations in this export"), logged as `export_sensitive_included`. Export UI carries a handling notice: the file is not covered by 30-day automatic deletion. Privacy copy scoped to "chat records **in our systems**." | F-1.1, F-4.16 |
| D16 | **Legal-page publish gate:** publishing Terms or Privacy requires an explicit authenticated confirmation by Sri or Ben showing the full final page text, logged as `legal_page_published` (actor, slug, version, timestamp). No auto-publish, ever. | F-2.1 |
| D17 | **Sweeper scope:** the 30-day retention sweeper applies to chat records (sessions, messages, their classifications) **only**. `audit_log`, `faq_*`, `answer_history`, `legal_pages`, and `schema_migrations` are never purged. | F-4.18 |
| D18 | **Rollback evidence standard:** Gate #5 requires four rehearsed procedures on a staging copy of production data (§6.5). | F-4.17 |
| D19 | **Chat-originated FAQ candidates** enter the queue only via explicit admin "promote" action. | Stage 2 OQ-7 |
| D20 | **State-dependent destructive actions:** drafts can be `Rejected`; published FAQs can be `Unpublished`; nothing in the admin UI deletes. Unavailable actions render disabled-with-reason. | F-4.12 |

---

## 2. Final Data Model (SQLite)

Additive to the existing capture schema. All migrations additive, reversible, rehearsed (D8).

| Table | Purpose | Key fields / notes |
|---|---|---|
| `sessions` | Chat sessions | `metadata` contents **must be enumerated (BQ-5)** before legal drafting; default posture: minimum necessary, drop unused fields |
| `messages` | Chat messages | Existing capture; untouched contract |
| `classifications` | One label per conversation | `Ignore` / `Needs answer` / `FAQ candidate` / `Sensitive-private`; human re-label path; LLM assist only per D1 |
| `faq_drafts` | Review queue | States: `New` → `In progress` → `Ready for approval` → `Published` / `Rejected`; plus `Possible duplicate`, `Suspended — source reclassified`; fields: `question`, `draft_answer`, `source` (`draft_file` / `chat`), `source_ref`, `linked_faq_id`, `version_of` |
| `answer_history` | Append-only edit history | Never updated or deleted |
| `faq_approved` | Published FAQs | Immutable rows; `version`; one live version per FAQ identity (D2) |
| `legal_pages` | Terms/Privacy versions | `slug`, `version`, `content`, `published_at`, `published_by`; prior versions retained, restorable |
| `audit_log` | Append-only audit | Read-only UI; **excluded from sweeper (D17)**; protected by pre-migration backup (D8) |
| `schema_migrations` | Migration tracking | `version`, `applied_at`, `checksum` (D8) |

---

## 3. Reconciled Loops

### Loop A — Capture (unchanged boundary)
Every chat entry captured; capture never blocks or breaks the chat response (fire-and-forget, logged failure — D7). Public API/MCP contracts, safeguards, and agent guardrails untouched.

### Loop B — Classification (amended per D1)
Local heuristics first → OpenRouter only for non-sensitive content → human-only re-classification of `Sensitive-private`. Re-label to `Sensitive-private` triggers D13 suspension of linked drafts.

### Loop C — Draft queue (amended per D10, D11, D19)
Import (transactional, idempotent, logged) and explicit promote are the only entry paths. Duplicate flags at both. Conflict-checked saves (D12). States per D3.

### Loop D — Approval & publish (manual gate, unchanged in principle, hardened)
Publish requires explicit authenticated confirmation by Sri or Ben showing exact text, last editor, last edit time, and any duplicate warning (D11). Preconditions: not `Suspended`, duplicate choice made if flagged. Logged with approver, timestamp, version. No auto-publish, no scheduled publish; any future batch publish requires per-item confirmation, each logged individually.

### Loop E — Export (scoped per D4, D5, D6, D15)
CSV/JSON, date range, sensitive excluded by default with D15 friction, sanitized CSV cells, read-only queries, logged (actor, format, range, row count; `export_sensitive_included` where applicable).

### Loop F — Retention (scoped per D17, D9)
Sweeper purges chat records only, at 30 days. Backup lifetime aligned (D9). Sweeper runs are themselves logged in `audit_log` (which it never touches).

### Loop G — UX (presentation-only, amended per D14)
Stage 2 §A.3 list stands, minus export preview (D6), plus snippet-masking and tooltip rules (D14), state-dependent destructive actions (D20), conflict-notice UI (D12), and publish-confirmation content (Loop D). Breadcrumbs per Stage 2 §B with opaque conversation IDs.

### Loop H — Terms & Privacy (separately reviewable — see §5)

---

## 4. Blocking Open Questions Register

These **must be answered with verified facts** before the named work proceeds. Everything else can proceed in parallel.

| # | Question | Blocks |
|---|---|---|
| BQ-1 | Verified status of cookies, localStorage/sessionStorage, analytics scripts, pixels, server access-log practice, and provider-set cookies on public pages (expanded scope per F-1.5) | Privacy §6 |
| BQ-2 | Actual marketing-communication behavior: what is sent, via what channel, actual opt-out mechanism | Privacy §7 |
| BQ-3 | Actual retention practice for contact/project records (non-chat) | Privacy §9 |
| BQ-4 | Actual Florida service-area description | Terms §5 |
| BQ-5 | Exact contents of `sessions.metadata` | Privacy §2; possible schema minimization |
| BQ-6 | 100-draft file format → field mapping (`question`, `draft_answer`, `source`) | Phase 2 import |
| BQ-7 | Owner confirmation of D1 classification flow; if LLM classification of all content is required instead, Privacy §4/§5 must state it plainly | Loop B build; Privacy §4 |

---

## 5. Loop H — Terms & Privacy as a Separately Reviewable Workstream

Loop H is decoupled from the dashboard build so it can be reviewed, approved, and published independently — but it remains under the same rigor.

**H-1. Drafting inputs (all required before copy is written):**
- BQ-1 through BQ-5 answered and recorded.
- Stage 2 §C.1/§C.2 outlines and §C.3 checklist, amended by: F-1.1 (scoped deletion language), F-1.3 (classification-flow disclosure per D1), F-1.5 (expanded tracking verification), F-4.3 (backup retention matches §9), and new checklist item: **"classification data flow matches Privacy §4."**

**H-2. Drafting rules (restated, binding):**
1. No invented addresses, registration numbers, certifications, SLAs, response times, retention periods, or service areas.
2. Every named provider (Railway, OpenRouter, Resend, Manus, Projul) actually in use; every described data flow real.
3. No claim or implication of legal review or approval on the pages. (User's lawyer reviews later; the pages say nothing about review status.)
4. No indemnity, warranty, or liability language conflicting with actual data flows as described in `/privacy/`.
5. Florida factual context from current official Florida sources only (e.g., Florida Statutes via Online Sunshine), including incident-notification framing in Privacy §10 — factual, no invented commitments.
6. Plain, professional tone. No warning banner. No dark patterns. No new public routes; breadcrumbs per Stage 2 §B.2.

**H-3. Review & publish sequence:**
1. Draft both pages → factual-alignment checklist (§C.3 as amended) passes in full.
2. Sri or Ben reviews the full final text.
3. Explicit authenticated publish confirmation showing full final text (D16) → logged as `legal_page_published`.
4. Publish is one reversible commit; prior versions retained in `legal_pages`.
5. Rollback = restore prior version, logged — rehearsed per §6.5(c) **before** first publish.

**H-4. Explicitly out of scope for Loop H:** any behavior change, any new data collection, any banner, any page beyond `/terms
