"""Private owner dashboard. Public callers remain pseudonymous, not authenticated agents."""
import base64
import csv
import hashlib
from datetime import date
import hmac
import io
import json
import secrets
import threading
from config import ADMIN_EMAIL, RECIPIENT
from safety import csv_safe, redact

ADMIN_ROLES = frozenset({'admin', 'ben'})


def _decode(value):
    return base64.b64decode(value.encode("ascii"), validate=True)


def hash_spec(encoded):
    try:
        parts = encoded.split("$")
        if parts[0] == "scrypt" and len(parts) == 7:
            _, n, r, p, salt, digest, length = parts
            n, r, p, length = int(n), int(r), int(p), int(length)
            if not (32768 <= n <= 131072 and n & (n - 1) == 0 and 8 <= r <= 16 and 1 <= p <= 2 and length == 32):
                return None
            salt, digest = _decode(salt), _decode(digest)
            if len(salt) < 16 or len(salt) > 64 or len(digest) != length:
                return None
            return "scrypt", (n, r, p, salt), digest
        if parts[0] == "pbkdf2_sha256" and len(parts) == 4:
            _, iterations, salt, digest = parts
            iterations = int(iterations)
            salt, digest = _decode(salt), _decode(digest)
            if 600000 <= iterations <= 2000000 and 16 <= len(salt) <= 64 and len(digest) == 32:
                return "pbkdf2", (iterations, salt), digest
    except (ValueError, UnicodeError, TypeError):
        pass
    return None


def make_password_hash(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 1024:
        raise ValueError("Use a password of 12 to 1024 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=32768, r=8, p=1, dklen=32, maxmem=256 * 1024 * 1024)
    return "scrypt$32768$8$1$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode() + "$32"


def verify_password(password, encoded):
    spec = hash_spec(encoded)
    if not spec or not isinstance(password, str) or not 12 <= len(password) <= 1024:
        return False
    kind, params, expected = spec
    try:
        if kind == "scrypt":
            n, r, p, salt = params
            result = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32, maxmem=256 * 1024 * 1024)
        else:
            iterations, salt = params
            result = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations, dklen=32)
        return hmac.compare_digest(result, expected)
    except (ValueError, UnicodeError):
        return False


class Dashboard:
    def __init__(self, config, store, agent, digest, notifications=None):
        self.config, self.store, self.agent, self.digest, self.notifications = config, store, agent, digest, notifications
        self.hash_slots = threading.BoundedSemaphore(2)

    @property
    def enabled(self):
        return bool(self.config.public_origin and hash_spec(self.config.admin_hash))

    def verify_login(self, email, password):
        if not self.hash_slots.acquire(blocking=False):
            return False
        try:
            email_valid = isinstance(email, str) and len(email) <= 254
            admin_email = ADMIN_EMAIL
            ben_email = RECIPIENT
            if email_valid:
                email_bytes = email.encode("utf-8", errors="replace")
                is_admin = hmac.compare_digest(email_bytes, admin_email.encode())
                is_ben = hmac.compare_digest(email_bytes, ben_email.encode())
            else:
                is_admin = False
                is_ben = False
            ben_configured = bool(hash_spec(self.config.ben_admin_hash)) if self.config.ben_admin_hash is not None else False
            if is_admin:
                hash_to_check = self.config.admin_hash
                account_valid = True
            elif is_ben and ben_configured:
                hash_to_check = self.config.ben_admin_hash
                account_valid = True
            else:
                hash_to_check = self.config.admin_hash
                account_valid = False
            password_ok = verify_password(password, hash_to_check)
            return self.enabled and account_valid and password_ok
        finally:
            self.hash_slots.release()

    def csrf_ok(self, session, origin, csrf):
        return bool(session and isinstance(origin, str) and origin == self.config.public_origin and
                    isinstance(csrf, str) and hmac.compare_digest(csrf, session["csrf"]))

    def report(self):
        """Only a file-based source review; no paid report generation or historical metrics."""
        empty = {"available": False, "message": "No source-review draft has been supplied. Activity is collected only from real incoming API/MCP questions."}
        try:
            raw = self.config.report_path.read_bytes()
            if len(raw) > 100000:
                return empty
            data = json.loads(raw)
            if not isinstance(data, dict) or data.get("type") != "source_review" or not isinstance(data.get("sections"), list):
                return empty
            approved_sources = {u for f in self.agent.faqs.values() for u in f["source_urls"]}
            sections = []
            for s in data["sections"][:20]:
                if not isinstance(s, dict) or not isinstance(s.get("heading"), str) or not isinstance(s.get("text"), str):
                    return empty
                urls = s.get("source_urls")
                if not isinstance(urls, list) or not urls or not all(isinstance(u, str) and u in approved_sources for u in urls):
                    return empty
                sections.append({"heading": redact(s["heading"], 200), "text": redact(s["text"], 5000), "source_urls": urls})
            if not sections:
                return empty
            try:
                generated_at = date.fromisoformat(data.get("generated_at")).isoformat()
            except (ValueError, TypeError):
                generated_at = "Not specified"
            return {"available": True, "type": "source_review", "title": redact(data.get("title", "Source review draft"), 200),
                    "generated_at": generated_at, "sections": sections,
                    "notice": "Source-based draft for human review only. Not an activity report, not approved FAQ knowledge, and not automatically generated by this service."}
        except (OSError, ValueError, TypeError):
            return empty

    def review_queue(self):
        """Read-only private review queue; draft records never enter runtime FAQ knowledge."""
        empty = {"count": 0, "items": [], "message": "No private FAQ review queue has been imported."}
        try:
            raw = self.config.review_queue_path.read_bytes()
            if len(raw) > 500000:
                return empty
            data = json.loads(raw)
            items = data.get("questions") if isinstance(data, dict) else data
            if not isinstance(items, list):
                return empty
            safe=[]
            for item in items[:500]:
                if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("question"), str):
                    continue
                safe.append({"id": item["id"][:100], "question": redact(item["question"], 500), "category": redact(item.get("category", ""), 100), "review_status": item.get("review_status", "pending_owner_review"), "runtime_eligible": False})
            return {"count": len(safe), "items": safe, "message": "Questions only; answers require separate admin drafting and approval."}
        except (OSError, ValueError, TypeError):
            return empty

    def summary(self, days):
        result = self.store.summary(days)
        result.update({"readiness": self.agent.readiness(), "digest": self.digest.readiness(), "report": self.report(),
                       "privacy_notice": "Sanitized real incoming API/MCP questions only. Basic redaction and salted IP hashes offer limited pseudonymity, not anonymity. Without a caller credential, an AI agent identity cannot be authenticated.",
                       "retention_notice": "Metrics reflect retained events (30 days, maximum 10,000), not all-time traffic. UTC days and monthly budget; unknown questions are never auto-approved."})
        return result

    def csv_export(self, days):
        summary = self.summary(days)
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        columns = ["id", "created", "question", "channel", "outcome", "faq_ids", "sources", "model_used", "cost_micro", "reason", "client_hash"]
        writer.writerow(columns)
        for row in summary["events"]:
            writer.writerow([csv_safe(json.dumps(row[k]) if isinstance(row[k], list) else row[k] if row[k] is not None else "") for k in columns])
        return stream.getvalue().encode("utf-8")

    def notification_settings(self):
        return self.notifications.settings() if self.notifications else []

    def notification_deliveries(self):
        return self.notifications.deliveries() if self.notifications else []

    def update_notification(self, trigger, enabled, recipients, role):
        if role not in ADMIN_ROLES:
            raise PermissionError('Administrator access required')
        return self.notifications.update_setting(trigger, enabled, recipients)

    def send_notification_test(self, session_key, role):
        if role not in ADMIN_ROLES:
            raise PermissionError('Administrator access required')
        return self.notifications.send_test(session_key)
