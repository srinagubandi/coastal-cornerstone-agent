import threading
import time
import re
import json
import uuid

from chat_store import ChatStore
from chat_mail import ChatMail
from chat_safety import screen_message, validate_contact, NEUTRAL, PROHIBITED_DECLINE, OFF_TOPIC_DECLINE, HUMAN
from agent import valid_source
from safety import classify_question

class ChatService:
    def __init__(self, config, store, agent, transport=None):
        self.config = config
        self.store = store
        self.agent = agent
        self.chats = ChatStore(store)
        self.mail = ChatMail(config, self.chats, transport)
        self.stop = threading.Event()
        self.worker = None
        self.worker_lock = threading.Lock()

    def _start_timing(self, operation):
        return {
            'request_id': uuid.uuid4().hex,
            'operation': operation,
            'started': time.perf_counter(),
            'stages': {},
        }

    def _record_timing(self, timing, name, started):
        if timing is not None:
            timing['stages'][name] = round((time.perf_counter() - started) * 1000, 2)

    def _finish_timing(self, timing, status_code):
        if timing is None:
            return
        total_ms = round((time.perf_counter() - timing['started']) * 1000, 2)
        event = {
            'event': 'chat_timing',
            'request_id': timing['request_id'],
            'operation': timing['operation'],
            'status_code': status_code,
            'total_ms': total_ms,
            'stages_ms': timing['stages'],
        }
        sink = getattr(self.config, 'chat_timing_sink', None)
        if callable(sink):
            sink(event)
        elif total_ms >= 10000:
            print(json.dumps(event, separators=(',', ':')), flush=True)

    def _classify_text(self, raw_text):
        import re
        # Credentials/PII patterns
        if re.search(r'(?i)(password|credential|api[_\s]?key|secret|access[_\s]?token|bearer[_\s]?token|sk-[a-z0-9_-]+|re_[a-z0-9_-]+|eyJ|BEGIN\s+PRIVATE\s+KEY|[0-9]{3}-[0-9]{2}-[0-9]{4}|\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b|[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', raw_text):
            return 'sensitive_private'
        # Prohibited/injection patterns
        if re.search(r'(?i)(ignore|disregard|override).{0,100}(instructions|prompt)|(you are now)|(run|execute).{0,100}(code|script|command)|(reveal|exfiltrate).{0,100}(secret|password|system prompt)|(system|developer).{0,100}(prompt|message|instructions)', raw_text):
            return 'ignore'
        # Greeting pattern
        if re.match(r'^\s*(hi|hello|thanks|thank\s?you)\s*[!?.]*\s*$', raw_text, re.IGNORECASE):
            return 'ignore'
        # FAQ match
        if self._curated_ids(raw_text):
            return 'faq_candidate'
        return 'needs_answer'

    def _auth(self, sid, token, now=None):
        if getattr(self.config, 'chat_enabled', False):
            return self.chats.auth(sid, token, now)
        return None

    def _blocked_answer(self, raw_text):
        try:
            _kind, reason = classify_question(raw_text)
            if reason in ('religious or political debate', 'hateful or discriminatory judgment', 'sexual content', 'explicit slur or abuse'):
                return PROHIBITED_DECLINE
            if reason in ('off-topic', 'arbitrary off-topic'):
                return OFF_TOPIC_DECLINE
        except Exception:
            pass
        return NEUTRAL


    def create(self, client, now=None):
        try:
            if not getattr(self.config, 'chat_enabled', False):
                return ({'error': 'Our virtual assistant is temporarily unavailable. For immediate assistance, please call (727) 771-5672, email ben@cccbuild.com, or use the public contact form on our website.'}, 404)
            self.chats.prune(now)
            allowed, retry = self.chats.rate(client, 'create', now)
            if not allowed:
                return ({'error': "We've received several messages from you in a short period. To ensure a smooth experience for everyone, please wait a moment before sending another message.", 'retry_after': retry}, 429)
            chat = self.chats.create(client, now)
            if chat is None:
                return ({'error': 'Our chat is currently handling more conversations than usual. Please try again shortly, or call (727) 771-5672, email ben@cccbuild.com, or use the public contact form.'}, 429)
            return (chat, 201)
        except Exception:
            return ({'error': "Our chat service is temporarily unable to connect. Please call (727) 771-5672, email ben@cccbuild.com, or use the public contact form on our website. We're happy to assist you directly."}, 503)

    def snapshot(self, sid, token, now=None):
        try:
            if not getattr(self.config, 'chat_enabled', False):
                return ({'error': 'Our virtual assistant is temporarily unavailable. For immediate assistance, please call (727) 771-5672, email ben@cccbuild.com, or use the public contact form on our website.'}, 404)
            if self._auth(sid, token, now) is None:
                return ({'error': "Your chat session has expired or is no longer available. Please start a new chat or contact us directly by calling (727) 771-5672, emailing ben@cccbuild.com, or using the public contact form."}, 401)
            self.chats.finalize_due(self.mail.make_payload, now)
            public = self.chats.snapshot(sid)
            if not public:
                return {'error': "Your chat session has expired or is no longer available. Please start a new chat or contact us directly by calling (727) 771-5672, emailing ben@cccbuild.com, or using the public contact form."}, 401
            return {
                'session_id': public['session_id'],
                'status': public['status'],
                'messages': public['messages'],
                'contact_received': public['contact_received'],
                'inactivity_seconds': 900
            }, 200
        except Exception:
            return {'error': "Our chat service is temporarily unable to connect. Please call (727) 771-5672, email ben@cccbuild.com, or use the public contact form on our website. We're happy to assist you directly."}, 503

    def _approved(self, result):
        H = ('needs_help', HUMAN, [], [])
        try:
            public = self.agent.rebuild_conversation(result)
            if not isinstance(public, dict) or public.get('status') != 'answered':
                return H
            for k in ('status', 'answer', 'sources', 'faq_ids'):
                if k in result and result[k] != public.get(k):
                    return H
            answer = public.get('answer')
            if not isinstance(answer, str) or not answer.strip() or len(answer) > 12000:
                return H
            sources = public.get('sources')
            if not isinstance(sources, list):
                return H
            for u in sources:
                if not isinstance(u, str) or not u.startswith('https://') or not valid_source(u):
                    return H
            faq_ids = public.get('faq_ids')
            if not isinstance(faq_ids, list) or len(faq_ids) > 3 or len(set(faq_ids)) != len(faq_ids):
                return H
            for fid in faq_ids:
                faq = self.agent.faqs.get(fid) if isinstance(fid, str) else None
                if not faq or faq.get('status') != 'source_verified' or faq.get('runtime_eligible') is not True:
                    return H
                if not isinstance(faq.get('answer'), str) or not faq['answer']:
                    return H
                urls = faq.get('source_urls')
                if not isinstance(urls, list) or not urls:
                    return H
                for u in urls:
                    if not isinstance(u, str) or not u.startswith('https://') or not valid_source(u):
                        return H
            if not faq_ids:
                return ('answered', answer, list(sources), list(faq_ids))
            return ('answered', answer, list(sources), list(faq_ids))
        except Exception:
            return H

    def message(self, sid, token, body, client, now=None):
        timing = self._start_timing('message')
        status_code = None
        try:
            if not getattr(self.config, 'chat_enabled', False):
                return {'error': 'Our virtual assistant is temporarily unavailable. For immediate assistance, please call (727) 771-5672, email ben@cccbuild.com, or use the public contact form on our website.'}, 404
            screen_body = {'message': body.get('message')} if isinstance(body, dict) else body
            kind, text = screen_message(screen_body)
            if kind == 'invalid' or (kind != 'blocked' and not text):
                return {'error': "We couldn't understand that message. Please enter a question about Coastal Cornerstone Construction or try again."}, 400
            raw_text = body['message']
            auth = self._auth(sid, token, now)
            if auth is None:
                return {'error': "Your chat session has expired or is no longer available. Please start a new chat or contact us directly by calling (727) 771-5672, emailing ben@cccbuild.com, or using the public contact form."}, 401
            request_id = body.get('request_id') if isinstance(body, dict) else None
            if not isinstance(request_id, str) or not re.fullmatch(r'(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})', request_id):
                request_id = None
            if request_id and self.chats.has_request_id(sid, request_id):
                return {'error': 'This message is already being processed. Please wait for the current answer before trying again.'}, 409
            # Check ignore
            normalized = self.chats._normalize(raw_text)
            if kind != 'blocked' and self.chats.is_ignored(normalized):
                try:
                    self.chats.capture_entry(sid, 'visitor', raw_text, 'ignore', 'ignored', now=now)
                    self.chats.capture_entry(sid, 'assistant', NEUTRAL, 'ignore', 'ignored', now=now)
                except Exception:
                    pass
                session_status = 'active' if auth.get('status', 'active') not in ('ending','ended') else 'ended'
                return {
                    'status': 'ignored',
                    'answer': NEUTRAL,
                    'sources': [],
                    'faq_ids': [],
                    'session_status': session_status,
                }, 200
            # Classify
            if kind == 'blocked':
                classification = self._classify_text(raw_text)
                if classification != 'sensitive_private':
                    classification = 'ignore'
            else:
                classification = self._classify_text(raw_text)
            visitor_entry_id = None
            try:
                visitor_entry_id = self.chats.capture_entry(sid, 'visitor', raw_text, classification, 'pending', now=now)
            except Exception:
                pass
            response, status_code = self._message(sid, token, body, client, now, timing)
            if status_code == 200:
                outcome = response.get('status', 'unknown')
                answer = response.get('answer', '')
            elif status_code == 429:
                outcome = 'rate_blocked'
                answer = ''
            elif status_code == 503:
                outcome = 'provider_failed'
                answer = ''
            else:
                outcome = 'error'
                answer = ''
            if visitor_entry_id is not None:
                try:
                    self.chats.set_entry_outcome(visitor_entry_id, outcome)
                    if answer:
                        self.chats.capture_entry(sid, 'assistant', answer, classification, outcome, now=now)
                except Exception:
                    pass
            return response, status_code
        except Exception:
            return {'error': "Our chat service is temporarily unable to connect. Please call (727) 771-5672, email ben@cccbuild.com, or use the public contact form on our website. We're happy to assist you directly."}, 503
        finally:
            self._finish_timing(timing, status_code or 503)

    def _message(self, sid, token, body, client, now=None, timing=None):
        try:
            if not getattr(self.config, 'chat_enabled', False):
                return {'error': 'Our virtual assistant is temporarily unavailable. For immediate assistance, please call (727) 771-5672, email ben@cccbuild.com, or use the public contact form on our website.'}, 404
            screen_body = {'message': body.get('message')} if isinstance(body, dict) else body
            kind, text = screen_message(screen_body)
            if kind == 'invalid' or (kind != 'blocked' and not text):
                return {'error': "We couldn't understand that message. Please enter a question about Coastal Cornerstone Construction or try again."}, 400
            auth = self._auth(sid, token, now)
            if auth is None:
                return {'error': "Your chat session has expired or is no longer available. Please start a new chat or contact us directly by calling (727) 771-5672, emailing ben@cccbuild.com, or using the public contact form."}, 401
            auth_status = auth.get('status', 'active')
            session_status = 'ended' if auth_status in ('ending','ended') else 'active'
            allowed, retry = self.chats.rate(client, 'message', now)
            if not allowed:
                return {'error': "We've received several messages from you in a short period. To ensure a smooth experience for everyone, please wait a moment before sending another message.", 'retry_after': retry}, 429
            greeting_re = re.compile(r'^\s*(hi|hello|thanks|thank\s?you)\s*[!?.]*\s*$', re.IGNORECASE)
            if kind == 'blocked' or greeting_re.match(text):
                return {
                    'status': 'ignored',
                    'answer': self._blocked_answer(body['message']) if kind == 'blocked' else "Hi, I'm Coastal Cornerstone Construction's assistant. Ask me about our services, the areas we serve, ICF construction, our experience, or how to get a quote. For anything specific to your project, you can reach Ben at ben@cccbuild.com or (727) 771-5672.",
                    'sources': [],
                    'faq_ids': [],
                    'session_status': session_status,
                }, 200
            self.chats.finalize_due(self.mail.make_payload, now)
            request_id = body.get('request_id') if isinstance(body, dict) else None
            if not isinstance(request_id, str) or not re.fullmatch(r'(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})', request_id):
                request_id = None
            op, reason = self.chats.begin_message(sid, text, request_id, now)
            if not op:
                if reason in ('missing', 'expired'):
                    return {'error': "Your chat session has expired or is no longer available. Please start a new chat or contact us directly by calling (727) 771-5672, emailing ben@cccbuild.com, or using the public contact form."}, 401
                elif reason == 'ended':
                    return {'error': 'This chat has ended. Please start a new chat or contact us directly.'}, 409
                elif reason == 'turn_limit':
                    return {'error': 'This chat has reached its message limit. Please start a new chat or contact us directly.'}, 409
                elif reason == 'busy':
                    return {'error': "I'm still working through your previous message. Please allow a moment before sending another. If you need help now, call (727) 771-5672, email ben@cccbuild.com, or use the public contact form."}, 409
                elif reason == 'duplicate':
                    return {'error': 'This message is already being processed. Please wait for the current answer before trying again.'}, 409
                else:
                    return {'error': "Our chat service is temporarily unable to connect. Please call (727) 771-5672, email ben@cccbuild.com, or use the public contact form on our website. We're happy to assist you directly."}, 503
            return self._respond(sid, op, text, kind, now, timing)
        except Exception:
            return {'error': "Our chat service is temporarily unable to connect. Please call (727) 771-5672, email ben@cccbuild.com, or use the public contact form on our website. We're happy to assist you directly."}, 503

    def _curated_ids(self, text):
        from safety import normalize
        import re
        profanity_patterns = [
            r'\bthe\s+hell\b',
            r'\bhell\b',
            r'\bd(a|e)mn\b',
            r'\bsh[i1]t\b',
            r'\bf[u*]ck\b',
            r'\bass\b',
            r'\bbastard\b',
            r'\bcrap\b'
        ]
        cleaned = text
        for pat in profanity_patterns:
            cleaned = re.sub(pat, '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        norm = normalize(cleaned)
        for faq_id, faq_data in self.agent.faqs.items():
            if faq_data.get('status') == 'source_verified' and faq_data.get('runtime_eligible') is True:
                if normalize(faq_data['question']) == norm:
                    return [faq_id]
        alias_map = {
            "what construction services does coastal cornerstone construction offer": "faq-001",
            "where are you located and what areas do you serve": "faq-004",
            "are you licensed and insured": "faq-032",
            "do you do icf construction and what is it": "faq-010",
            "where are you located": "faq-003",
            "what is your address": "faq-003",
            "tell me about ccc": "faq-001",
            "what does ccc do": "faq-001",
            "what do you do": "faq-001",
            "how long have you been doing this": "faq-002",
            "what counties do you cover": "faq-004",
            "where do you work": "faq-004",
            "what is icf": "faq-010",
            "what is your license number": "faq-047",
            "how do i contact you": "faq-028",
            "what do you build": "faq-001",
            "where are you based": "faq-003",
            "what is your location": "faq-003",
            "location": "faq-003",
            "address": "faq-003",
            "whats your address": "faq-003",
            "what is ccc": "faq-001",
            "about ccc": "faq-001",
            "who are you": "faq-001",
            "what is your company": "faq-001",
            "how long have you been in business": "faq-002",
            "how long in business": "faq-002",
            "what is your experience": "faq-002",
            "how much experience do you have": "faq-002",
            "experience": "faq-002",
            "what experience do you have": "faq-002",
            "what counties do you serve": "faq-004",
            "where do you operate": "faq-004",
            "service area": "faq-004",
            "what areas do you cover": "faq-004",
            "icf": "faq-010",
            "what is insulated concrete forms": "faq-010",
            "insulated concrete forms": "faq-010",
            "what is your license": "faq-047",
            "license number": "faq-047",
            "how do i reach you": "faq-028",
            "contact": "faq-028",
            "how can i contact you": "faq-028",
            "what services do you offer": "faq-001",
            "what services does ccc offer": "faq-001",
            "can you tell me about ccc": "faq-001",
            "where is ccc located": "faq-003",
            "where is your office": "faq-003",
            "what s your address": "faq-003",
            "what s your phone number": "faq-028",
            "what s your email": "faq-028",
            "how many years of experience do you have": "faq-002",
            "what counties do you work in": "faq-004",
            "what are your hours": "faq-029",
            "what is your business": "faq-001",
            "do you build homes": "faq-005",
            "what are insulated concrete forms": "faq-010",
            "are you a licensed contractor": "faq-032",
            "can you do bathroom kitchen renovations": "faq-006",
            "what s your license number": "faq-047",
            "do you have bonding capacity": "faq-048",
            "are you a wosb": "faq-046",
            "do you do commercial projects": "faq-007",
            "do you offer custom homes": "faq-005",
            "do you handle renovations and additions": "faq-006",
            "do you serve multiple counties": "faq-004",
            "are you insured": "faq-032",
            "do you have experience in construction": "faq-002",
            "can i contact you by phone or email": "faq-028",
            "where can i find your office": "faq-003",
            "do you provide commercial services": "faq-007",
            "are you bonded": "faq-048"
        }
        if norm in alias_map:
            faq_id = alias_map[norm]
            faq_data = self.agent.faqs.get(faq_id)
            if faq_data and faq_data.get('status') == 'source_verified' and faq_data.get('runtime_eligible') is True:
                return [faq_id]
        return []

    def _direct_company_answer(self, text):
        """Return exact, evidence-backed answers for high-value company intents."""
        normalized = re.sub(r'[^a-z0-9]+', ' ', text.casefold()).strip()
        if re.search(r'\b(?:quote|estimate|discuss my project|how do i get a quote)\b', normalized) and 'per square foot' not in normalized:
            return HUMAN, 'needs_help'
        if re.search(r'\b(?:cost|price|pricing|rate|per square foot|price list)\b', normalized):
            return ("We don't publish a standard cost per square foot, because the price depends on the type of work, the design, and the site conditions. The way to get a real number is to talk through your project with us — call or text (727) 771-5672, email Ben at ben@cccbuild.com, or use the contact form on our Contact page with the project location and type of work, and we can discuss cost estimates from there. One published figure: ICF construction typically runs about 15–20% above conventional construction.", 'answered')
        if re.search(r'\bmiami\b', normalized):
            return ("No — Miami is outside our service area. We're based in Clearwater and serve most of Central Florida, from Gainesville to Venice, with a primary focus on Hillsborough, Pinellas, Pasco, Hernando, and Citrus counties. If your project is near the edge of that area, it's worth a quick call to (727) 771-5672 to confirm.", 'answered')
        return None

    def _respond(self, sid, op, text, kind, now=None, timing=None):
        try:
            answer_started = time.perf_counter()
            direct = self._direct_company_answer(text) if kind != 'blocked' else None
            ids = self._curated_ids(text) if kind != 'blocked' else []
            if direct:
                answer, status = direct
                sources, faq_ids = [], []
            elif ids and 'faq-027' in ids:
                status, answer, sources, faq_ids = 'needs_help', HUMAN, [], []
            elif ids:
                status, answer, sources, faq_ids = self._approved(self.agent.answered(ids))
            elif kind == 'human':
                try:
                    self.agent.fallback(text, 'project_specific_or_team_help')
                except Exception:
                    pass
                status, answer, sources, faq_ids = 'needs_help', HUMAN, [], []
            else:
                status, answer, sources, faq_ids = self._approved(self.agent._answer(text))

            self._record_timing(timing, 'answer_generation', answer_started)
            persistence_started = time.perf_counter()
            completed = self.chats.complete_message(sid, op, answer, sources, faq_ids, now)
            if not completed:
                return ({'error':'Chat state changed; refresh the conversation'},409)

            self.chats.finalize_due(self.mail.make_payload, now)
            snapshot = self.chats.snapshot(sid)
            session_status = snapshot['status'] if snapshot else 'ended'
            self._record_timing(timing, 'persistence_and_snapshot', persistence_started)

            return ({'status':status,'answer':answer,'sources':sources,'faq_ids':faq_ids,'session_status':session_status},200)

        except Exception:
            try:
                self.chats.abort_message(sid,op,now)
                self.chats.finalize_due(self.mail.make_payload,now)
            except Exception:
                pass
            return ({'error':'Chat temporarily unavailable'},503)

    def contact(self, sid, token, body, client, now=None):
        try:
            if not getattr(self.config, 'chat_enabled', False):
                return {'error': 'Our virtual assistant is temporarily unavailable. For immediate assistance, please call (727) 771-5672, email ben@cccbuild.com, or use the public contact form on our website.'}, 404
            validated, reason = validate_contact(body)
            if validated is None:
                return {'error': "We couldn't process your form submission because some required information was missing or invalid. Please review your entries and try again."}, 400
            if self._auth(sid, token, now) is None:
                return {'error': "Your chat session has expired or is no longer available. Please start a new chat or contact us directly by calling (727) 771-5672, emailing ben@cccbuild.com, or using the public contact form."}, 401
            allowed, retry = self.chats.rate(client, 'contact', now)
            if not allowed:
                return {'error': "We've received several messages from you in a short period. To ensure a smooth experience for everyone, please wait a moment before sending another message.", 'retry_after': retry}, 429
            result = self.chats.put_contact(sid, validated, self.mail.make_payload, now)
            if result in ('accepted', 'duplicate'):
                return {'ok': True, 'contact_received': True}, 200
            if result == 'conflict':
                return {'error': "We've already received contact details for this chat. If you need to add anything, please call (727) 771-5672 or email ben@cccbuild.com."}, 409
            if result in ('missing', 'expired'):
                return {'error': "Your chat session has expired or is no longer available. Please start a new chat or contact us directly by calling (727) 771-5672, emailing ben@cccbuild.com, or using the public contact form."}, 401
            return {'error': "Our chat service is temporarily unable to connect. Please call (727) 771-5672, email ben@cccbuild.com, or use the public contact form on our website. We're happy to assist you directly."}, 503
        except Exception:
            return {'error': "Our chat service is temporarily unable to connect. Please call (727) 771-5672, email ben@cccbuild.com, or use the public contact form on our website. We're happy to assist you directly."}, 503

    def end(self, sid, token, now=None):
        try:
            if not getattr(self.config, 'chat_enabled', False):
                return ({'error': 'Our virtual assistant is temporarily unavailable. For immediate assistance, please call (727) 771-5672, email ben@cccbuild.com, or use the public contact form on our website.'}, 404)
            if self._auth(sid, token, now) is None:
                return ({'error': "Your chat session has expired or is no longer available. Please start a new chat or contact us directly by calling (727) 771-5672, emailing ben@cccbuild.com, or using the public contact form."}, 401)
            if not self.chats.request_end(sid, self.mail.make_payload, now):
                return ({'error': "Your chat session has expired or is no longer available. Please start a new chat or contact us directly by calling (727) 771-5672, emailing ben@cccbuild.com, or using the public contact form."}, 401)
            return ({'ok': True, 'status': 'ended'}, 200)
        except Exception:
            return ({'error': "Our chat service is temporarily unable to connect. Please call (727) 771-5672, email ben@cccbuild.com, or use the public contact form on our website. We're happy to assist you directly."}, 503)

    def update_entry(self, entry_id, classification, revision, actor, now=None):
        return self.chats.update_entry(entry_id, classification, revision, actor, now)

    def private_list(self):
        try:
            return self.chats.private_list()
        except Exception:
            return {'chats': [], 'retention_days': 30, 'error': 'Chat temporarily unavailable'}

    def private_detail(self, sid):
        if not isinstance(sid, str) or not re.fullmatch(r'[0-9a-f]{32}', sid):
            return None
        try:
            return self.chats.private_detail(sid)
        except Exception:
            return None

    def start(self):
        if not getattr(self.config, 'chat_enabled', False):
            return
        with self.worker_lock:
            if self.worker is not None and self.worker.is_alive():
                return
            self.stop.clear()
            self.worker = threading.Thread(target=self._work, name='ccc-chat-worker', daemon=True)
            self.worker.start()

    def _work(self):
        while not self.stop.is_set():
            if getattr(self.config, 'chat_enabled', False):
                try:
                    self.chats.prune(now=None)
                except Exception:
                    pass
                try:
                    self.chats.finalize_due(self.mail.make_payload, now=None)
                except Exception:
                    pass
                if getattr(self.config, 'chat_emails_enabled', False) and getattr(self.config, 'resend_key', None):
                    try:
                        self.mail.run_once(now=None)
                    except Exception:
                        pass
            self.stop.wait(60)
