import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from chat_store import ChatStore
from notifications import NotificationService
from store import Store


class FakeTransport:
    def __init__(self): self.calls = []
    def request(self, url, payload, headers, timeout=60):
        self.calls.append((url, payload, headers))
        return {'id': 're_test_123'}


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ChatStore(Store(Path(self.tmp.name)))
        self.transport = FakeTransport()
        self.config = SimpleNamespace(chat_emails_enabled=True, resend_key='test-key')
        self.service = NotificationService(self.config, self.store, self.transport)

    def tearDown(self): self.tmp.cleanup()

    def test_defaults_and_multiple_recipient_rules(self):
        rows = self.service.settings()
        contact = next(x for x in rows if x['trigger'] == 'contact_form')
        self.assertTrue(contact['enabled'])
        self.service.update_setting('safety_flag', True, ['sri@srinagubandi.com', 'ben@cccbuild.com'])
        safety = next(x for x in self.service.settings() if x['trigger'] == 'safety_flag')
        self.assertEqual(safety['recipients'], ['ben@cccbuild.com', 'sri@srinagubandi.com'])
        with self.assertRaises(ValueError): self.service.update_setting('safety_flag', True, ['outside@example.com'])

    def test_test_send_is_fixed_to_sri_and_logged_without_body(self):
        result = self.service.send_test('admin-session', now=1000)
        self.assertEqual(result['status'], 'sent')
        self.assertEqual(self.transport.calls[0][1]['to'], ['sri@srinagubandi.com'])
        self.assertIn('[TEST]', self.transport.calls[0][1]['subject'])
        self.assertNotIn('text', self.store.notification_deliveries()[0])
        self.assertEqual(self.service.send_test('admin-session', now=1001)['status'], 'rate_limited')
        self.assertEqual(self.store.notification_deliveries()[0]['status'], 'sent')

    def test_trigger_send_respects_disabled_rule(self):
        self.assertEqual(self.service.maybe_send('chat_ended', 'x', 'body', 'event-1')['status'], 'disabled')
        self.service.update_setting('chat_ended', True, ['ben@cccbuild.com'])
        self.assertEqual(self.service.maybe_send('chat_ended', 'x', 'body', 'event-1')['status'], 'sent')

    def test_service_works_with_production_base_store(self):
        base_store = Store(Path(self.tmp.name) / 'base-store')
        service = NotificationService(self.config, base_store, self.transport)
        settings = service.settings()
        self.assertTrue(any(row['trigger'] == 'contact_form' for row in settings))
        self.assertEqual(service.deliveries(), [])


if __name__ == '__main__': unittest.main()
