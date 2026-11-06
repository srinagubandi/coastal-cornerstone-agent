"""Private persistent SQLite state. Every operation owns a connection and write lock."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from config import MONTHLY_CAP
from safety import normalize, redact

DAY = 86400


def month_utc(now=None):
    return datetime.fromtimestamp(time.time() if now is None else now, timezone.utc).strftime("%Y-%m")


class Store:
    def __init__(self, data_dir):
        directory = Path(data_dir)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(directory, 0o700)
        self.path = directory / "state.sqlite3"
        with self.connect() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reservations(id TEXT PRIMARY KEY,month TEXT NOT NULL,
                amount INTEGER NOT NULL,status TEXT NOT NULL,created REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS reservation_month ON reservations(month);
            CREATE TABLE IF NOT EXISTS rates(key TEXT,bucket INTEGER,count INTEGER NOT NULL,
                PRIMARY KEY(key,bucket));
            CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY,payload TEXT NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS questions(id INTEGER PRIMARY KEY,normalized TEXT NOT NULL,
                question TEXT NOT NULL,created REAL NOT NULL,last_seen REAL NOT NULL,
                occurrences INTEGER NOT NULL DEFAULT 1,state TEXT NOT NULL DEFAULT 'pending');
            CREATE INDEX IF NOT EXISTS question_dedup ON questions(normalized,last_seen);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,created REAL NOT NULL,
                question TEXT NOT NULL,channel TEXT NOT NULL,outcome TEXT NOT NULL,
                faq_ids TEXT NOT NULL,sources TEXT NOT NULL,model_used TEXT,cost_micro INTEGER NOT NULL,
                reason TEXT NOT NULL,client_hash TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS event_created ON events(created);
            CREATE TABLE IF NOT EXISTS digests(day TEXT PRIMARY KEY,ids TEXT NOT NULL,payload TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,status TEXT NOT NULL,created REAL NOT NULL,
                attempted REAL,provider_id TEXT);
            CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,role TEXT NOT NULL,
                csrf TEXT NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS notification_settings(
                trigger TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0,
                recipients TEXT NOT NULL DEFAULT '[]', updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS notification_log(
                id INTEGER PRIMARY KEY AUTOINCREMENT, trigger TEXT NOT NULL,
                recipients TEXT NOT NULL, subject TEXT NOT NULL, status TEXT NOT NULL,
                created REAL NOT NULL, provider_id TEXT, idempotency_key TEXT NOT NULL UNIQUE);
            """)
        os.chmod(self.path, 0o600)
        with self.transaction() as db:
            for key in ("ip_salt", "session_key"):
                db.execute("INSERT OR IGNORE INTO meta VALUES (?,?)", (key, secrets.token_hex(32)))
        with self.connect() as db:
            self.ip_salt = db.execute("SELECT value FROM meta WHERE key='ip_salt'").fetchone()[0].encode()
            self.session_key = bytes.fromhex(db.execute("SELECT value FROM meta WHERE key='session_key'").fetchone()[0])

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=15000")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def client_hash(self, ip):
        return hmac.new(self.ip_salt, ip.encode(), hashlib.sha256).hexdigest()

    def _prune(self, db, now):
        cutoff = now - 30 * DAY
        db.execute("DELETE FROM events WHERE created < ?", (cutoff,))
        db.execute("DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 10000)")
        db.execute("DELETE FROM questions WHERE created < ?", (cutoff,))
        db.execute("DELETE FROM cache WHERE expires < ?", (now,))
        db.execute("DELETE FROM rates WHERE bucket < ?", (int(now) - 2 * DAY,))
        db.execute("DELETE FROM sessions WHERE expires < ?", (now,))
        db.execute("DELETE FROM digests WHERE created < ?", (now - 32 * DAY,))
        db.execute("DELETE FROM reservations WHERE created < ? AND month <> ?", (now - 62 * DAY, month_utc(now)))

    def prune(self, now=None):
        with self.transaction() as db:
            self._prune(db, time.time() if now is None else now)

    def rate(self, client, kind="ask", now=None):
        now = time.time() if now is None else now
        minute = int(now // 60) * 60
        day = int(now // DAY) * DAY
        if kind == "ask":
            limits = [(f"ask:m:{client}", minute, 5), (f"ask:d:{client}", day, 50),
                      ("ask:global:m", minute, 60), ("ask:global:d", day, 1000)]
        elif kind == "login":
            limits = [(f"login:{client}", minute, 5), ("login:global", minute, 30)]
        else:
            limits = [(f"read:{client}", minute, 120), ("read:global", minute, 1200)]
        with self.transaction() as db:
            self._prune(db, now)
            waits = []
            for key, bucket, limit in limits:
                row = db.execute("SELECT count FROM rates WHERE key=? AND bucket=?", (key, bucket)).fetchone()
                if row and row[0] >= limit:
                    window = DAY if key.startswith("ask:d:") or key == "ask:global:d" else 60
                    waits.append(max(1, int(bucket + window - now + 1)))
            # Blocked requests are not allowed to overflow or prolong fixed windows.
            if waits:
                return False, max(waits)
            for key, bucket, _ in limits:
                db.execute("INSERT INTO rates VALUES (?,?,1) ON CONFLICT(key,bucket) DO UPDATE SET count=count+1", (key, bucket))
        return True, 0

    def reserve(self, amount, now=None):
        if not isinstance(amount, int) or amount <= 0:
            raise ValueError("Reservation must be positive microUSD")
        now = time.time() if now is None else now
        month = month_utc(now)
        with self.transaction() as db:
            # A crashed request never frees money; it becomes an uncertain debit.
            db.execute("UPDATE reservations SET status='uncertain' WHERE status='pending' AND created < ?", (now - 120,))
            spent = db.execute("SELECT COALESCE(SUM(amount),0) FROM reservations WHERE month=?", (month,)).fetchone()[0]
            active = db.execute("SELECT count(*) FROM reservations WHERE status='pending'").fetchone()[0]
            if spent + amount > MONTHLY_CAP:
                return None, "monthly_budget_exhausted"
            if active >= 3:
                return None, "model_concurrency_limit"
            rid = uuid.uuid4().hex
            db.execute("INSERT INTO reservations VALUES (?,?,?,'pending',?)", (rid, month, amount, now))
            return rid, ""

    def settle(self, rid, actual_micro=None):
        with self.transaction() as db:
            row = db.execute("SELECT amount,status FROM reservations WHERE id=?", (rid,)).fetchone()
            if not row:
                raise ValueError("Unknown reservation")
            if actual_micro is None:
                db.execute("UPDATE reservations SET status='uncertain' WHERE id=? AND status='pending'", (rid,))
                return row[0]
            if not isinstance(actual_micro, int) or actual_micro < 0:
                raise ValueError("Invalid cost settlement")
            # Never hide a provider charge above the preflight bound.
            if row[1] in {"pending", "uncertain"}:
                db.execute("UPDATE reservations SET amount=?,status=? WHERE id=?", (actual_micro, "settled" if actual_micro <= row[0] else "overrun", rid))
                return actual_micro
            return row[0]

    def budget(self, now=None):
        month = month_utc(now)
        with self.connect() as db:
            rows = db.execute("SELECT status,SUM(amount) AS amount,COUNT(*) AS count FROM reservations WHERE month=? GROUP BY status", (month,)).fetchall()
        result = {"month": month, "cap_micro_usd": MONTHLY_CAP, "committed_micro_usd": sum(r["amount"] for r in rows),
                  "settled_micro_usd": sum(r["amount"] for r in rows if r["status"] in {"settled", "overrun"}),
                  "uncertain_micro_usd": sum(r["amount"] for r in rows if r["status"] == "uncertain"),
                  "inflight_micro_usd": sum(r["amount"] for r in rows if r["status"] == "pending")}
        result["remaining_micro_usd"] = max(0, MONTHLY_CAP - result["committed_micro_usd"])
        return result

    def _ensure_notification_defaults(self):
        defaults = {
            "contact_form": (1, '["ben@cccbuild.com"]'),
            "chat_ended": (0, "[]"),
            "unanswered_question": (0, "[]"),
            "safety_flag": (0, "[]"),
            "rate_limit": (0, "[]"),
            "monthly_faq_update": (0, "[]"),
        }
        now = time.time()
        with self.transaction() as db:
            for trigger, (enabled, recipients) in defaults.items():
                db.execute(
                    "INSERT OR IGNORE INTO notification_settings(trigger, enabled, recipients, updated) VALUES (?,?,?,?)",
                    (trigger, enabled, recipients, now),
                )

    def get_notification_settings(self):
        self._ensure_notification_defaults()
        with self.connect() as db:
            rows = db.execute("SELECT trigger, enabled, recipients, updated FROM notification_settings ORDER BY trigger").fetchall()
        return [{**dict(row), "enabled": bool(row["enabled"]), "recipients": json.loads(row["recipients"])} for row in rows]

    def set_notification_setting(self, trigger, enabled, recipients, now=None):
        allowed = {"contact_form", "chat_ended", "unanswered_question", "safety_flag", "rate_limit", "monthly_faq_update"}
        if trigger not in allowed or not isinstance(enabled, bool) or not isinstance(recipients, list) or len(recipients) > 4:
            raise ValueError("Invalid notification setting")
        clean = []
        for value in recipients:
            if not isinstance(value, str) or not re.fullmatch(r"[^@\s]{1,64}@(?:cccbuild\.com|srinagubandi\.com)", value, re.I):
                raise ValueError("Recipients must use an approved company domain")
            clean.append(value.lower())
        with self.transaction() as db:
            db.execute("UPDATE notification_settings SET enabled=?, recipients=?, updated=? WHERE trigger=?",
                       (int(enabled), json.dumps(sorted(set(clean))), time.time() if now is None else float(now), trigger))
            if db.total_changes != 1:
                raise ValueError("Unknown notification setting")

    def record_notification(self, trigger, recipients, subject, status, idempotency_key, provider_id=None, now=None):
        with self.transaction() as db:
            db.execute("""INSERT INTO notification_log(trigger, recipients, subject, status, created, provider_id, idempotency_key)
                          VALUES (?,?,?,?,?,?,?)
                          ON CONFLICT(idempotency_key) DO UPDATE SET status=excluded.status, provider_id=excluded.provider_id""",
                       (trigger, json.dumps(recipients), subject[:200], status, time.time() if now is None else float(now), provider_id, idempotency_key))

    def notification_deliveries(self, limit=50):
        limit = max(1, min(int(limit), 100))
        with self.connect() as db:
            rows = db.execute("SELECT trigger, recipients, subject, status, created, provider_id, idempotency_key FROM notification_log ORDER BY created DESC LIMIT ?", (limit,)).fetchall()
        return [{**dict(row), "recipients": json.loads(row["recipients"])} for row in rows]

    def cache_get(self, key, now=None):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM cache WHERE key=? AND expires>?", (key, time.time() if now is None else now)).fetchone()
            return json.loads(row[0]) if row else None

    def cache_set(self, key, payload):
        with self.transaction() as db:
            db.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?)", (key, json.dumps(payload), time.time() + DAY))
            db.execute("DELETE FROM cache WHERE key NOT IN (SELECT key FROM cache ORDER BY expires DESC LIMIT 5000)")

    def queue_question(self, question, now=None):
        now = time.time() if now is None else now
        question = redact(question, 1000)
        norm = normalize(question)
        with self.transaction() as db:
            self._prune(db, now)
            row = db.execute("SELECT id FROM questions WHERE normalized=? AND created>=? ORDER BY id DESC LIMIT 1", (norm, now - 30 * DAY)).fetchone()
            if row:
                db.execute("UPDATE questions SET occurrences=occurrences+1,last_seen=? WHERE id=?", (now, row[0]))
                return True
            daily = db.execute("SELECT COUNT(*) FROM questions WHERE created>=?", (int(now // DAY) * DAY,)).fetchone()[0]
            pending = db.execute("SELECT COUNT(*) FROM questions WHERE state IN ('pending','digest_pending')").fetchone()[0]
            if daily >= 100 or pending >= 1000:
                return False
            db.execute("INSERT INTO questions(normalized,question,created,last_seen) VALUES (?,?,?,?)", (norm, question, now, now))
            return True

    def log_event(self, question, channel, outcome, client_hash, faq_ids=(), sources=(), model_used=None, cost_micro=0, reason="", now=None):
        now = time.time() if now is None else now
        with self.transaction() as db:
            db.execute("INSERT INTO events(created,question,channel,outcome,faq_ids,sources,model_used,cost_micro,reason,client_hash) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (now, redact(question, 1500), channel if channel in {"API", "MCP"} else "API", outcome,
                        json.dumps(list(faq_ids)), json.dumps(list(sources)), model_used, cost_micro, reason, client_hash))
            self._prune(db, now)

    def summary(self, days=7, now=None):
        now = time.time() if now is None else now
        self.prune(now)
        with self.connect() as db:
            rows = [dict(r) for r in db.execute("SELECT id,created,question,channel,outcome,faq_ids,sources,model_used,cost_micro,reason,client_hash FROM events WHERE created>=? ORDER BY created DESC,id DESC", (now - days * DAY,))]
            trend_rows = db.execute("SELECT strftime('%Y-%m-%d',created,'unixepoch') AS day,COUNT(*) AS total,SUM(outcome='answered') AS answered,SUM(outcome='needs_review') AS unanswered FROM events WHERE created>=? GROUP BY day", (now - 30 * DAY,)).fetchall()
            questions = [dict(r) for r in db.execute("SELECT id,question,created,last_seen,occurrences,state FROM questions ORDER BY created DESC LIMIT 3100")]
        top, sources, outcomes = {}, {}, {}
        for row in rows:
            row["faq_ids"] = json.loads(row["faq_ids"])
            row["sources"] = json.loads(row["sources"])
            outcomes[row["outcome"]] = outcomes.get(row["outcome"], 0) + 1
            for fid in row["faq_ids"]:
                top[fid] = top.get(fid, 0) + 1
            for url in row["sources"]:
                sources[url] = sources.get(url, 0) + 1
        by_day = {r["day"]: dict(r) for r in trend_rows}
        today = datetime.fromtimestamp(now, timezone.utc).date()
        trend = [by_day.get(str(today - timedelta(days=i)), {"day": str(today - timedelta(days=i)), "total": 0, "answered": 0, "unanswered": 0}) for i in range(29, -1, -1)]
        return {"days": days, "counts": {"total": len(rows), "answered": outcomes.get("answered", 0), "unanswered": outcomes.get("needs_review", 0), "rate_blocked": outcomes.get("rate_blocked", 0), "invalid": outcomes.get("invalid", 0)},
                "outcomes": outcomes, "top_faqs": sorted(top.items(), key=lambda x: -x[1]), "source_usage": sorted(sources.items(), key=lambda x: -x[1]),
                "events": rows, "unanswered_questions": questions, "trend": trend, "model_budget": self.budget(now),
                "review_queue_counts": {state: sum(q["state"] == state for q in questions) for state in ("pending", "digest_pending", "sent")},
                "period_cost_micro_usd": sum(r["cost_micro"] for r in rows), "retention_days": 30, "event_cap": 10000}

    def create_session(self, role="admin", now=None):
        now = time.time() if now is None else now
        raw = secrets.token_urlsafe(32)
        signature = hmac.new(self.session_key, raw.encode(), hashlib.sha256).hexdigest()
        token = raw + "." + signature
        csrf = secrets.token_urlsafe(32)
        ttl = 8 * 3600 if role in ("admin", "ben") else 600
        with self.transaction() as db:
            db.execute("DELETE FROM sessions WHERE expires < ?", (now,))
            db.execute("INSERT INTO sessions VALUES (?,?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), role, csrf, now + ttl))
            db.execute("DELETE FROM sessions WHERE token_hash NOT IN (SELECT token_hash FROM sessions ORDER BY expires DESC LIMIT 10000)")
        return token, csrf

    def session(self, token, now=None):
        if not isinstance(token, str) or len(token) > 200:
            return None
        try:
            raw, sig = token.split(".", 1)
        except ValueError:
            return None
        expected = hmac.new(self.session_key, raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        with self.connect() as db:
            row = db.execute("SELECT role,csrf,expires FROM sessions WHERE token_hash=? AND expires>?", (hashlib.sha256(token.encode()).hexdigest(), time.time() if now is None else now)).fetchone()
            return dict(row) if row else None

    def revoke_session(self, token):
        with self.transaction() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))

    def prepare_digest(self, day, cutoff, now=None):
        now = time.time() if now is None else now
        with self.transaction() as db:
            self._prune(db, now)
            row = db.execute("SELECT * FROM digests WHERE day=?", (day,)).fetchone()
            if row:
                return dict(row)
            rows = db.execute("SELECT id,question FROM questions WHERE state='pending' AND created<=? ORDER BY id LIMIT 100", (cutoff,)).fetchall()
            if not rows:
                return None
            ids = [r["id"] for r in rows]
            payload = [redact(r["question"], 1000) for r in rows]
            digest_hash = hashlib.sha256(json.dumps(ids).encode()).hexdigest()[:32]
            key = f"ccc-digest-{day}-{digest_hash}"
            db.execute("INSERT INTO digests(day,ids,payload,idempotency_key,status,created) VALUES (?,?,?,?, 'prepared',?)", (day, json.dumps(ids), json.dumps(payload), key, now))
            db.executemany("UPDATE questions SET state='digest_pending' WHERE id=?", [(i,) for i in ids])
            return dict(db.execute("SELECT * FROM digests WHERE day=?", (day,)).fetchone())

    def claim_digest(self, day, now=None):
        now = time.time() if now is None else now
        with self.transaction() as db:
            row = db.execute("SELECT * FROM digests WHERE day=?", (day,)).fetchone()
            if not row or row["status"] in {"sent", "hold"}:
                return None
            if now - row["created"] >= DAY:
                db.execute("UPDATE digests SET status='hold' WHERE day=?", (day,))
                return None
            if row["attempted"] is not None and now - row["attempted"] < 120:
                return None
            db.execute("UPDATE digests SET attempted=?,status='ambiguous' WHERE day=?", (now, day))
            return dict(row)

    def finish_digest(self, day, provider_id):
        with self.transaction() as db:
            row = db.execute("SELECT ids FROM digests WHERE day=? AND status <> 'sent'", (day,)).fetchone()
            if not row:
                return
            ids = json.loads(row[0])
            db.executemany("UPDATE questions SET state='sent' WHERE id=?", [(i,) for i in ids])
            db.execute("UPDATE digests SET status='sent',provider_id=? WHERE day=?", (provider_id, day))

    def digest_states(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT day,status,created,attempted FROM digests ORDER BY day DESC LIMIT 30")]
