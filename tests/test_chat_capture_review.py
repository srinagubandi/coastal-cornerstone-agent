import json
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from chat_service import ChatService
from chat_store import ChatStore, ReviewConflict
from chat_safety import NEUTRAL, PROHIBITED_DECLINE
from config import Config
from store import Store


class MockAgent:
    def __init__(self):
        self.faqs = {
            'faq-001': {
                'id': 'faq-001',
                'question': 'What does CCC do?',
                'answer': 'CCC builds custom homes.',
                'source_urls': ['https://cccbuild.com/'],
                'status': 'source_verified',
                'runtime_eligible': True
            }
        }
        self.calls = []

    def answered(self, ids):
        self.calls.append(('answered', ids))
        return {
            'status': 'answered',
            'answer': self.faqs[ids[0]]['answer'],
            'sources': self.faqs[ids[0]]['source_urls'],
            'faq_ids': ids
        }

    def _answer(self, text):
        self.calls.append(('_answer', text))
        return {
            'status': 'needs_help',
            'answer': 'I need help with that.',
            'sources': [],
            'faq_ids': []
        }

    def fallback(self, text, reason):
        pass

    def rebuild_conversation(self, result):
        return result


class MockMail:
    def make_payload(self, *args, **kwargs):
        return {}

    def run_once(self, now=None):
        pass


class TestChatCaptureReview(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = replace(
            Config(),
            data_dir=self.root / 'private',
            chat_enabled=True,
            chat_emails_enabled=False,
            api_key='',
            resend_key='',
            admin_hash='',
            public_origin='https://unit-test.example'
        )
        self.store = Store(self.config.data_dir)
        self.chat_store = ChatStore(self.store)
        self.agent = MockAgent()
        self.service = ChatService(self.config, self.store, self.agent)
        self.service.mail = MockMail()  # avoid real mail
        # Create a session for testing
        self.client_ip = '127.0.0.1'
        chat = self.chat_store.create(self.client_ip)
        self.sid = chat['session_id']
        self.token = chat['token']

    def tearDown(self):
        self.tmp.cleanup()

    def _send(self, message):
        return self.service.message(self.sid, self.token, {'message': message}, self.client_ip)

    def test_blocked_message_captured(self):
        # Send a message that will be blocked by safety (e.g., NSFW)
        resp, code = self._send('pornography is bad')
        self.assertEqual(code, 200)
        self.assertEqual(resp['status'], 'ignored')
        self.assertEqual(resp['answer'], PROHIBITED_DECLINE)
        # Check entry captured
        detail = self.chat_store.private_detail(self.sid)
        self.assertIn('entries', detail)
        entries = detail['entries']
        self.assertEqual(len(entries), 2)  # visitor + assistant
        visitor = entries[0]
        self.assertEqual(visitor['role'], 'visitor')
        self.assertEqual(visitor['text'], 'pornography is bad')
        self.assertEqual(visitor['classification'], 'ignore')
        self.assertEqual(visitor['outcome'], 'ignored')
        assistant = entries[1]
        self.assertEqual(assistant['role'], 'assistant')
        self.assertEqual(assistant['text'], PROHIBITED_DECLINE)
        # Public snapshot must not contain entries
        snap = self.chat_store.snapshot(self.sid)
        self.assertNotIn('entries', snap)
        self.assertNotIn('pornography', json.dumps(snap))

    def test_repeated_blocked_phrase_keeps_specific_decline(self):
        first, first_code = self._send('pornography is bad')
        second, second_code = self._send('pornography is bad')
        self.assertEqual((first_code, second_code), (200, 200))
        self.assertEqual(first['answer'], PROHIBITED_DECLINE)
        self.assertEqual(second['answer'], PROHIBITED_DECLINE)

    def test_greeting_captured(self):
        resp, code = self._send('Hello')
        self.assertEqual(code, 200)
        self.assertEqual(resp['status'], 'ignored')
        detail = self.chat_store.private_detail(self.sid)
        entries = detail['entries']
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]['text'], 'Hello')
        self.assertEqual(entries[0]['classification'], 'ignore')

    def test_abort_retains_raw_entry(self):
        # Simulate a provider failure by making service._message return an error
        original_message = self.service._message
        def fake_message(sid, token, body, client, now=None, timing=None):
            return ({'error': 'provider unavailable'}, 503)
        self.service._message = fake_message
        try:
            resp, code = self._send('What is your pricing?')
            self.assertEqual(code, 503)
        finally:
            self.service._message = original_message
        # Entry should still exist with outcome provider_failed
        detail = self.chat_store.private_detail(self.sid)
        entries = detail['entries']
        self.assertTrue(any(e['role'] == 'visitor' and e['outcome'] == 'provider_failed' for e in entries))
        # The raw text must be preserved
        visitor_entry = [e for e in entries if e['role'] == 'visitor'][0]
        self.assertEqual(visitor_entry['text'], 'What is your pricing?')

    def test_duplicate_request_id_does_not_create_second_turn(self):
        body = {'message': 'What does CCC do?', 'request_id': '01234567-89ab-cdef-0123-456789abcdef'}
        first, first_code = self.service.message(self.sid, self.token, body, self.client_ip)
        second, second_code = self.service.message(self.sid, self.token, body, self.client_ip)
        self.assertEqual(first_code, 200)
        self.assertEqual(second_code, 409)
        self.assertIn('already being processed', second['error'])
        detail = self.chat_store.private_detail(self.sid)
        self.assertEqual(len([e for e in detail['entries'] if e['role'] == 'visitor']), 1)

    def test_sensitive_classification(self):
        resp, code = self._send('my email is test@example.com and password is secret')
        self.assertEqual(code, 200)
        detail = self.chat_store.private_detail(self.sid)
        entries = detail['entries']
        visitor = [e for e in entries if e['role'] == 'visitor'][0]
        self.assertEqual(visitor['classification'], 'sensitive_private')
        # Public snapshot must not expose raw text
        snap = self.chat_store.snapshot(self.sid)
        self.assertNotIn('test@example.com', json.dumps(snap))

    def test_public_snapshot_no_raw_field(self):
        self._send('What does CCC do?')
        snap = self.chat_store.snapshot(self.sid)
        self.assertNotIn('entries', snap)
        for msg in snap['messages']:
            self.assertNotIn('test@example.com', msg['text'])

    def test_auth_required_no_capture(self):
        # Use invalid token
        resp, code = self.service.message(self.sid, 'bad-token', {'message': 'test'}, self.client_ip)
        self.assertEqual(code, 401)
        detail = self.chat_store.private_detail(self.sid)
        self.assertEqual(detail['entries'], [])  # no entries created

    def test_rateblocked_capture(self):
        # Exhaust rate limit for this client
        for _ in range(5):
            self.chat_store.rate(self.client_ip, 'message')
        resp, code = self._send('Another message')
        self.assertEqual(code, 429)
        detail = self.chat_store.private_detail(self.sid)
        entries = detail['entries']
        visitor = [e for e in entries if e['role'] == 'visitor'][0]
        self.assertEqual(visitor['outcome'], 'rate_blocked')
        self.assertEqual(visitor['text'], 'Another message')

    def test_classification_change_and_conflict(self):
        # Send a message and get its entry
        self._send('What does CCC do?')
        detail = self.chat_store.private_detail(self.sid)
        entry = detail['entries'][0]
        entry_id = entry['id']
        rev = entry['review_revision']
        # Update classification
        updated = self.chat_store.update_entry(entry_id, 'faq_candidate', rev, 'admin')
        self.assertEqual(updated['classification'], 'faq_candidate')
        self.assertEqual(updated['review_revision'], rev + 1)
        # Conflict on stale revision
        with self.assertRaises(ReviewConflict):
            self.chat_store.update_entry(entry_id, 'ignore', rev, 'admin')
        # Invalid classification raises ValueError
        with self.assertRaises(ValueError):
            self.chat_store.update_entry(entry_id, 'invalid', None, 'admin')

    def test_ignore_exact_future(self):
        # First, send a normal message
        self._send('What does CCC do?')
        # Admin marks the entry as ignore
        detail = self.chat_store.private_detail(self.sid)
        entry = detail['entries'][0]
        self.chat_store.update_entry(entry['id'], 'ignore', entry['review_revision'], 'admin')
        # Now send the same normalized text again (should be ignored without model call)
        self.agent.calls.clear()
        resp, code = self._send('What does CCC do?')
        self.assertEqual(code, 200)
        self.assertEqual(resp['status'], 'ignored')
        self.assertEqual(resp['answer'], NEUTRAL)
        # No model calls should have been made
        self.assertEqual(len(self.agent.calls), 0)
        # A new entry should be captured with classification 'ignore'
        detail = self.chat_store.private_detail(self.sid)
        new_entries = [e for e in detail['entries'] if e['role'] == 'visitor' and e['text'] == 'What does CCC do?']
        self.assertEqual(len(new_entries), 2)
        self.assertTrue(all(e['classification'] == 'ignore' for e in new_entries))
        # Admin reverses ignore by updating the latest entry
        latest_visitor = new_entries[-1]
        self.chat_store.update_entry(latest_visitor['id'], 'faq_candidate', latest_visitor['review_revision'], 'admin')
        # Now sending again should go through to model
        self.agent.calls.clear()
        resp, code = self._send('What does CCC do?')
        self.assertEqual(code, 200)
        self.assertNotEqual(resp['status'], 'ignored')
        self.assertGreater(len(self.agent.calls), 0)

    def test_prune_entries(self):
        # Create an old entry
        old_now = time.time() - 31 * 86400
        self.chat_store.capture_entry(self.sid, 'visitor', 'old message', 'unreviewed', 'pending', now=old_now)
        # Prune
        self.chat_store.prune(now=time.time())
        detail = self.chat_store.private_detail(self.sid)
        self.assertEqual(detail['entries'], [])  # session itself may be pruned if old enough, but we only test entry removal
        # Actually, prune deletes sessions older than 30 days, so the session might be gone.
        # We'll just check that the entry is not present.
        with self.store.connect() as db:
            count = db.execute('SELECT COUNT(*) FROM chat_entries WHERE session_id=?', (self.sid,)).fetchone()[0]
            self.assertEqual(count, 0)

    def test_no_new_runtime_cost_for_ignored(self):
        # Mark a text as ignored
        self._send('ignore me')
        detail = self.chat_store.private_detail(self.sid)
        entry = detail['entries'][0]
        self.chat_store.update_entry(entry['id'], 'ignore', entry['review_revision'], 'admin')
        # Clear agent calls
        self.agent.calls.clear()
        # Send same text
        self._send('ignore me')
        # No model calls
        self.assertEqual(len(self.agent.calls), 0)


if __name__ == '__main__':
    unittest.main()
