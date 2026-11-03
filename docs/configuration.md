# Protected configuration

## Required production setup

Use Python 3.12, one Railway replica, a persistent volume at `/data`, `DATA_DIR=/data`, and `PORT=3000` (or Railway's actual injected port). Keep `.private/`, SQLite databases including WAL/SHM sidecars, `.env`, credentials, and volume backups outside Git and Docker build contexts. The public `data/faq.json` snapshot is source knowledge, not private queue state.

`PUBLIC_ORIGIN=https://coastal-cornerstone-agent-production.up.railway.app` is the approved origin configuration, but this implementation does not claim it has verified a live deployment. All privileged POSTs require an exact Origin header match and session-bound `X-CSRF-Token`. Cookies are host-only, Secure, HttpOnly, SameSite=Lax. Secure cookies may be disabled only with an explicit localhost origin for local development, never on standalone Railway.

`ADMIN_PASSWORD_HASH` is the **only password credential variable**. Administrator username is fixed to `sri@srinagubandi.com`; it cannot be overridden or expanded to Ben. There is no weak/default/plaintext credential fallback. An absent or invalid hash/origin disables the dashboard. Parent/operator handles password generation and any authorized credential-access email, not this app.

### Hash formats

Default helper `python3 hash_password.py` accepts a hidden password and confirmation, prints only a hash, and writes no credential file. Password length is 12–1,024 characters. Store the complete printed string in protected `ADMIN_PASSWORD_HASH`, preserving literal dollar signs.

Preferred format:

```text
scrypt$32768$8$1$<base64-16-byte-or-longer-random-salt>$<base64-32-byte-derived-hash>$32
```

The verifier accepts power-of-two N 32768–131072, r 8–16, p 1–2, 16–64-byte salts, and a 32-byte derived key (within the implementation's memory bound). The helper defaults N=32768, r=8, p=1. PBKDF2 SHA-256 is also supported:

```text
pbkdf2_sha256$600000$<base64-16-byte-or-longer-random-salt>$<base64-32-byte-derived-hash>
```

Iterations must be 600,000–2,000,000. Comparison uses constant-time `hmac.compare_digest`. Login is limited to 5/minute/client and 30/minute globally; hashing has two concurrent slots. Secrets/passwords/provider bodies are not logged. Do not put plaintext passwords on a command line, in a URL, or in a repository.

No extra salt or signing-secret environment variables are necessary. Random `session_key` and `ip_salt` are generated once in private SQLite metadata and survive restarts on the mounted volume. Sessions contain 256-bit random tokens with HMAC signatures, store only token hashes, bind role and random CSRF tokens, expire after eight hours (pre-login sessions ten minutes), and revoke on logout. To revoke all sessions, use an approved offline database maintenance transaction deleting `sessions`; do not rotate metadata casually because IP rate continuity and outstanding tokens depend on it. Rotate a changed password hash along with session revocation. Keep metadata private in backups.

## Runtime model variables

`OPENROUTER_API_KEY` is optional for deterministic/cache-only operation. `OPENROUTER_MODEL` must equal `deepseek/deepseek-v4-flash`; any other configured value fails startup. User inputs cannot override the model, key, URL, prompt, effort, tokens, recipient, or routing. `INPUT_PRICE_CEILING=0.000000091`, `OUTPUT_PRICE_CEILING=0.000000182`, `REQUEST_PRICE_CEILING=0` are USD/token/request defaults and may only be lowered. Monthly model cap is hard-coded to 1,000,000 microUSD. Build-time parent-owned reviews and reports are separate, never recurring API/dashboard work.

Live catalog verification occurs before a paid call and is cached for at most five minutes. Readiness does not initiate pricing or model network calls. Unverified pricing is honestly shown as unverified. No placeholder API key is invented if the real key is absent.

## Digest variables

`DIGEST_ENABLED=false` remains the default and approved task state. `RESEND_API_KEY` can be provisioned without enabling email. Sender/recipient variables are exactly `DIGEST_FROM=notifications@propeldock.com` and `DIGEST_TO=ben@cccbuild.com`. Any destination mismatch fails startup. No API send/test endpoint exists. Do not enable the scheduler until the owner approves production sender verification and delivery. No external email testing is permitted by this task.

## Other variables

`FAQ_PATH=/app/data/faq.json`, `REPORT_PATH=/app/data/report.json` are local file paths controlled only by deployment. `COOKIE_SECURE=true` is the production default. `TRUST_PROXY=false` is conservative: turn on only after verifying Railway's edge replaces/sanitizes X-Forwarded-For and prevents direct-origin bypass; this code reads only the rightmost hop, never an arbitrary first-hop value. An incorrect proxy setting can group clients or let callers evade per-client limits, though global caps still apply. Verify this operational boundary at release.
