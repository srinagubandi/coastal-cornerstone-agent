import hashlib
import threading
import time
from config import ADMIN_EMAIL, EMAIL_URL, RECIPIENT, SENDER
from network import Transport

TRIGGERS = ('contact_form', 'chat_ended', 'unanswered_question', 'safety_flag', 'rate_limit', 'monthly_faq_update')

class NotificationService:
    def __init__(self, config, store, transport=None):
        self.config = config
        self.store = store
        self.transport = transport or Transport()
        self._test_lock = threading.Lock()
        self._last_test = {}

    def settings(self):
        return self.store.get_notification_settings()

    def update_setting(self, trigger, enabled, recipients):
        if trigger == 'contact_form' and not enabled:
            raise ValueError('The contact-form notification cannot be disabled')
        self.store.set_notification_setting(trigger, enabled, recipients)
        return self.settings()

    def deliveries(self):
        return self.store.notification_deliveries()

    def _send(self, trigger, recipients, subject, text, event_key, now=None):
        if not self.config.chat_emails_enabled or not self.config.resend_key:
            return {'status': 'disabled'}
        recipients = list(dict.fromkeys(recipients))
        if not recipients:
            return {'status': 'skipped'}
        key = 'ccc-' + hashlib.sha256((trigger + ':' + event_key).encode()).hexdigest()[:48]
        self.store.record_notification(trigger, recipients, subject, 'prepared', key, now=now)
        payload = {'from': SENDER, 'to': recipients, 'subject': subject[:200], 'text': text[:105000]}
        try:
            response = self.transport.request(EMAIL_URL, payload, {'Authorization': 'Bearer ' + self.config.resend_key, 'Content-Type': 'application/json', 'Idempotency-Key': key}, timeout=60)
            provider_id = response.get('id') if isinstance(response, dict) else None
            if not isinstance(provider_id, str) or not provider_id or any(c.isspace() for c in provider_id):
                self.store.record_notification(trigger, recipients, subject, 'ambiguous', key, now=now)
                return {'status': 'ambiguous'}
            self.store.record_notification(trigger, recipients, subject, 'sent', key, provider_id=provider_id, now=now)
            return {'status': 'sent', 'provider_id': provider_id}
        except Exception:
            self.store.record_notification(trigger, recipients, subject, 'ambiguous', key, now=now)
            return {'status': 'ambiguous'}

    def maybe_send(self, trigger, subject, text, event_key, now=None):
        if trigger not in TRIGGERS:
            raise ValueError('Unknown notification trigger')
        setting = next((x for x in self.settings() if x['trigger'] == trigger), None)
        if not setting or not setting['enabled']:
            return {'status': 'disabled'}
        recipients = setting['recipients'] or ([RECIPIENT] if trigger == 'contact_form' else [])
        return self._send(trigger, recipients, subject, text, event_key, now=now)

    def send_test(self, session_key, now=None):
        now_value = time.time() if now is None else float(now)
        with self._test_lock:
            last = self._last_test.get(session_key, 0)
            if now_value - last < 60:
                return {'status': 'rate_limited'}
            self._last_test[session_key] = now_value
        return self._send('test_email', [ADMIN_EMAIL], '[TEST] Coastal Cornerstone notification test', 'This is a notification test from the private Coastal Cornerstone dashboard.', 'test:' + str(session_key), now=now_value)
