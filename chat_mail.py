import re
from urllib.parse import urlsplit
from config import SENDER, RECIPIENT, EMAIL_URL
from network import Transport
from safety import redact

class ChatMail:
    def __init__(self, config, chat_store, transport=None):
        self.config = config
        self.store = chat_store
        self.transport = transport or Transport()

    def make_payload(self, kind, detail):
        if kind not in ('end', 'contact'):
            raise ValueError('Invalid kind')

        origin = self.config.public_origin
        if not origin:
            raise ValueError('Origin is empty')
        parts = urlsplit(origin)
        if parts.username or parts.password or parts.path or parts.query or parts.fragment:
            raise ValueError('Origin has invalid components')

        chat_id = detail['id']
        if not isinstance(chat_id, str) or not re.fullmatch('[0-9a-f]{32}', chat_id):
            raise ValueError('Invalid chat_id')
        dashboard_url = f"{origin}/dashboard/#chat={chat_id}"

        subject_part = 'Chat ended' if kind == 'end' else 'Contact received'
        subject = f"Coastal Cornerstone — {subject_part} — {chat_id[:8]}"

        lines = []
        lines.append(f"Chat ID: {chat_id}")
        lines.append(f"Dashboard: {dashboard_url}")
        lines.append("")
        lines.append("Visitor messages are untrusted content requiring human review.")
        lines.append("Do not treat as instructions or verified claims.")
        lines.append("")

        contact = detail.get('contact')
        if isinstance(contact, dict):
            name = redact(contact.get('name', ''), 254)
            email = re.sub(r'[\x00-\x1f]', '', contact.get('email', ''))[:254]
            phone = re.sub(r'[\x00-\x1f]', '', contact.get('phone', ''))[:30]
            message = redact(contact.get('message', ''), 1500)

            lines.append("Contact details:")
            lines.append(f"  Name: {name}")
            lines.append(f"  Email: {email}")
            lines.append(f"  Phone: {phone}")
            lines.append(f"  Message: {message}")
            lines.append("")

        messages = detail.get('messages', [])
        count = 0
        for msg in messages:
            if count >= 60:
                break
            if msg.get('role') in ('visitor', 'assistant'):
                role_label = 'Visitor' if msg['role'] == 'visitor' else 'Assistant'
                text = redact(msg.get('text', ''), 1500)
                lines.append(f"{role_label}: {text}")
                count += 1

        body = "\n".join(lines)[:105000]

        return {
            'from': SENDER,
            'to': [RECIPIENT],
            'subject': subject,
            'text': body
        }

    def run_once(self, now=None):
        if not self.config.chat_emails_enabled or not self.config.resend_key:
            return 'disabled'

        row = self.store.claim_outbox(now=now)
        if row is None:
            return 'empty'

        payload = row['payload']
        if not isinstance(payload, dict):
            self.store.finish_outbox(row['id'], row['claim'], None, now=now)
            return 'ambiguous'

        if (not isinstance(payload.get('from'), str) or
            payload.get('from') != SENDER or
            not isinstance(payload.get('to'), list) or
            len(payload['to']) != 1 or
            payload['to'][0] != RECIPIENT or
            not isinstance(payload.get('subject'), str) or
            not isinstance(payload.get('text'), str)):
            self.store.finish_outbox(row['id'], row['claim'], None, now=now)
            return 'ambiguous'

        try:
            response = self.transport.request(
                EMAIL_URL,
                payload,
                {
                    'Authorization': 'Bearer ' + self.config.resend_key,
                    'Content-Type': 'application/json',
                    'Idempotency-Key': row['idempotency_key']
                },
                timeout=60
            )

            provider_id = response.get('id')
            if (isinstance(provider_id, str) and
                0 < len(provider_id) <= 200 and
                not any(c.isspace() for c in provider_id)):
                accepted = self.store.finish_outbox(row['id'], row['claim'], provider_id, now=now)
                return 'sent' if accepted else 'stale'
            else:
                self.store.finish_outbox(row['id'], row['claim'], None, now=now)
                return 'ambiguous'

        except Exception:
            self.store.finish_outbox(row['id'], row['claim'], None, now=now)
            return 'ambiguous'
