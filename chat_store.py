import hashlib
import hmac
import json
import re
import secrets
import time
import sqlite3
from contextlib import contextmanager

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

        return {
            "id": row["id"],
            "created": row["created"],
            "last_seen": row["last_seen"],
            "status": status,
            "messages": messages,
            "contact": contact,
            "email_states": email_states,
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
            return self._detail(db, sid)

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

            chats = []
            for s in sessions:
                sid = s['id']
                m = msg_map.get(sid)
                message_count = m['message_count'] if m else 0
                preview = (m['preview'] or '')[:160] if m and m['preview'] else ''
                chats.append({
                    'id': sid,
                    'created': s['created'],
                    'last_seen': s['last_seen'],
                    'status': s['status'],
                    'message_count': message_count,
                    'contact_received': sid in contact_set,
                    'email_states': email_map.get(sid, {}),
                    'preview': preview,
                })
        return {'chats': chats, 'retention_days': retention_days}

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
