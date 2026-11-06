import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from chat_mail import ChatMail
from chat_store import ChatStore
from store import Store


class ChatMailTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ChatStore(Store(Path(self.tmp.name)))
        self.config = SimpleNamespace(public_origin='https://cccbuild-website-production.up.railway.app')
        self.mail = ChatMail(self.config, self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_contact_fields_are_present_in_plain_text_and_branded_html_escaped(self):
        payload = self.mail.make_payload('contact', {
            'id': 'a' * 32,
            'contact': {
                'name': 'A <Visitor>',
                'email': 'sri@srinagubandi.com',
                'phone': '7277715601',
                'message': 'Need an ICF wall & a callback <soon>.'
            },
            'messages': [
                {'role': 'visitor', 'text': 'Please review <this>.'},
                {'role': 'assistant', 'text': 'We can help.'},
            ],
        })
        self.assertIn('A <Visitor>', payload['text'])
        self.assertIn('sri@srinagubandi.com', payload['text'])
        self.assertIn('7277715601', payload['text'])
        self.assertIn('Need an ICF wall & a callback <soon>.', payload['text'])
        self.assertIn('#0a3d5f', payload['html'])
        self.assertIn('#9b8579', payload['html'])
        self.assertIn('Contact details', payload['html'])
        self.assertIn('sri@srinagubandi.com', payload['html'])
        self.assertIn('&lt;Visitor&gt;', payload['html'])
        self.assertIn('Need an ICF wall &amp; a callback &lt;soon&gt;.', payload['html'])
        self.assertNotIn('<Visitor>', payload['html'])
        self.assertNotIn('<soon>', payload['html'])
        self.assertIn('dashboard/#chat=' + 'a' * 32, payload['html'])

    def test_html_is_required_and_bounded_for_outbox_payloads(self):
        self.assertIsInstance(self.mail.make_payload('end', {'id': 'b' * 32, 'messages': []})['html'], str)


if __name__ == '__main__':
    unittest.main()
