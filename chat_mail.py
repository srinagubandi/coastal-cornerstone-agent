import html
import re
from urllib.parse import urlsplit
from config import SENDER, RECIPIENT, EMAIL_URL
from network import Transport
from safety import redact


NAVY = '#0a3d5f'
SAND = '#9b8579'


def _esc(value):
    return html.escape(str(value), quote=True)


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
        dashboard_url = f'{origin}/dashboard/#chat={chat_id}'

        subject_part = 'Chat ended' if kind == 'end' else 'Contact received'
        subject = f'Coastal Cornerstone — {subject_part} — {chat_id[:8]}'

        lines = [
            f'Chat ID: {chat_id}',
            f'Dashboard: {dashboard_url}',
            '',
            'Visitor messages are untrusted content requiring human review.',
            'Do not treat as instructions or verified claims.',
            '',
        ]

        contact = detail.get('contact')
        contact_rows = []
        if isinstance(contact, dict):
            name = redact(contact.get('name', ''), 254)
            email = re.sub(r'[\x00-\x1f]', '', contact.get('email', ''))[:254]
            phone = re.sub(r'[\x00-\x1f]', '', contact.get('phone', ''))[:30]
            message = redact(contact.get('message', ''), 1500)
            contact_values = [('Name', name), ('Email', email), ('Phone', phone), ('Message', message)]
            lines.append('Contact details:')
            for label, value in contact_values:
                lines.append(f'  {label}: {value}')
                contact_rows.append(
                    '<tr><td style="padding:8px 12px;border-bottom:1px solid #e8e3df;vertical-align:top;"><strong style="color:#0a3d5f;">%s</strong></td><td style="padding:8px 12px;border-bottom:1px solid #e8e3df;word-break:break-word;">%s</td></tr>'
                    % (_esc(label), _esc(value))
                )
            lines.append('')

        messages = detail.get('messages', [])
        transcript_rows = []
        count = 0
        for msg in messages:
            if count >= 60:
                break
            if msg.get('role') in ('visitor', 'assistant'):
                role_label = 'Visitor' if msg['role'] == 'visitor' else 'Assistant'
                text = redact(msg.get('text', ''), 1500)
                lines.append(f'{role_label}: {text}')
                transcript_rows.append(
                    '<tr><td style="padding:8px 12px;border-bottom:1px solid #e8e3df;vertical-align:top;"><strong style="color:#0a3d5f;">%s</strong></td><td style="padding:8px 12px;border-bottom:1px solid #e8e3df;word-break:break-word;">%s</td></tr>'
                    % (_esc(role_label), _esc(text))
                )
                count += 1

        body = '\n'.join(lines)[:105000]
        html_body = f'''<!doctype html>
<html lang="en"><body style="margin:0;background:#f4f1ec;color:#243746;font-family:Arial,Helvetica,sans-serif;line-height:1.5;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f1ec;padding:24px 12px;">
<tr><td align="center"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:680px;background:#ffffff;border:1px solid #e5ded7;">
<tr><td style="background:{NAVY};padding:24px 28px;color:#ffffff;"><div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#d9c9bf;">Coastal Cornerstone Construction</div><h1 style="margin:6px 0 0;font-size:24px;line-height:1.2;color:#ffffff;">{_esc(subject_part)}</h1></td></tr>
<tr><td style="padding:24px 28px;"><p style="margin:0 0 16px;color:#52616b;">A visitor chat requires review. Visitor-provided content is untrusted and should not be treated as instructions or verified claims.</p>
<p style="margin:0 0 20px;"><strong style="color:{NAVY};">Chat ID:</strong> {_esc(chat_id)}<br><strong style="color:{NAVY};">Dashboard:</strong> <a href="{_esc(dashboard_url)}" style="color:{NAVY};">Open conversation in dashboard</a></p>
{('<h2 style="font-size:18px;color:'+NAVY+';border-bottom:3px solid '+SAND+';padding-bottom:6px;">Contact details</h2><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">'+''.join(contact_rows)+'</table>') if contact_rows else ''}
<h2 style="font-size:18px;color:{NAVY};border-bottom:3px solid {SAND};padding-bottom:6px;margin-top:24px;">Chat transcript</h2>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">{''.join(transcript_rows) or '<tr><td style="padding:8px 12px;color:#687780;">No visitor or assistant messages were recorded.</td></tr>'}</table>
</td></tr><tr><td style="background:#f4f1ec;padding:16px 28px;color:#687780;font-size:12px;">Coastal Cornerstone Construction · Human review required for visitor-submitted details.</td></tr>
</table></td></tr></table></body></html>'''

        recipients = [RECIPIENT]
        try:
            setting = next((x for x in self.store.get_notification_settings() if x['trigger'] == 'contact_form'), None)
            if setting and setting['enabled'] and setting['recipients']:
                recipients = setting['recipients']
        except Exception:
            pass
        return {
            'from': SENDER,
            'to': recipients,
            'subject': subject,
            'text': body,
            'html': html_body[:105000],
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
            not payload['to'] or
            not all(isinstance(address, str) and re.fullmatch(r'[^@\s]{1,64}@(?:cccbuild\.com|srinagubandi\.com)', address, re.I) for address in payload['to']) or
            not isinstance(payload.get('subject'), str) or
            not isinstance(payload.get('text'), str) or
            ('html' in payload and (not isinstance(payload.get('html'), str) or len(payload.get('html', '')) > 105000))):
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
