"""Durable private FAQ review workflow for SQLite Store."""
import json
import os
import shutil
import sqlite3
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from safety import normalize, redact  # assuming safety.py is importable
import unicodedata

# Allowed public source hosts
ALLOWED_HOSTS = {
    "cccbuild.com",
    "www.cccbuild.com",
    "cccbuild-3mhyn4jl.manus.space",
    "cccbuild-website-production.up.railway.app",
}

# Private path segments that are not allowed in public URLs
PRIVATE_PATH_SEGMENTS = {"dashboard", "private", "static", "api", "admin", "internal", "server"}

# Allowed PII in answers
ALLOWED_EMAIL = "ben@cccbuild.com"
ALLOWED_PHONE = "(727)771-5672"

# Maximum lengths
MAX_QUESTION_LENGTH = 1500
MAX_ANSWER_LENGTH = 5000  # reasonable limit

class Conflict(Exception):
    """Optimistic concurrency conflict."""
    pass

def _validate_public_url(url):
    """Check that url is a public allowed source URL after normalization."""
    from urllib.parse import urlparse, unquote
    if not isinstance(url, str):
        raise ValueError("source_url must be a string")
    # NFKC normalization
    url = unicodedata.normalize('NFKC', url)
    if any(c.isspace() or (ord(c) < 32 and c not in '\n\r\t') for c in url):
        raise ValueError("source_url contains invalid whitespace or control characters")
    if not url.startswith("https://"):
        raise ValueError("source_url must use HTTPS")
    parsed = urlparse(url)
    if parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"source_url host not allowed: {parsed.hostname}")
    if parsed.port is not None and parsed.port != 443:
        raise ValueError("source_url must not specify a port other than 443")
    if parsed.query or parsed.fragment:
        raise ValueError("source_url must not contain query or fragment")
    if parsed.username or parsed.password:
        raise ValueError("source_url must not contain credentials")
    # Check path for private segments, recursively decode
    path = parsed.path
    for raw_segment in path.split('/'):
        if not raw_segment:
            continue
        # Decode percent-encoded characters
        decoded = unquote(raw_segment)
        # Reject if decoded segment contains slash (encoded path separator)
        if '/' in decoded:
            raise ValueError("source_url contains encoded path separator")
        # Check against forbidden private segments (case-insensitive)
        if decoded.lower() in PRIVATE_PATH_SEGMENTS:
            raise ValueError("source_url contains private path segment")
        # Also check recursively any sub-paths after splitting decoded
        for subseg in decoded.split('/'):
            if subseg.lower() in PRIVATE_PATH_SEGMENTS:
                raise ValueError("source_url contains private path segment")
    return True

def _contains_pii(text):
    """Check if text contains PII/credentials or private URLs beyond allowed ones."""
    import re
    from safety import CREDENTIAL_PATTERN, PRIVATE_URL_PATTERN
    # Check for non-allowed emails
    emails = re.findall(r'[\w.!#$%&\'*+/=?^`{|}~-]+@[\w.-]+\.[A-Za-z]{2,}', text)
    for email in emails:
        if email != ALLOWED_EMAIL:
            return True
    # Remove allowed email and phone from text before checking patterns to avoid false alarms
    cleaned = text.replace(ALLOWED_EMAIL, '').replace(ALLOWED_PHONE, '')
    if CREDENTIAL_PATTERN.search(cleaned):
        return True
    if PRIVATE_URL_PATTERN.search(cleaned):
        return True
    return False

def _normalize_question(question):
    """Normalize question for duplicate detection."""
    return normalize(question)

class FAQReview:
    def __init__(self, store, base_snapshot):
        self.store = store
        self.base_snapshot = base_snapshot
        self._migrate()
        self._initialize_baseline()

    def _backup_db(self):
        """Create a consistent backup using SQLite backup API (handles WAL)."""
        backup_dir = self.store.path.parent / "migration-backups"
        backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(backup_dir, 0o700)
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        backup_path = backup_dir / f"{self.store.path.name}.{timestamp}.bak"
        # Use SQLite backup instead of file copy for consistent WAL snapshot
        with self.store.connect() as src_conn:
            dst_conn = sqlite3.connect(str(backup_path))
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
        os.chmod(backup_path, 0o600)
        # Clean up old backups older than 30 days
        cutoff = time.time() - 30 * 86400
        for f in backup_dir.glob("*.bak"):
            if f.stat().st_mtime < cutoff:
                f.unlink()

    def _migrate(self):
        """Apply schema migrations idempotently."""
        with self.store.connect() as db:
            # Ensure schema_migrations table exists
            db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)")
            row = db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
            current_version = row[0] if row[0] is not None else 0
        target_version = 1
        if current_version >= target_version:
            return
        # Backup before migration
        self._backup_db()
        with self.store.transaction() as db:
            # Apply migrations sequentially
            if current_version < 1:
                db.execute("""
                CREATE TABLE IF NOT EXISTS faq_drafts (
                    id TEXT PRIMARY KEY,
                    question TEXT NOT NULL DEFAULT '',
                    answer TEXT NOT NULL DEFAULT '',
                    source_urls TEXT NOT NULL DEFAULT '[]',
                    tags TEXT NOT NULL DEFAULT '[]',
                    state TEXT NOT NULL DEFAULT 'new',
                    source_kind TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    linked_session_id TEXT,
                    linked_message_id TEXT,
                    replaces_faq_id TEXT,
                    revision INTEGER NOT NULL DEFAULT 1,
                    updated_by TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL,
                    UNIQUE(source_kind, source_id)
                )
                """)
                db.execute("""
                CREATE TABLE IF NOT EXISTS faq_draft_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    draft_id TEXT NOT NULL REFERENCES faq_drafts(id),
                    revision INTEGER NOT NULL,
                    question TEXT,
                    answer TEXT,
                    source_urls TEXT,
                    tags TEXT,
                    state TEXT,
                    updated_by TEXT,
                    updated_at REAL,
                    UNIQUE(draft_id, revision)
                )
                """)
                db.execute("""
                CREATE TABLE IF NOT EXISTS faq_release_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """)
                db.execute("""
                CREATE TABLE IF NOT EXISTS faq_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    draft_id TEXT,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    metadata TEXT
                )
                """)
                db.execute("""
                CREATE TABLE IF NOT EXISTS faq_confirmations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    draft_id TEXT NOT NULL REFERENCES faq_drafts(id),
                    confirmed_by TEXT NOT NULL,
                    confirmed_at REAL NOT NULL,
                    UNIQUE(draft_id, confirmed_by)
                )
                """)
                db.execute("INSERT INTO schema_migrations (version) VALUES (1)")
            # Future migrations can be added here

    def _initialize_baseline(self):
        """Insert base_snapshot as the first release if none exists (idempotent)."""
        with self.store.transaction() as db:
            # Only insert if no releases exist yet
            db.execute(
                "INSERT INTO faq_release_history (snapshot, created_by, created_at) "
                "SELECT ?, ?, ? WHERE NOT EXISTS (SELECT 1 FROM faq_release_history)",
                (json.dumps(self.base_snapshot), "system", time.time())
            )

    def import_questions(self, seed, actor="system"):
        """Import questions from seed list. Returns count of newly imported drafts."""
        imported = 0
        with self.store.transaction() as db:
            for item in seed:
                question = item.get("question", "")
                answer = item.get("answer", "")
                source_urls = item.get("source_urls", [])
                tags = item.get("tags", [])
                source_kind = item.get("source_kind", "draft_file")
                source_id = item.get("source_id")
                if source_id is None:
                    # Generate a stable source_id from question and source_urls
                    import hashlib
                    hash_input = json.dumps({"q": question, "urls": source_urls}, sort_keys=True)
                    source_id = hashlib.sha256(hash_input.encode()).hexdigest()[:16]
                # Check if already exists
                existing = db.execute(
                    "SELECT id FROM faq_drafts WHERE source_kind=? AND source_id=?",
                    (source_kind, source_id)
                ).fetchone()
                if existing:
                    continue
                draft_id = uuid.uuid4().hex
                now = time.time()
                db.execute(
                    """INSERT INTO faq_drafts (id, question, answer, source_urls, tags, state, source_kind, source_id,
                       revision, updated_by, updated_at)
                       VALUES (?, ?, ?, ?, ?, 'new', ?, ?, 1, ?, ?)""",
                    (draft_id, question, answer, json.dumps(source_urls), json.dumps(tags),
                     source_kind, source_id, actor, now)
                )
                # Insert initial history
                db.execute(
                    """INSERT INTO faq_draft_history (draft_id, revision, question, answer, source_urls, tags, state, updated_by, updated_at)
                       VALUES (?, 1, ?, ?, ?, ?, 'new', ?, ?)""",
                    (draft_id, question, answer, json.dumps(source_urls), json.dumps(tags), actor, now)
                )
                imported += 1
        return imported

    def list_drafts(self):
        """Return list of all drafts with basic fields."""
        with self.store.connect() as db:
            rows = db.execute("SELECT * FROM faq_drafts ORDER BY updated_at DESC").fetchall()
            drafts = []
            for row in rows:
                d = dict(row)
                d["source_urls"] = json.loads(d["source_urls"])
                d["tags"] = json.loads(d["tags"])
                drafts.append(d)
            return drafts

    def detail(self, draft_id):
        """Return draft detail with history and duplicate candidates."""
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM faq_drafts WHERE id=?", (draft_id,)).fetchone()
            if not row:
                return None
            draft = dict(row)
            draft["source_urls"] = json.loads(draft["source_urls"])
            draft["tags"] = json.loads(draft["tags"])
            # History
            history_rows = db.execute(
                "SELECT * FROM faq_draft_history WHERE draft_id=? ORDER BY revision",
                (draft_id,)
            ).fetchall()
            history = [dict(r) for r in history_rows]
            for h in history:
                h["source_urls"] = json.loads(h["source_urls"]) if h["source_urls"] else []
                h["tags"] = json.loads(h["tags"]) if h["tags"] else []
            draft["history"] = history
            # Duplicate candidates
            norm_q = _normalize_question(draft["question"])
            candidates = []
            # Check baseline (latest release snapshot)
            release_row = db.execute(
                "SELECT snapshot FROM faq_release_history ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if release_row:
                baseline = json.loads(release_row["snapshot"])
                for item in baseline:
                    if _normalize_question(item.get("question", "")) == norm_q:
                        candidates.append({"source": "baseline", "id": item.get("id", ""), "question": item.get("question", "")})
            # Check other drafts
            other_drafts = db.execute(
                "SELECT id, question FROM faq_drafts WHERE id != ?", (draft_id,)
            ).fetchall()
            for od in other_drafts:
                if _normalize_question(od["question"]) == norm_q:
                    candidates.append({"source": "draft", "id": od["id"], "question": od["question"]})
            draft["duplicate_candidates"] = candidates
            return draft

    def save(self, draft_id, body, actor):
        """Save updates to a draft. body must contain 'revision' matching current revision.
        Allowed fields: question, answer, source_urls, tags, state.
        Raises Conflict on revision mismatch, ValueError on validation failure.
        """
        # Allowed top-level keys
        allowed_keys = {"revision", "question", "answer", "source_urls", "tags", "state"}
        unknown = set(body.keys()) - allowed_keys
        if unknown:
            raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")
        # revision is mandatory and must be an integer
        if "revision" not in body:
            raise ValueError("body must contain 'revision'")
        if not isinstance(body["revision"], int) or isinstance(body["revision"], bool):
            raise ValueError("revision must be an integer")
        # Allowed state values
        ALLOWED_STATES = {"new", "in_progress", "ready", "rejected", "suspended"}
        if "state" in body:
            state_val = body["state"]
            if not isinstance(state_val, str) or state_val not in ALLOWED_STATES:
                raise ValueError(f"state must be one of {ALLOWED_STATES}, got {state_val!r}")
            if state_val == "published":
                raise ValueError("Cannot save with state='published'; use create_release instead")
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM faq_drafts WHERE id=?", (draft_id,)).fetchone()
            if not row:
                raise ValueError("Draft not found")
            current_state = row["state"]
            if current_state == "published":
                raise ValueError("Cannot edit a published draft")
            current_revision = row["revision"]
            if body["revision"] != current_revision:
                raise Conflict("Revision mismatch")
            # Extract updatable fields (excluding revision)
            updatable = {"question", "answer", "source_urls", "tags", "state"}
            updates = {}
            for key in updatable:
                if key in body:
                    updates[key] = body[key]
            if not updates:
                raise ValueError("No valid fields to update")
            # Validate lengths and types
            if "question" in updates:
                q = updates["question"]
                if not isinstance(q, str) or len(q) > MAX_QUESTION_LENGTH:
                    raise ValueError(f"question must be string <= {MAX_QUESTION_LENGTH} chars")
            if "answer" in updates:
                a = updates["answer"]
                if not isinstance(a, str) or len(a) > MAX_ANSWER_LENGTH:
                    raise ValueError(f"answer must be string <= {MAX_ANSWER_LENGTH} chars")
            # Validate tags
            if "tags" in updates:
                tags = updates["tags"]
                if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
                    raise ValueError("tags must be a list of strings")
                if len(tags) > 20:
                    raise ValueError("tags must not exceed 20 items")
            # Validate source_urls
            if "source_urls" in updates:
                urls = updates["source_urls"]
                if not isinstance(urls, list):
                    raise ValueError("source_urls must be a list")
                for url in urls:
                    _validate_public_url(url)
            # Build effective new state
            new_state = updates.get("state", current_state)
            # Readiness checks for 'ready' state
            if new_state == "ready":
                # Must have non-empty question and answer
                question = updates.get("question", row["question"])
                answer = updates.get("answer", row["answer"])
                if not isinstance(question, str) or not question.strip():
                    raise ValueError("Question must be a non-empty string for readiness")
                if not isinstance(answer, str) or not answer.strip():
                    raise ValueError("Answer must be a non-empty string for readiness")
                # Require at least one valid HTTPS public allowed source
                source_urls = updates.get("source_urls", json.loads(row["source_urls"]))
                if not source_urls:
                    raise ValueError("At least one source_url is required for readiness")
                for url in source_urls:
                    _validate_public_url(url)
                # Check PII/credentials in both question and answer
                if _contains_pii(question):
                    raise ValueError("Question contains prohibited PII or credentials")
                if _contains_pii(answer):
                    raise ValueError("Answer contains prohibited PII or credentials")
            # Apply updates
            new_revision = current_revision + 1
            now = time.time()
            # Update faq_drafts
            set_clause = ", ".join(f"{k}=?" for k in updates.keys())
            values = list(updates.values()) + [new_revision, actor, now, draft_id]
            db.execute(
                f"UPDATE faq_drafts SET {set_clause}, revision=?, updated_by=?, updated_at=? WHERE id=?",
                values
            )
            # Insert history
            history_question = updates.get("question", row["question"])
            history_answer = updates.get("answer", row["answer"])
            history_source_urls = json.dumps(updates.get("source_urls", json.loads(row["source_urls"])))
            history_tags = json.dumps(updates.get("tags", json.loads(row["tags"])))
            history_state = new_state
            db.execute(
                """INSERT INTO faq_draft_history (draft_id, revision, question, answer, source_urls, tags, state, updated_by, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (draft_id, new_revision, history_question, history_answer, history_source_urls, history_tags, history_state, actor, now)
            )
            # Audit log
            db.execute(
                "INSERT INTO faq_audit (draft_id, action, actor, timestamp, metadata) VALUES (?, 'save', ?, ?, ?)",
                (draft_id, actor, now, json.dumps({"revision": new_revision, "fields": list(updates.keys())}))
            )

    def create_release(self, actor="system"):
        """Create a new release snapshot from all published drafts."""
        with self.store.transaction() as db:
            published = db.execute(
                "SELECT * FROM faq_drafts WHERE state='published'"
            ).fetchall()
            snapshot = []
            for row in published:
                d = dict(row)
                d["source_urls"] = json.loads(d["source_urls"])
                d["tags"] = json.loads(d["tags"])
                snapshot.append(d)
            snapshot_json = json.dumps(snapshot)
            db.execute(
                "INSERT INTO faq_release_history (snapshot, created_by, created_at) VALUES (?, ?, ?)",
                (snapshot_json, actor, time.time())
            )
            return len(snapshot)

def read_public_snapshot(store, fallback=None):
    """Safely return current DB released snapshot, no migration side effects.
    Returns fallback if tables absent.
    """
    try:
        with store.connect() as db:
            # Check if faq_release_history exists
            table_exists = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='faq_release_history'"
            ).fetchone()
            if not table_exists:
                return fallback
            row = db.execute(
                "SELECT snapshot FROM faq_release_history ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row:
                return json.loads(row["snapshot"])
            return fallback
    except sqlite3.OperationalError:
        return fallback
