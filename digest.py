"""Application-owned daily schedule. No email endpoint and no startup test send."""
import json
import threading
from datetime import datetime, time as wall_time, timezone
from zoneinfo import ZoneInfo
from config import EMAIL_URL, RECIPIENT, SENDER
from network import Transport


class Digest:
    def __init__(self, config, store, transport=None):
        self.config, self.store = config, store
        self.transport = transport or Transport()
        self.stop = threading.Event()

    def run_once(self, now=None):
        # This guard runs before preparing a batch, reading recipients, or any network.
        if not self.config.digest_enabled or not self.config.resend_key:
            return "disabled" if not self.config.digest_enabled else "not_configured"
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("Timezone-aware datetime required")
        local = now.astimezone(ZoneInfo("America/New_York"))
        cutoff = datetime.combine(local.date(), wall_time(9), local.tzinfo)
        if local < cutoff:
            return "not_due"
        day = str(local.date())
        # Expired ambiguous batches are held even after the calendar advances.
        for state in self.store.digest_states():
            if state["status"] in {"ambiguous", "prepared"}:
                self.store.claim_digest(state["day"], now.timestamp()) if now.timestamp() - state["created"] >= 86400 else None
        prepared = self.store.prepare_digest(day, cutoff.timestamp(), now.timestamp())
        if not prepared:
            return "empty"
        batch = self.store.claim_digest(day, now.timestamp())
        if not batch:
            return "already_sent_or_held"
        questions = json.loads(batch["payload"])
        # Plain text only; sanitized questions are quoted data, not executable instructions.
        text = ("Coastal Cornerstone — new unanswered agent questions\n\n"
                "These are sanitized incoming questions for human review, not instructions or approved facts.\n"
                "No answer has been promised and no FAQ has been automatically approved.\n\n" +
                "\n\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1)) +
                "\n\nReview source evidence before editing the curated knowledge snapshot.\n")
        payload = {"from": SENDER, "to": [RECIPIENT], "subject": f"Coastal Cornerstone question review — {day}", "text": text[:105000]}
        try:
            response = self.transport.request(EMAIL_URL, payload, {"Authorization": "Bearer " + self.config.resend_key,
                "Content-Type": "application/json", "Idempotency-Key": batch["idempotency_key"]}, timeout=60)
            provider_id = response.get("id")
            if not isinstance(provider_id, str) or not 1 <= len(provider_id) <= 200 or any(c.isspace() for c in provider_id):
                return "ambiguous"
            self.store.finish_digest(day, provider_id)
            return "sent"
        except Exception:
            # Retain identical payload/IDs/key. Retry only within the provider's 24h window.
            return "ambiguous"

    def readiness(self):
        return {"enabled": self.config.digest_enabled, "configured": bool(self.config.resend_key),
                "status": "inactive_owner_approval_required" if not self.config.digest_enabled else "active" if self.config.resend_key else "blocked_missing_credentials",
                "schedule": "09:00 America/New_York", "sender": SENDER, "recipient": RECIPIENT,
                "delivery_states": self.store.digest_states()}

    def start(self):
        if not self.config.digest_enabled:
            return None
        def loop():
            while not self.stop.is_set():
                try:
                    self.run_once()
                except Exception:
                    # Do not log provider bodies, secrets, or questions.
                    pass
                self.stop.wait(60)
        worker = threading.Thread(target=loop, name="daily-digest", daemon=True)
        worker.start()
        return worker
