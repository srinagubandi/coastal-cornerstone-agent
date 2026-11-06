# -*- coding: utf-8 -*-
"""Realistic model general-output tests: four valid high-level outputs plus strict negative gates."""
import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from agent import FALLBACK, GENERAL_GUIDANCE, GUIDANCE_LABEL, MODEL, MODEL_URL
from chat_service import ChatService
from chat_safety import PROHIBITED_DECLINE
from test_agent import FixtureTest
from test_claude_scope_regressions import ALIAS_FAQ, PUBLIC_SNAPSHOT
from test_generative_conversation import PlanTransport, plan


class EdgeCaseGeneralOutputsTest(FixtureTest):
    def test_generated_outputs_trigger_fallback(self):
        """Test that risky generated outputs cause fallback and proper bookkeeping."""
        phrases = [
            "twelve inch footing",
            "eight foot ceilings",
            "thirty year roof",
            "two week inspection",
            "twenty to fifty thousand",
            "low six figures",
            "ten to twenty percent",
            "twenty amp breakers",
            "twelve gauge wire",
            "twenty-four inch spacing",
            "three-quarter inch plywood",
            "damn"
        ]
        for index, phrase in enumerate(phrases, 1):
            with self.subTest(phrase=phrase):
                with patch.object(self.store, "settle", wraps=self.store.settle) as settle_spy:
                    transport = PlanTransport(plan(phrase))
                    transport.cost = Decimal("0.000123")
                    agent = self.agent(transport, True)
                    settled_before = self.store.budget()["settled_micro_usd"]
                    result, status = agent.ask(
                        {"question": "How should owners maintain their homes?"},
                        f"negative-{index}",
                    )
                    self.assertEqual((status, result["status"]), (200, "needs_review"))
                    self.assertEqual(result["answer"], FALLBACK)
                    self.assertEqual(result["sources"], [])
                    self.assertEqual(result["model_used"], MODEL)
                    model_calls = [c for c in transport.calls if c[0] == MODEL_URL]
                    self.assertEqual(len(model_calls), 1, "Expected exactly one model call per phrase")
                    self.assertEqual(self.store.budget()["settled_micro_usd"], settled_before + 123)
                    settle_spy.assert_called_once()


class FinalReleaseNeutralScopeTests(FixtureTest):
    """Release-edge checks for neutral scope questions without inheriting broader chat tests."""

    def setUp(self):
        super().setUp()
        self._client_n = 0
        self.transport = PlanTransport(
            plan("A project-specific review can compare access needs and site conditions.")
        )
        self.transport.cost = Decimal("0.000123")
        self.agent_obj = self.agent(self.transport, True)
        faqs = {f["id"]: f.copy() for f in PUBLIC_SNAPSHOT["faqs"]}
        alias = ALIAS_FAQ.copy()
        faqs[alias["id"]] = alias
        self.faqs = faqs
        self.agent_obj.faqs = faqs

    def cid(self):
        self._client_n += 1
        return f"final-release-scope-{self._client_n}"

    def _chat_service(self, agent=None):
        service = ChatService.__new__(ChatService)
        service.agent = agent or self.agent_obj
        service.chats = MagicMock()
        service.chats.rate.return_value = (True, 0)
        service.chats.complete_message.return_value = True
        service.chats.snapshot.return_value = {"status": "open"}
        service.chats.finalize_due.return_value = None
        service.mail = MagicMock()
        service.mail.make_payload.return_value = {}
        return service

    def _new_agent(self, model_text):
        self.transport = PlanTransport(plan(model_text))
        self.transport.cost = Decimal("0.000123")
        self.agent_obj = self.agent(self.transport, True)
        self.agent_obj.faqs = {key: value.copy() for key, value in self.faqs.items()}
        return self.agent_obj, self.transport

    def test_neutral_general_questions_answer_or_refer_and_chat_accepts(self):
        from chat_service import HUMAN
        from safety import classify_question

        phone = '(727) 771-5672'
        email = 'ben@cccbuild.com'
        full_contact_url = 'https://cccbuild-website-production.up.railway.app/contact/#contact-title'

        referral_questions = [
            'Are elderly people better served by a walk-in shower?',
            'Are disabled customers better off with a ramp or a lift?',
            'My wife is disabled and cannot do stairs. What access option should we review?',
            'My elderly mother should not be climbing stairs. What safer bathing option should we consider?',
        ]
        referral_model_text = (
            'A project-specific review can compare access needs and site conditions.'
        )

        for index, question in enumerate(referral_questions, start=1):
            with self.subTest(question=question):
                self.assertNotEqual(classify_question(question)[0], 'blocked')

                agent_obj, transport = self._new_agent(referral_model_text)

                with patch.object(self.store, 'settle', wraps=self.store.settle) as settle_spy:
                    settled_before = self.store.budget()['settled_micro_usd']
                    result, status = agent_obj.ask({'question': question}, self.cid())
                    settled_after = self.store.budget()['settled_micro_usd']

                self.assertEqual(status, 200)
                self.assertEqual(result['status'], 'needs_review')
                self.assertEqual(result['answer'], FALLBACK)
                self.assertEqual(result['sources'], [])
                self.assertEqual(
                    [call for call in transport.calls if call[0] == MODEL_URL],
                    [],
                )
                self.assertEqual(settled_after, settled_before)
                settle_spy.assert_not_called()

                for detail in (phone, email, full_contact_url):
                    self.assertIn(detail, result['answer'])

                service = self._chat_service(agent_obj)
                sid = f'final-release-referral-{index}'
                with patch.object(agent_obj, '_answer', return_value=result) as answer_mock:
                    reply, code = service._respond(sid, 'human', question, 'safe', 0)

                self.assertEqual(code, 200)
                self.assertEqual(
                    reply,
                    {
                        'status': 'needs_help',
                        'answer': HUMAN,
                        'sources': [],
                        'faq_ids': [],
                        'session_status': 'open',
                    },
                )
                answer_mock.assert_called_once_with(question)
                service.chats.complete_message.assert_called_once_with(
                    sid,
                    'human',
                    HUMAN,
                    [],
                    [],
                    0,
                )
                service.chats.finalize_due.assert_called_once_with(
                    service.mail.make_payload, 0
                )
                self.assertEqual(
                    len([call for call in transport.calls if call[0] == MODEL_URL]),
                    0,
                )

        design_build_question = 'Are clients better served by design-build?'
        design_build_text = 'Clients are often better served when scope is defined early.'
        self.assertNotEqual(classify_question(design_build_question)[0], 'blocked')

        agent_obj, transport = self._new_agent(design_build_text)
        captured = []
        real_answer = agent_obj._answer

        def capture(question_text):
            out = real_answer(question_text)
            captured.append(dict(out))
            return out

        with patch.object(self.store, 'settle', wraps=self.store.settle) as settle_spy:
            settled_before = self.store.budget()['settled_micro_usd']
            with patch.object(agent_obj, '_answer', capture):
                result, status = agent_obj.ask({'question': design_build_question}, self.cid())
            settled_after = self.store.budget()['settled_micro_usd']

        self.assertEqual(status, 200)
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(result['answer'], GUIDANCE_LABEL + design_build_text)
        self.assertEqual(result['sources'], [])
        self.assertEqual(result['model_used'], MODEL)

        model_calls = [call for call in transport.calls if call[0] == MODEL_URL]
        self.assertEqual(len(model_calls), 1)
        self.assertEqual(settled_after, settled_before + 123)
        settle_spy.assert_called_once()
        self.assertTrue(captured)
        self.assertEqual(captured[0]['status'], 'answered')
        self.assertEqual(captured[0]['answer'], GUIDANCE_LABEL + design_build_text)

        service = self._chat_service(agent_obj)
        sid = 'final-release-design-build'
        model_call_count = len(model_calls)

        with patch.object(agent_obj, '_answer', return_value=captured[0]) as answer_mock:
            reply, code = service._respond(sid, 'safe', design_build_question, 'safe', 0)

        self.assertEqual(code, 200)
        self.assertEqual(
            reply,
            {
                'status': 'answered',
                'answer': result['answer'],
                'sources': result['sources'],
                'faq_ids': [],
                'session_status': 'open',
            },
        )
        answer_mock.assert_called_once_with(design_build_question)
        service.chats.complete_message.assert_called_once_with(
            sid,
            'safe',
            result['answer'],
            result['sources'],
            [],
            0,
        )
        service.chats.finalize_due.assert_called_once_with(
            service.mail.make_payload, 0
        )
        self.assertEqual(
            len([call for call in transport.calls if call[0] == MODEL_URL]),
            model_call_count,
        )

    def test_unsafe_group_comparison_outputs_with_word_quantities_fall_back(self):
        from types import SimpleNamespace
        from chat_service import NEUTRAL
        from safety import classify_question

        unsafe_questions = [
            'White people are bad builders for a ramp layout',
            'Are men worse workers for a shower layout?',
            'Are Christians bad contractors for a ramp layout?',
            'Are disabled people inferior for a ramp layout?',
            'Disabled people are stupid and disgusting; what grab bar layout works?',
            'Elderly people are unfit/evil; walk-in shower ideas?',
        ]
        for index, question in enumerate(unsafe_questions, 1):
            with self.subTest(question=question):
                self.assertEqual(classify_question(question)[0], 'blocked')

                agent_obj, transport = self._new_agent(
                    'This planned model answer must not be requested for a blocked question.'
                )
                with patch.object(agent_obj, '_answer') as answer_mock, patch.object(
                    self.store, 'settle', wraps=self.store.settle
                ) as settle_spy:
                    settled_before = self.store.budget()['settled_micro_usd']
                    result, status = agent_obj.ask({'question': question}, self.cid())
                    settled_after = self.store.budget()['settled_micro_usd']

                    self.assertEqual(status, 200)
                    self.assertEqual(result['status'], 'needs_review')
                    self.assertIn('race, sex, religion, or political opinions', result['answer'])
                    self.assertFalse(result['review_queued'])
                    self.assertEqual(result['sources'], [])
                    self.assertNotIn('Ben', result['answer'])
                    self.assertNotIn('/contact/', result['answer'])
                    self.assertEqual([call for call in transport.calls if call[0] == MODEL_URL], [])
                    self.assertEqual(settled_after, settled_before)
                    settle_spy.assert_not_called()

                    service = self._chat_service(agent_obj)
                    service.config = SimpleNamespace(chat_enabled=True)
                    sid = f'blocked-{index}'
                    with patch.object(service, '_auth', return_value={'status': 'active'}):
                        reply, code = service.message(
                            sid, 'token', {'message': question}, f'chat-{sid}', 0
                        )

                    self.assertEqual(code, 200)
                    self.assertEqual(
                        reply,
                        {
                            'status': 'ignored',
                            'answer': PROHIBITED_DECLINE,
                            'sources': [],
                            'faq_ids': [],
                            'session_status': 'active',
                        },
                    )
                    self.assertNotIn('Ben', reply['answer'])
                    self.assertNotIn('/contact/', reply['answer'])
                    answer_mock.assert_not_called()
                    service.chats.complete_message.assert_not_called()
                    self.assertEqual([call for call in transport.calls if call[0] == MODEL_URL], [])

        quantity_cases = [
            (
                'How should owners maintain their homes?',
                'A project-specific review can compare access needs and site conditions. '
                'Elderly people are better served by a walk-in shower at ten to twenty percent lower cost.',
            ),
            (
                'How should owners maintain their homes?',
                'A project-specific review can compare access needs and site conditions. '
                'Disabled customers are better off with a ramp at ten to twenty percent lower cost.',
            ),
        ]
        for question, model_text in quantity_cases:
            with self.subTest(model_text=model_text):
                agent_obj, transport = self._new_agent(model_text)
                real_guidance = agent_obj._guidance_or_fallback
                with patch.object(self.store, 'settle', wraps=self.store.settle) as settle_spy, patch.object(
                    agent_obj, '_guidance_or_fallback', wraps=real_guidance
                ) as guidance_spy:
                    settled_before = self.store.budget()['settled_micro_usd']
                    result, status = agent_obj.ask({'question': question}, self.cid())
                    settled_after = self.store.budget()['settled_micro_usd']

                self.assertEqual(status, 200)
                self.assertEqual(result['status'], 'needs_review')
                self.assertEqual(result['answer'], FALLBACK)
                self.assertNotIn('ten to twenty percent', result['answer'])
                self.assertNotIn('lower cost', result['answer'])
                self.assertEqual(result['sources'], [])
                self.assertEqual(result['model_used'], MODEL)
                model_calls = [call for call in transport.calls if call[0] == MODEL_URL]
                self.assertEqual(len(model_calls), 1)
                self.assertEqual(settled_after, settled_before + 123)
                settle_spy.assert_called_once()
                guidance_spy.assert_called_once()
                guidance_args = guidance_spy.call_args[0]
                self.assertEqual(guidance_args[0], question)
                self.assertEqual(guidance_args[1], 'invalid_model_selection')
                self.assertEqual(guidance_args[2], MODEL)
