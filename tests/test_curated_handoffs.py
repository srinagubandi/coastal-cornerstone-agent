"""Curated handoff and usefulness end-to-end tests for approved public snapshot answers."""
import json
import unittest
from unittest.mock import MagicMock

from agent import FALLBACK, GENERAL_GUIDANCE, GUIDANCE_LABEL
from chat_service import ChatService, HUMAN
from config import MODEL, MODEL_URL
from safety import classify_question
from test_agent import FixtureTest, MockTransport


PUBLIC_SNAPSHOT = {
    "version": "2026-11-04",
    "faqs": [
        {
            "id": "faq-001",
            "question": "What does Coastal Cornerstone Construction do?",
            "answer": "Coastal Cornerstone Construction manages commercial, industrial, and government-grade construction projects and builds and renovates homes in Central Florida. We coordinate owners, end users, design teams, and subcontractors from planning through construction.",
            "source_urls": [
                "https://cccbuild-3mhyn4jl.manus.space/",
                "https://cccbuild.com/"
            ],
            "tags": ["overview", "services"],
            "status": "source_verified",
            "runtime_eligible": True,
            "review_status": "pending_client_review"
        },
        {
            "id": "faq-002",
            "question": "How many years of experience does your company have?",
            "answer": "Our team brings more than 40 years of experience in design, construction, value engineering, estimating, and project management.",
            "source_urls": [
                "https://cccbuild-3mhyn4jl.manus.space/about/",
                "https://cccbuild.com/about-us/"
            ],
            "tags": ["experience", "about"],
            "status": "source_verified",
            "runtime_eligible": True,
            "review_status": "pending_client_review"
        },
        {
            "id": "faq-027",
            "question": "How do I get a cost estimate for my project?",
            "answer": "Contact us by phone, text, email, or through the project information form and describe the work you are considering. We review scope, design options, and cost estimates during the planning phase. Pricing is specific to each project and is not published at a fixed rate.",
            "source_urls": [
                "https://cccbuild-3mhyn4jl.manus.space/contact/",
                "https://cccbuild-3mhyn4jl.manus.space/process/"
            ],
            "tags": ["pricing", "contact"],
            "status": "source_verified",
            "runtime_eligible": True,
            "review_status": "pending_client_review"
        },
        {
            "id": "faq-028",
            "question": "How do I contact Coastal Cornerstone Construction?",
            "answer": "You can call or text (727) 771-5672, email ben@cccbuild.com, or submit your project details through the project information form on the Contact page.",
            "source_urls": [
                "https://cccbuild-3mhyn4jl.manus.space/contact/",
                "https://cccbuild.com/contact-us/"
            ],
            "tags": ["contact"],
            "status": "source_verified",
            "runtime_eligible": True,
            "review_status": "pending_client_review"
        },
        {
            "id": "faq-032",
            "question": "Are you licensed and insured?",
            "answer": "For current licensing, insurance, and certification details, contact Ben at ben@cccbuild.com or (727) 771-5672. The Resources page links our published capability statement.",
            "source_urls": [
                "https://cccbuild.com/",
                "https://cccbuild-3mhyn4jl.manus.space/resources/"
            ],
            "tags": ["credentials", "licensing"],
            "status": "source_verified",
            "runtime_eligible": True,
            "review_status": "pending_client_review"
        },
        {
            "id": "faq-046",
            "question": "Are you a Women-Owned Small Business (WOSB)?",
            "answer": "Yes. Coastal Cornerstone Construction LLC is a Federal Government registered SBA Women-Owned Small Business.",
            "source_urls": [
                "https://cccbuild-3mhyn4jl.manus.space/resources/"
            ],
            "tags": ["qualifications"],
            "status": "source_verified",
            "runtime_eligible": True,
            "review_status": "pending_client_review"
        },
        {
            "id": "faq-047",
            "question": "What is your Florida contractor license number?",
            "answer": "CBC1266336 (Bently Piersma - Qualifying Agent).",
            "source_urls": [
                "https://cccbuild-3mhyn4jl.manus.space/resources/"
            ],
            "tags": ["qualifications"],
            "status": "source_verified",
            "runtime_eligible": True,
            "review_status": "pending_client_review"
        },
        {
            "id": "faq-048",
            "question": "Do you have bonding capacity?",
            "answer": "Yes, we have bonding capacity for applicable projects. Contact us for details on specific project needs.",
            "source_urls": [
                "https://cccbuild-3mhyn4jl.manus.space/resources/"
            ],
            "tags": ["qualifications"],
            "status": "source_verified",
            "runtime_eligible": True,
            "review_status": "pending_client_review"
        }
    ]
}


class PlanTransport(MockTransport):
    def __init__(self, general, **kwargs):
        super().__init__(ids=[], **kwargs)
        self.general = general

    def request(self, url, body=None, headers=None, timeout=60):
        if url == MODEL_URL:
            self.calls.append((url, body, headers, timeout))
            if self.fail:
                raise TimeoutError("mock uncertainty")
            content = json.dumps({
                "company_evidence_ids": [],
                "guidance_ids": ["guidance-planning"],
                "next_step": "none",
                "general_answer": self.general
            })
            return {
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                "usage": {"cost": self.cost}
            }
        return super().request(url, body, headers, timeout)


class CuratedHandoffUsefulnessTests(FixtureTest):
    def setUp(self):
        super().setUp()
        self._client_n = 0
        self.transport = MockTransport()
        self.agent_obj = self.agent(self.transport, True)
        self.agent_obj.faqs = {f["id"]: f.copy() for f in PUBLIC_SNAPSHOT["faqs"]}

    def cid(self):
        self._client_n += 1
        return f"curated-handoff-{self._client_n}"

    @staticmethod
    def _faq(fid):
        return next(f for f in PUBLIC_SNAPSHOT["faqs"] if f["id"] == fid)

    def _chat_service(self):
        service = ChatService.__new__(ChatService)
        service.agent = self.agent_obj
        service.chats = MagicMock()
        service.chats.complete_message.return_value = True
        service.chats.snapshot.return_value = {"status": "open"}
        service.chats.finalize_due.return_value = None
        service.mail = MagicMock()
        service.mail.make_payload.return_value = {}
        return service

    def test_agent_serves_exact_human_trigger_faqs_without_model(self):
        cases = [
            ("Are you licensed and insured?", "faq-032"),
            ("Do you have bonding capacity?", "faq-048"),
            ("What is your Florida contractor license number?", "faq-047"),
        ]
        for question, fid in cases:
            with self.subTest(question=question):
                self.transport.calls.clear()
                result, status = self.agent_obj.ask({"question": question}, self.cid())
                faq = self._faq(fid)
                self.assertEqual(status, 200)
                self.assertEqual(result["status"], "answered")
                self.assertEqual(result["answer"], faq["answer"])
                self.assertEqual(result["sources"], faq["source_urls"])
                self.assertEqual(result["faq_ids"], [fid])
                self.assertIsNone(result["model_used"])
                self.assertEqual(self.transport.calls, [])

    def test_unknown_human_project_price_still_no_model(self):
        self.transport.calls.clear()
        result, status = self.agent_obj.ask(
            {"question": "How much will my kitchen remodel cost?"}, self.cid()
        )
        self.assertEqual(status, 200)
        self.assertNotEqual(result["status"], "answered")
        self.assertIsNone(result["model_used"])
        self.assertEqual(self.transport.calls, [])

    def test_chat_curated_alias_serves_before_human(self):
        cases = [
            ("are you bonded", "faq-048"),
            ("are you insured", "faq-032"),
            ("how long have you been in business", "faq-002"),
        ]
        for text, fid in cases:
            with self.subTest(text=text):
                service = self._chat_service()
                body, code = service._respond("s1", "op", text, "human", 0)
                faq = self._faq(fid)
                self.assertEqual(code, 200)
                self.assertEqual(body["status"], "answered")
                self.assertEqual(body["answer"], faq["answer"])
                self.assertEqual(body["sources"], faq["source_urls"])
                self.assertEqual(body["faq_ids"], [fid])

    def test_chat_faq027_project_handoff_retained(self):
        service = self._chat_service()
        body, code = service._respond(
            "s1", "op", "How do I get a cost estimate for my project?", "human", 0
        )
        self.assertEqual(code, 200)
        self.assertEqual(body["status"], "needs_help")
        self.assertEqual(body["answer"], HUMAN)
        self.assertEqual(body["faq_ids"], [])

    def test_source_approved_business_facts_no_model(self):
        cases = [
            ("What does Coastal Cornerstone Construction do?", "faq-001"),
            ("How many years of experience does your company have?", "faq-002"),
            ("How do I contact Coastal Cornerstone Construction?", "faq-028"),
            ("Are you a Women-Owned Small Business (WOSB)?", "faq-046"),
        ]
        for question, fid in cases:
            with self.subTest(question=question):
                self.transport.calls.clear()
                result, status = self.agent_obj.ask({"question": question}, self.cid())
                faq = self._faq(fid)
                self.assertEqual(status, 200)
                self.assertEqual(result["status"], "answered")
                self.assertEqual(result["answer"], faq["answer"])
                self.assertEqual(result["faq_ids"], [fid])
                self.assertIsNone(result["model_used"])
                self.assertEqual(self.transport.calls, [])

    def test_company_founding_not_invented(self):
        self.transport.calls.clear()
        result, status = self.agent_obj.ask(
            {"question": "When was the company founded?"}, self.cid()
        )
        self.assertEqual(status, 200)
        self.assertNotEqual(result["status"], "answered")
        self.assertIsNone(result["model_used"])
        self.assertEqual(self.transport.calls, [])
        self.assertNotIn("founded", result["answer"].lower())

    def test_neutral_safety_terms_are_not_off_topic(self):
        for question in [
            "white roof vs black roof heat gain",
            "male vs female threaded fittings",
            "church facility remodel",
            "accessibility grab bars in a bathroom remodel",
        ]:
            with self.subTest(question=question):
                kind, _ = classify_question(question)
                self.assertNotEqual(kind, "blocked")

    def test_neutral_general_questions_reach_paid_mock_general_guidance(self):
        general = (
            "For roof color choices, lighter colors generally reflect more sunlight and can reduce heat gain. "
            "For threaded fittings, installation depends on the pipe material and thread type."
        )
        for question in [
            "white roof vs black roof heat gain",
            "male vs female threaded fittings",
        ]:
            with self.subTest(question=question):
                transport = PlanTransport(general)
                agent = self.agent(transport, True)
                agent.faqs = self.agent_obj.faqs
                result, status = agent.ask({"question": question}, self.cid())
                self.assertEqual(status, 200)
                self.assertEqual(result["status"], "answered")
                self.assertIn(GUIDANCE_LABEL, result["answer"])
                self.assertIn(general, result["answer"])
                self.assertEqual(result["model_used"], MODEL)
                self.assertTrue(any(url == MODEL_URL for (url, body, headers, timeout) in transport.calls))
