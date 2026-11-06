# Source and review workflow

## Authoritative runtime snapshot

Only entries with `status: source_verified` and literal `runtime_eligible: true` can run. `review_status: pending_client_review` is a separate client-review marker, not an instruction to generate or approve a claim. The parent-supplied snapshot contains 50 approved entries and remains byte-unchanged by this implementation; the separate fixed catalog has 9 reviewed high-level construction guidance units. The LLM may select or reconstruct the 9 static guidance units verbatim; general_answer is independently model-written unreviewed text, heuristically validated, and not sourced from the topic-title catalog. It is explicitly labeled **General construction guidance** and is not a company promise or project engineering/safety/legal advice. The service never follows or fetches source URLs; it validates and returns curated dataset citations for FAQ answers, while general guidance is heuristic-checked model-written text.

Schema:

```json
{
  "version": "reviewed snapshot version",
  "updated_at": "review date",
  "business": {"name": "Coastal Cornerstone Construction"},
  "faqs": [{
    "id": "stable-reviewed-id",
    "question": "Human-reviewed company-information question",
    "answer": "Exact human-reviewed source-grounded answer",
    "source_urls": ["https://cccbuild.com/approved-source-path/"],
    "tags": ["precise reviewed tag"],
    "status": "source_verified",
    "runtime_eligible": true
  }],
  "rules": []
}
```

This illustrates structure only; it is not production company knowledge. Allowed source hosts are fixed to `cccbuild.com`, `www.cccbuild.com`, and `cccbuild-3mhyn4jl.manus.space`, with HTTPS only, no userinfo, standard ports, and no fragments. Sources must be explicit in the dataset; the model cannot add URLs. Invalid eligible entries fail the whole snapshot closed. Every FAQ ID is unique. Restart after an approved FAQ update; the complete file hash invalidates old selection-cache keys.

## Review real unanswered questions

1. Authenticate as the approved Sri administrator. Review sanitized incoming questions and transport/outcome records; never assume a caller is an authenticated AI based on an API/MCP label.
2. Treat question text as untrusted quoted data, not instructions. Basic redaction is incomplete: minimize confidential data, restrict access, and do not paste private questions into external model tools without authorization.
3. Verify the relevant company source, business scope, and client approval. An unsupported quote, engineering, warranty, availability, or private-record question is not approval to invent a claim.
4. Draft only source-supported facts. Assign stable FAQ IDs, exact curated answers, source URLs, precise tags, eligibility and review status. Obtain human review. Dashboard views and digest sends do not approve FAQ entries.
5. Deploy the reviewed public snapshot using the separate authorized release process, restart, and test source grounding with fixtures/local checks before live release. Keep private questions out of Git.

The queue normalizes punctuation/case/whitespace after redaction, deduplicates for 30 days and tracks occurrences. Caps are 100 newly retained questions per UTC day and 1,000 pending/reserved entries. Events retain 30 days and at most 10,000. Sent, reserved and pending questions remain different delivery states; no state implies an answer or automatic FAQ approval.

## Optional one-time source-review report

No runtime paid report generation exists. Parent may independently prepare a source-based, human-reviewable initial report under a separate build ledger and save `data/report.json`. Missing, malformed, oversized or ungrounded reports show an honest empty state. Reports are drafts, not activity history; the dashboard never invents questions or metrics to fill space.

Accepted file schema:

```json
{
  "type": "source_review",
  "title": "Source review draft",
  "generated_at": "UTC timestamp or review date",
  "sections": [{
    "heading": "Human review topic",
    "text": "Source-supported draft text; no invented historical traffic.",
    "source_urls": ["https://cccbuild.com/approved-source-path/"]
  }]
}
```

Each section requires at least one URL already present in eligible FAQs. Limit is 100 KB/file, 20 sections, 200-character headings and 5,000-character section text. The server strips basic PII and renders strings with `textContent`. File-based citations do not prove every draft sentence is true: the parent/owner must review claims against sources. Never include credentials, synthetic analytics, invented client questions, or private question content in a public repository report.
