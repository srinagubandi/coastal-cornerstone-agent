import unittest
from types import SimpleNamespace

from chat_service import ChatService


class ChatTimingTests(unittest.TestCase):
    def test_timing_sink_receives_safe_request_event(self):
        events = []
        service = ChatService.__new__(ChatService)
        service.config = SimpleNamespace(chat_timing_sink=events.append)

        timing = service._start_timing('message')
        service._record_timing(timing, 'answer_generation', timing['started'])
        service._finish_timing(timing, 200)

        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event['event'], 'chat_timing')
        self.assertEqual(event['operation'], 'message')
        self.assertEqual(event['status_code'], 200)
        self.assertRegex(event['request_id'], r'^[0-9a-f]{32}$')
        self.assertIn('answer_generation', event['stages_ms'])
        self.assertNotIn('message', event)
        self.assertNotIn('token', event)
        self.assertNotIn('email', event)

    def test_timing_without_sink_does_not_print_fast_requests(self):
        service = ChatService.__new__(ChatService)
        service.config = SimpleNamespace()
        timing = service._start_timing('message')
        service._finish_timing(timing, 200)


if __name__ == '__main__':
    unittest.main()
