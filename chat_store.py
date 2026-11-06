import hashlib
import hmac
import json
import re
import secrets
import time
import sqlite3
from contextlib import contextmanager

class ReviewConflict(Exception):
    pass

DAY = 86400

def _now(now):
    return time.time() if now is None else float(now)

class ChatStore:
    def __init__(self, store):
        self.store = store
        with self.store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL,
                    client TEXT NOT NULL,
                    created REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    expires REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    turns INTEGER NOT NULL DEFAULT 0,
                    processing TEXT,
                    lease_until REAL
                );
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created REAL NOT NULL,
                    sources TEXT NOT NULL DEFAULT '[]',
                    faq_ids TEXT NOT NULL DEFAULT '[]',
                    operation TEXT
                );
                CREATE TABLE IF NOT EXISTS chat_contacts (
                    session_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chat_outbox (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'prepared',
                    created REAL NOT NULL,
                    attempted REAL,
                    claim TEXT,
                    provider_id TEXT
                );
                CREATE TABLE IF NOT EXISTS notification_settings (
                    trigger TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    recipients TEXT NOT NULL DEFAULT '[]',
                    updated REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS notification_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trigger TEXT NOT NULL,
                    recipients TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created REAL NOT NULL,
                    provider_id TEXT,
                    idempotency_key TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS chat_reviews (
                    session_id TEXT PRIMARY KEY,
                    classification TEXT NOT NULL DEFAULT 'unreviewed',
                    answer_draft TEXT NOT NULL DEFAULT '',
                    admin_note TEXT NOT NULL DEFAULT '',
                    updated REAL NOT NULL,
                    updated_by TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chat_review_events (
                    id INTEGER PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    classification TEXT NOT NULL,
                    answer_draft TEXT NOT NULL,
                    admin_note TEXT NOT NULL,
                    created REAL NOT NULL,
                    updated_by TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chat_entries (
                    id INTEGER PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created REAL NOT NULL,
                    classification TEXT NOT NULL DEFAULT 'unreviewed',
                    outcome TEXT NOT NULL DEFAULT 'pending',
                    review_revision INTEGER NOT NULL DEFAULT 0,
                    reviewed_by TEXT,
                    reviewed_time REAL,
                    normalized_text TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_chat_entries_session_id ON chat_entries(session_id);
                CREATE INDEX IF NOT EXISTS idx_chat_entries_normalized_text ON chat_entries(normalized_text);
                CREATE INDEX IF NOT EXISTS idx_chat_reviews_classification ON chat_reviews(classification);
                CREATE TABLE IF NOT EXISTS chat_rates (
                    key TEXT,
                    bucket INTEGER,
                    count INTEGER NOT NULL,
                    PRIMARY KEY(key, bucket)
                );
                CREATE INDEX IF NOT EXISTS idx_chat_sessions_last_seen ON chat_sessions(last_seen);
                CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id_id ON chat_messages(session_id, id);
                CREATE INDEX IF NOT EXISTS idx_chat_outbox_status_created ON chat_outbox(status, created);
                CREATE TRIGGER IF NOT EXISTS prevent_outbox_update
                    BEFORE UPDATE OF id,session_id,kind,payload,idempotency_key,created ON chat_outbox
                    FOR EACH ROW
                    BEGIN
                        SELECT RAISE(ABORT, 'Immutable column update not allowed');
                    END;
            ''')
            defaults = {
                'contact_form': (1, '["ben@cccbuild.com"]'),
                'chat_ended': (0, '[]'),
                'unanswered_question': (0, '[]'),
                'safety_flag': (0, '[]'),
                'rate_limit': (0, '[]'),
                'monthly_faq_update': (0, '[]'),
            }
            now = time.time()
            for trigger, (enabled, recipients) in defaults.items():
                db.execute('INSERT OR IGNORE INTO notification_settings(trigger, enabled, recipients, updated) VALUES (?,?,?,?)',
                           (trigger, enabled, recipients, now))

    def get_notification_settings(self):
        with self.store.connect() as db:
            rows = db.execute('SELECT trigger, enabled, recipients, updated FROM notification_settings ORDER BY trigger').fetchall()
        return [{**dict(row), 'enabled': bool(row['enabled']), 'recipients': json.loads(row['recipients'])} for row in rows]

    def set_notification_setting(self, trigger, enabled, recipients, now=None):
        allowed = {'contact_form', 'chat_ended', 'unanswered_question', 'safety_flag', 'rate_limit', 'monthly_faq_update'}
        if trigger not in allowed or not isinstance(enabled, bool) or not isinstance(recipients, list) or len(recipients) > 4:
            raise ValueError('Invalid notification setting')
        clean = []
        for value in recipients:
            if not isinstance(value, str) or not re.fullmatch(r'[^@\s]{1,64}@(?:cccbuild\.com|srinagubandi\.com)', value, re.I):
                raise ValueError('Recipients must use an approved company domain')
            clean.append(value.lower())
        with self.store.connect() as db:
            db.execute('UPDATE notification_settings SET enabled=?, recipients=?, updated=? WHERE trigger=?',
                       (int(enabled), json.dumps(sorted(set(clean))), _now(now), trigger))
            if db.total_changes != 1:
                raise ValueError('Unknown notification setting')

    def record_notification(self, trigger, recipients, subject, status, idempotency_key, provider_id=None, now=None):
        with self.store.connect() as db:
            db.execute('''INSERT INTO notification_log(trigger, recipients, subject, status, created, provider_id, idempotency_key)
                          VALUES (?,?,?,?,?,?,?)
                          ON CONFLICT(idempotency_key) DO UPDATE SET status=excluded.status, provider_id=excluded.provider_id''',
                       (trigger, json.dumps(recipients), subject[:200], status, _now(now), provider_id, idempotency_key))

    def notification_deliveries(self, limit=50):
        limit = max(1, min(int(limit), 100))
        with self.store.connect() as db:
            rows = db.execute('SELECT trigger, recipients, subject, status, created, provider_id, idempotency_key FROM notification_log ORDER BY created DESC LIMIT ?', (limit,)).fetchall()
        return [{**dict(row), 'recipients': json.loads(row['recipients'])} for row in rows]

    def create(self, client, now=None):
        if client is None:
            client = ''
        if not isinstance(client, str) or len(client) > 200:
            raise ValueError("client must be a string and <= 200 chars")
        try:
            client.encode('utf-8')
        except UnicodeEncodeError:
            raise ValueError("client not valid UTF-8")
        now = _now(now)
        sid = secrets.token_hex(16)
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode('ascii')).hexdigest()
        client_hash = hashlib.sha256(client.encode('utf-8')).hexdigest() if client is not None else None
        with self.store.transaction() as db:
            if db.execute("SELECT COUNT(*) FROM chat_sessions").fetchone()[0] >= 10000:
                return None
            db.execute(
                "INSERT INTO chat_sessions (id, token_hash, client, created, last_seen, expires, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (sid, token_hash, client_hash, now, now, now + DAY, 'active')
            )
        return {
            'session_id': sid,
            'token': token,
            'status': 'active',
            'expires_at': now + DAY,
            'messages': []
        }

    def auth(self, sid, token, now=None):
        if not isinstance(sid, str) or not re.fullmatch(r'[a-f0-9]{32}', sid):
            return None
        if not isinstance(token, str) or not (20 <= len(token) <= 200):
            return None
        try:
            token.encode('utf-8')
        except UnicodeError:
            return None
        now = _now(now)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM chat_sessions WHERE id=?", (sid,)).fetchone()
            if row is None:
                hmac.compare_digest(token_hash, '0'*64)
                return None
            if not hmac.compare_digest(row['token_hash'], token_hash):
                return None
            if now >= row['expires']:
                return None
            return dict(row)

    def rate(self, client, kind="message", now=None):
        valid = {"create", "message", "contact", "read"}
        if not isinstance(client, str) or len(client) > 200:
            return (False, 60)
        if not isinstance(kind, str) or kind not in valid:
            return (False, 60)
        try:
            client_hash = hashlib.sha256(client.encode('utf-8')).hexdigest()
        except (UnicodeEncodeError, UnicodeDecodeError):
            return (False, 60)
        limits = {
            "create": (5, 30, 30, 500),
            "message": (5, 60, 50, 1000),
            "contact": (3, 30, 10, 200),
            "read": (120, 1200, 1000, 10000),
        }
        c_min, g_min, c_day, g_day = limits[kind]
        now_ts = int(_now(now))
        min_bucket = now_ts // 60 * 60
        day_bucket = now_ts // DAY * DAY
        dur60 = 60
        durDAY = DAY
        key_cm = f"rate:{kind}:client:{client_hash}:{dur60}"
        key_gm = f"rate:{kind}:global:{dur60}"
        key_cd = f"rate:{kind}:client:{client_hash}:{durDAY}"
        key_gd = f"rate:{kind}:global:{durDAY}"
        windows = [
            (key_cm, min_bucket, dur60, c_min),
            (key_gm, min_bucket, dur60, g_min),
            (key_cd, day_bucket, durDAY, c_day),
            (key_gd, day_bucket, durDAY, g_day),
        ]
        blocked = False
        max_wait = 1
        with self.store.transaction() as conn:
            cutoff = now_ts - 2 * DAY
            conn.execute("DELETE FROM chat_rates WHERE bucket < ?", (cutoff,))
            for key, bucket, dur, limit in windows:
                row = conn.execute(
                    "SELECT count FROM chat_rates WHERE key = ? AND bucket = ?",
                    (key, bucket)
                ).fetchone()
                current = row["count"] if row else 0
                if current >= limit:
                    blocked = True
                    wait = bucket + dur - now_ts
                    if wait <= 0:
                        wait = 0
                    ceil_wait = int(-(-wait // 1))
                    ceil_wait = max(1, ceil_wait)
                    if ceil_wait > max_wait:
                        max_wait = ceil_wait
            if not blocked:
                for key, bucket, dur, limit in windows:
                    conn.execute(
                        "INSERT INTO chat_rates (key, bucket, count) VALUES (?, ?, 1)"
                        " ON CONFLICT(key, bucket) DO UPDATE SET count = count + 1",
                        (key, bucket)
                    )
        if blocked:
            return (False, max_wait)
        return (True, 0)

    def _detail(self, db, sid):
        row = db.execute(
            "SELECT id, created, last_seen, status FROM chat_sessions WHERE id = ?",
            (sid,)
        ).fetchone()
        if row is None:
            return None

        status = row["status"]
        if status == "ending":
            status = "ended"

        messages = []
        message_rows = db.execute(
            "SELECT role, text, created, sources, faq_ids FROM chat_messages WHERE session_id = ? ORDER BY id ASC",
            (sid,)
        ).fetchall()
        for m in message_rows:
            sources = m["sources"]
            if sources is None:
                sources = []
            elif isinstance(sources, str):
                try:
                    sources = json.loads(sources)
                except (json.JSONDecodeError, TypeError):
                    sources = []
                if not isinstance(sources, list):
                    sources = []
            elif not isinstance(sources, list):
                sources = []

            faq_ids = m["faq_ids"]
            if faq_ids is None:
                faq_ids = []
            elif isinstance(faq_ids, str):
                try:
                    faq_ids = json.loads(faq_ids)
                except (json.JSONDecodeError, TypeError):
                    faq_ids = []
                if not isinstance(faq_ids, list):
                    faq_ids = []
            elif not isinstance(faq_ids, list):
                faq_ids = []

            messages.append({
                "role": m["role"],
                "text": m["text"],
                "created": m["created"],
                "sources": sources,
                "faq_ids": faq_ids,
            })

        contact = None
        contact_row = db.execute(
            "SELECT payload FROM chat_contacts WHERE session_id = ?",
            (sid,)
        ).fetchone()
        if contact_row is not None and contact_row["payload"] is not None:
            raw_contact = contact_row["payload"]
            if isinstance(raw_contact, str):
                try:
                    data = json.loads(raw_contact)
                except (json.JSONDecodeError, TypeError):
                    data = None
            elif isinstance(raw_contact, dict):
                data = raw_contact
            else:
                data = None
            if isinstance(data, dict):
                contact = {
                    "name": data.get("name"),
                    "email": data.get("email"),
                    "phone": data.get("phone"),
                    "message": data.get("message"),
                }

        email_states = {}
        outbox_rows = db.execute(
            "SELECT kind, status FROM chat_outbox WHERE session_id = ? ORDER BY id ASC",
            (sid,)
        ).fetchall()
        for o in outbox_rows:
            email_states[o["kind"]] = o["status"]

        review_row = db.execute(
            "SELECT classification, answer_draft, admin_note, updated, updated_by FROM chat_reviews WHERE session_id = ?",
            (sid,)
        ).fetchone()
        review = {
            "classification": review_row["classification"] if review_row else "unreviewed",
            "answer_draft": review_row["answer_draft"] if review_row else "",
            "admin_note": review_row["admin_note"] if review_row else "",
            "updated": review_row["updated"] if review_row else None,
            "updated_by": review_row["updated_by"] if review_row else None,
        }
        return {
            "id": row["id"],
            "created": row["created"],
            "last_seen": row["last_seen"],
            "status": status,
            "messages": messages,
            "contact": contact,
            "email_states": email_states,
            "review": review,
        }

    def snapshot(self, sid):
        if not isinstance(sid, str) or not re.fullmatch(r'[0-9a-f]{32}', sid):
            return None
        with self.store.connect() as db:
            detail = self._detail(db, sid)
            if detail is None:
                return None
            return {
                "session_id": detail["id"],
                "status": detail["status"],
                "messages": detail["messages"],
                "contact_received": bool(detail["contact"]),
                "inactivity_seconds": 900
            }

    def private_detail(self, sid):
        if not isinstance(sid, str) or not re.fullmatch(r'[0-9a-f]{32}', sid):
            return None
        with self.store.connect() as db:
            detail = self._detail(db, sid)
            if detail is None:
                return None
            entries = db.execute('SELECT id, role, text, created, classification, outcome, review_revision, reviewed_by, reviewed_time FROM chat_entries WHERE session_id=? ORDER BY id', (sid,)).fetchall()
            detail['entries'] = [dict(e) for e in entries]
            return detail

    def private_list(self):
        retention_days = 30
        with self.store.connect() as db:
            sessions = db.execute(
                "SELECT id, created, last_seen, "
                "CASE WHEN status='ending' THEN 'ended' ELSE status END AS status "
                "FROM chat_sessions ORDER BY created DESC, id DESC LIMIT 10000"
            ).fetchall()
            if not sessions:
                return {"chats": [], "retention_days": retention_days}

            msg_rows = db.execute(
                "SELECT m.session_id, COUNT(*) AS message_count, "
                "(SELECT v.text FROM chat_messages v "
                " WHERE v.session_id = m.session_id AND v.role = 'visitor' "
                " ORDER BY v.id ASC LIMIT 1) AS preview "
                "FROM chat_messages m "
                "WHERE m.session_id IN (SELECT id FROM chat_sessions ORDER BY created DESC, id DESC LIMIT 10000) "
                "GROUP BY m.session_id"
            ).fetchall()
            msg_map = {r['session_id']: r for r in msg_rows}

            contact_rows = db.execute(
                "SELECT DISTINCT session_id FROM chat_contacts "
                "WHERE session_id IN (SELECT id FROM chat_sessions ORDER BY created DESC, id DESC LIMIT 10000)"
            ).fetchall()
            contact_set = {r['session_id'] for r in contact_rows}

            outbox_rows = db.execute(
                "SELECT o.session_id, o.kind, o.status "
                "FROM chat_outbox o "
                "WHERE o.id = (SELECT MAX(o2.id) FROM chat_outbox o2 "
                "               WHERE o2.session_id = o.session_id AND o2.kind = o.kind) "
                "AND o.session_id IN (SELECT id FROM chat_sessions ORDER BY created DESC, id DESC LIMIT 10000)"
            ).fetchall()
            email_map = {}
            for r in outbox_rows:
                email_map.setdefault(r['session_id'], {})[r['kind']] = r['status']

            entry_rows = db.execute(
                "SELECT session_id, role, classification, text FROM chat_entries "
                "WHERE session_id IN (SELECT id FROM chat_sessions ORDER BY created DESC, id DESC LIMIT 10000) "
                "ORDER BY id"
            ).fetchall()
            entry_map = {}
            for r in entry_rows:
                sid = r['session_id']
                if sid not in entry_map:
                    entry_map[sid] = {'count': 0, 'classifications': {}, 'first_visitor_text': None}
                entry_map[sid]['count'] += 1
                cls = r['classification']
                entry_map[sid]['classifications'][cls] = entry_map[sid]['classifications'].get(cls, 0) + 1
                if entry_map[sid]['first_visitor_text'] is None and r['role'] == 'visitor':
                    entry_map[sid]['first_visitor_text'] = r['text']

            chats = []
            for s in sessions:
                sid = s['id']
                m = msg_map.get(sid)
                message_count = m['message_count'] if m else 0
                preview = (m['preview'] or '')[:160] if m and m['preview'] else ''
                review = db.execute("SELECT classification FROM chat_reviews WHERE session_id=?", (sid,)).fetchone()
                entry_info = entry_map.get(sid, {})
                entry_count = entry_info.get('count', 0)
                entry_classifications = entry_info.get('classifications', {})
                first_visitor_text = entry_info.get('first_visitor_text')
                if first_visitor_text and entry_classifications.get('sensitive_private', 0) == 0:
                    entry_preview = first_visitor_text[:160]
                else:
                    entry_preview = None
                chats.append({
                    'id': sid,
                    'created': s['created'],
                    'last_seen': s['last_seen'],
                    'status': s['status'],
                    'message_count': message_count,
                    'contact_received': sid in contact_set,
                    'email_states': email_map.get(sid, {}),
                    'preview': preview,
                    'classification': review['classification'] if review else 'unreviewed',
                    'entry_count': entry_count,
                    'entry_classifications': entry_classifications,
                    'entry_preview': entry_preview,
                })
        return {'chats': chats, 'retention_days': retention_days}

    def update_review(self, sid, classification, answer_draft='', admin_note='', updated_by='admin', now=None):
        allowed = {'unreviewed', 'ignore', 'needs_answer', 'faq_candidate', 'sensitive_private'}
        if not isinstance(sid, str) or not re.fullmatch(r'[0-9a-f]{32}', sid):
            return None
        if classification not in allowed:
            raise ValueError('Invalid review classification')
        if not all(isinstance(v, str) for v in (answer_draft, admin_note, updated_by)):
            raise ValueError('Review fields must be strings')
        if len(answer_draft) > 12000 or len(admin_note) > 2000 or len(updated_by) > 254:
            raise ValueError('Review field too long')
        now = _now(now)
        with self.store.transaction() as db:
            if not db.execute('SELECT 1 FROM chat_sessions WHERE id=?', (sid,)).fetchone():
                return None
            db.execute('INSERT INTO chat_reviews (session_id, classification, answer_draft, admin_note, updated, updated_by) VALUES (?, ?, ?, ?, ?, ?) '
                       'ON CONFLICT(session_id) DO UPDATE SET classification=excluded.classification, answer_draft=excluded.answer_draft, admin_note=excluded.admin_note, updated=excluded.updated, updated_by=excluded.updated_by',
                       (sid, classification, answer_draft, admin_note, now, updated_by))
            db.execute('INSERT INTO chat_review_events (session_id, classification, answer_draft, admin_note, created, updated_by) VALUES (?, ?, ?, ?, ?, ?)',
                       (sid, classification, answer_draft, admin_note, now, updated_by))
            row = db.execute('SELECT classification, answer_draft, admin_note, updated, updated_by FROM chat_reviews WHERE session_id=?', (sid,)).fetchone()
            return dict(row)

    def review_events(self, sid):
        if not isinstance(sid, str) or not re.fullmatch(r'[0-9a-f]{32}', sid):
            return []
        with self.store.connect() as db:
            return [dict(row) for row in db.execute('SELECT classification, answer_draft, admin_note, created, updated_by FROM chat_review_events WHERE session_id=? ORDER BY id DESC LIMIT 100', (sid,)).fetchall()]

    def _normalize(self, text):
        import re
        return re.sub(r'\s+', ' ', text.strip().lower())

    def capture_entry(self, sid, role, text, classification, outcome, operation_id=None, now=None):
        now = _now(now)
        normalized = self._normalize(text)
        with self.store.transaction() as db:
            cursor = db.execute(
                'INSERT INTO chat_entries (session_id, role, text, created, classification, outcome, normalized_text) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (sid, role, text, now, classification, outcome, normalized)
            )
            return cursor.lastrowid

    def update_entry(self, entry_id, classification, revision, actor, now=None):
        allowed = {'unreviewed', 'ignore', 'needs_answer', 'faq_candidate', 'sensitive_private'}
        if classification not in allowed:
            raise ValueError('Invalid classification')
        now = _now(now)
        with self.store.transaction() as db:
            row = db.execute('SELECT id, review_revision FROM chat_entries WHERE id=?', (entry_id,)).fetchone()
            if not row:
                raise ValueError('Entry not found')
            if revision is not None and row['review_revision'] != revision:
                raise ReviewConflict('Entry has been modified')
            new_rev = row['review_revision'] + 1
            db.execute('UPDATE chat_entries SET classification=?, review_revision=?, reviewed_by=?, reviewed_time=? WHERE id=?',
                       (classification, new_rev, actor, now, entry_id))
            updated_row = db.execute('SELECT * FROM chat_entries WHERE id=?', (entry_id,)).fetchone()
            return dict(updated_row) if updated_row else None

    def get_entry(self, entry_id):
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM chat_entries WHERE id=?', (entry_id,)).fetchone()
            return dict(row) if row else None

    def get_latest_entry_by_normalized(self, normalized_text):
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM chat_entries WHERE normalized_text=? ORDER BY id DESC LIMIT 1', (normalized_text,)).fetchone()
            return dict(row) if row else None

    def is_ignored(self, normalized_text):
        entry = self.get_latest_entry_by_normalized(normalized_text)
        return entry is not None and entry['classification'] == 'ignore'

    def set_entry_outcome(self, entry_id, outcome):
        with self.store.transaction() as db:
            db.execute('UPDATE chat_entries SET outcome=? WHERE id=?', (outcome, entry_id))

    def begin_message(self, sid, text, now=None):
        if not isinstance(text, str) or not (1 <= len(text) <= 1500):
            raise ValueError("text must be a string of length 1 to 1500")
        try:
            text.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("text must be valid UTF-8") from None
        now = _now(now)
        with self.store.transaction() as db:
            row = db.execute("SELECT id, status, turns, processing, lease_until, expires, last_seen FROM chat_sessions WHERE id = ?", (sid,)).fetchone()
            if row is None:
                return (None, "missing")
            if now >= row["expires"]:
                return (None, "expired")
            if row["status"] != "active":
                return (None, "ended")
            if row["processing"] is not None and row["lease_until"] is not None and row["lease_until"] > now:
                return (None, "busy")
            if row["processing"] is not None:
                self._discard(db, sid, row["processing"])
                row = db.execute("SELECT id, status, turns, processing, lease_until, expires, last_seen FROM chat_sessions WHERE id = ?", (sid,)).fetchone()
                if row is None:
                    return (None, "missing")
                if row["turns"] >= 30:
                    return (None, "turn_limit")
            else:
                if row["turns"] >= 30:
                    return (None, "turn_limit")
            op = secrets.token_hex(32)
            db.execute(
                "INSERT INTO chat_messages (session_id, role, text, created, sources, faq_ids, operation) VALUES (?, 'visitor', ?, ?, '[]', '[]', ?)",
                (sid, text, now, op)
            )
            db.execute(
                "UPDATE chat_sessions SET turns = turns + 1, last_seen = MAX(last_seen, ?), processing = ?, lease_until = ? WHERE id = ?",
                (now, op, now + 120, sid)
            )
            return (op, None)

    def complete_message(self, sid, op, answer, sources, faq_ids, now=None):
        now = _now(now)
        with self.store.transaction() as db:
            row = db.execute(
                'SELECT processing FROM chat_sessions WHERE id = ? AND status IN ("active", "ending")',
                (sid,)
            ).fetchone()
            if not op or not row or row["processing"] != op:
                return False
            db.execute(
                'INSERT INTO chat_messages (session_id, role, text, created, sources, faq_ids, operation) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (sid, 'assistant', answer[:12000], now, json.dumps(list(sources)), json.dumps(list(faq_ids)), op)
            )
            db.execute(
                'UPDATE chat_sessions SET processing = NULL, lease_until = NULL WHERE id = ?',
                (sid,)
            )
            return True

    def _discard(self, db, sid, op):
        row = db.execute("SELECT processing FROM chat_sessions WHERE id=?", (sid,)).fetchone()
        if not row or not row[0] or row[0] != op:
            return False
        cur = db.execute("DELETE FROM chat_messages WHERE session_id=? AND role='visitor' AND operation=?", (sid, op))
        deleted = cur.rowcount if cur.rowcount > 0 else 0
        db.execute("UPDATE chat_sessions SET turns = MAX(0, turns - ?) WHERE id=?", (deleted, sid))
        db.execute("UPDATE chat_sessions SET processing = NULL, lease_until = NULL WHERE id=?", (sid,))
        return True

    def abort_message(self, sid, op, now=None):
        with self.store.transaction() as db:
            return self._discard(db, sid, op)

    def put_contact(self, sid, contact, make_payload, now=None):
        now = _now(now)
        if not isinstance(contact, dict):
            raise ValueError("contact must be a dict")
        if set(contact.keys()) != {'name', 'email', 'phone', 'message'}:
            raise ValueError("contact must have exactly keys: name, email, phone, message")
        if not all(isinstance(v, str) for v in contact.values()):
            raise ValueError("all contact values must be strings")
        contact_json = json.dumps(contact, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        with self.store.transaction() as db:
            row = db.execute(
                'SELECT expires FROM chat_sessions WHERE id = ?',
                (sid,)
            ).fetchone()
            if not row:
                return 'missing'
            if now >= row['expires']:
                return 'expired'
            existing = db.execute(
                'SELECT payload FROM chat_contacts WHERE session_id = ?',
                (sid,)
            ).fetchone()
            if existing:
                if existing['payload'] == contact_json:
                    return 'duplicate'
                return 'conflict'
            db.execute(
                'INSERT INTO chat_contacts (session_id, payload, created) VALUES (?, ?, ?)',
                (sid, contact_json, now)
            )
            detail = self._detail(db, sid)
            payload = make_payload('contact', detail)
            self._enqueue(db, sid, 'contact', payload, now)
            return 'accepted'

    def request_end(self, sid, make_payload, now=None):
        now = _now(now)
        with self.store.transaction() as db:
            row = db.execute(
                'SELECT status, processing, lease_until FROM chat_sessions WHERE id = ?',
                (sid,)
            ).fetchone()
            if not row:
                return False
            if row['status'] == 'ended':
                return True
            if row['processing'] is not None and (row['lease_until'] is None or row['lease_until'] <= now):
                self._discard(db, sid, row['processing'])
                row = db.execute(
                    'SELECT status, processing FROM chat_sessions WHERE id = ?',
                    (sid,)
                ).fetchone()
                if not row:
                    return False
            if row['status'] == 'active':
                db.execute('UPDATE chat_sessions SET status = ? WHERE id = ?', ('ending', sid))
            self._finalize(db, sid, make_payload, now)
            return True

    def _finalize(self, db, sid, make_payload, now):
        row = db.execute(
            'SELECT status, processing FROM chat_sessions WHERE id = ?', (sid,)
        ).fetchone()
        if not row or row[0] != 'ending' or row[1] is not None:
            return False
        db.execute(
            'UPDATE chat_sessions SET status = ?, lease_until = NULL WHERE id = ?',
            ('ended', sid)
        )
        visitor_msg = db.execute(
            'SELECT 1 FROM chat_messages WHERE session_id = ? AND role = ? LIMIT 1',
            (sid, 'visitor')
        ).fetchone()
        if visitor_msg:
            detail = self._detail(db, sid)
            payload = make_payload('end', detail)
            self._enqueue(db, sid, 'end', payload, now)
        return True

    def _enqueue(self, db, sid, kind, payload, now):
        eid = f'{sid}:{kind}'
        ekey = f'ccc-chat-{sid}-{kind}'
        payload_json = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        db.execute(
            'INSERT OR IGNORE INTO chat_outbox (id, session_id, kind, payload, idempotency_key, status, created) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (eid, sid, kind, payload_json, ekey, 'prepared', now)
        )

    def finalize_due(self, make_payload, now=None):
        now = _now(now)
        count = 0
        with self.store.transaction() as db:
            db.execute("UPDATE chat_sessions SET status='ending' WHERE status='active' AND last_seen<=?", (now - 900,))
            rows = db.execute("SELECT id, processing FROM chat_sessions WHERE processing IS NOT NULL AND (lease_until IS NULL OR lease_until<=?)", (now,)).fetchall()
            for row in rows:
                self._discard(db, row['id'], row['processing'])
            rows = db.execute("SELECT id FROM chat_sessions WHERE status='ending' AND processing IS NULL ORDER BY created, id").fetchall()
            for row in rows:
                if self._finalize(db, row['id'], make_payload, now):
                    count += 1
        return count

    def prune(self, now=None):
        now = _now(now)
        cutoff = now - 30 * DAY
        with self.store.transaction() as db:
            db.execute('DELETE FROM chat_entries WHERE created < ?', (cutoff,))
            db.execute('DELETE FROM chat_reviews WHERE session_id NOT IN (SELECT DISTINCT session_id FROM chat_entries)')
            db.execute('DELETE FROM chat_review_events WHERE session_id NOT IN (SELECT DISTINCT session_id FROM chat_entries)')
            db.execute('DELETE FROM chat_messages WHERE session_id IN (SELECT id FROM chat_sessions WHERE created < ?)', (cutoff,))
            db.execute('DELETE FROM chat_contacts WHERE session_id IN (SELECT id FROM chat_sessions WHERE created < ?)', (cutoff,))
            db.execute('DELETE FROM chat_outbox WHERE session_id IN (SELECT id FROM chat_sessions WHERE created < ?)', (cutoff,))
            db.execute('DELETE FROM chat_sessions WHERE created < ?', (cutoff,))
            db.execute('DELETE FROM chat_rates WHERE bucket < ?', (now - 2 * DAY,))

    def claim_outbox(self, now=None):
        now = _now(now)
        with self.store.transaction() as db:
            db.execute("UPDATE chat_outbox SET status='hold' WHERE status NOT IN ('sent', 'hold') AND created <= ?", (now - DAY,))
            row = db.execute("""
                SELECT id, session_id, kind, payload, idempotency_key, status, created, attempted, claim, provider_id
                FROM chat_outbox
                WHERE status IN ('prepared', 'ambiguous')
                  AND created > ?
                  AND (attempted IS NULL OR attempted <= ?)
                ORDER BY created, id
                LIMIT 1
            """, (now - DAY, now - 120)).fetchone()
            if not row:
                return None
            claim = secrets.token_hex(16)
            db.execute("UPDATE chat_outbox SET status='ambiguous', claim=?, attempted=? WHERE id=?", (claim, now, row['id']))
            payload = json.loads(row['payload'])
            if not isinstance(payload, dict):
                raise ValueError('Payload is not a dictionary')
            return {
                'id': row['id'],
                'idempotency_key': row['idempotency_key'],
                'payload': payload,
                'status': 'ambiguous',
                'claim': claim
            }

    def finish_outbox(self, eid, claim, provider_id=None, now=None):
        if not eid or not isinstance(eid, str):
            raise ValueError('Invalid eid')
        if not claim or not isinstance(claim, str):
            raise ValueError('Invalid claim')
        if provider_id is not None:
            if not isinstance(provider_id, str) or len(provider_id) > 200 or re.search(r'\s', provider_id) or not provider_id:
                raise ValueError('Invalid provider_id')
        now = _now(now)
        with self.store.transaction() as db:
            row = db.execute("SELECT claim, status, created FROM chat_outbox WHERE id=?", (eid,)).fetchone()
            if not row:
                return False
            if not row['claim']:
                return False
            if not hmac.compare_digest(row['claim'], claim):
                return False
            if row['status'] not in ('ambiguous', 'hold'):
                return False
            if provider_id is not None:
                db.execute("UPDATE chat_outbox SET status='sent', provider_id=?, claim=NULL WHERE id=?", (provider_id, eid))
                return True
            else:
                if row['status'] == 'hold' or now - row['created'] >= DAY:
                    db.execute("UPDATE chat_outbox SET status='hold', claim=NULL WHERE id=?", (eid,))
                else:
                    db.execute("UPDATE chat_outbox SET status='ambiguous', claim=NULL WHERE id=?", (eid,))
                return True
