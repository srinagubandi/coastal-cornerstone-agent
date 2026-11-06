import threading
import time
import re
import json

from chat_store import ChatStore
from chat_mail import ChatMail
from chat_safety import screen_message, validate_contact, NEUTRAL, HUMAN
from agent import valid_source

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


    def create(self, client, now=None):
        try:
            if not getattr(self.config, 'chat_enabled', False):
                return ({'error': 'Chat unavailable'}, 404)
            self.chats.prune(now)
            allowed, retry = self.chats.rate(client, 'create', now)
            if not allowed:
                return ({'error': 'Too many requests', 'retry_after': retry}, 429)
            chat = self.chats.create(client, now)
            if chat is None:
                return ({'error': 'Chat capacity reached'}, 429)
            return (chat, 201)
        except Exception:
            return ({'error': 'Chat temporarily unavailable'}, 503)

    def snapshot(self, sid, token, now=None):
        try:
            if not getattr(self.config, 'chat_enabled', False):
                return ({'error': 'Chat unavailable'}, 404)
            if self._auth(sid, token, now) is None:
                return ({'error': 'Unauthorized'}, 401)
            self.chats.finalize_due(self.mail.make_payload, now)
            public = self.chats.snapshot(sid)
            if not public:
                return {'error': 'Unauthorized'}, 401
            return {
                'session_id': public['session_id'],
                'status': public['status'],
                'messages': public['messages'],
                'contact_received': public['contact_received'],
                'inactivity_seconds': 900
            }, 200
        except Exception:
            return {'error': 'Chat temporarily unavailable'}, 503

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
        try:
            if not getattr(self.config, 'chat_enabled', False):
                return {'error': 'Chat unavailable'}, 404
            kind, text = screen_message(body)
            if kind == 'invalid' or (kind != 'blocked' and not text):
                return {'error': 'Invalid message'}, 400
            raw_text = body['message']
            auth = self._auth(sid, token, now)
            if auth is None:
                return {'error': 'Unauthorized'}, 401
            # Check ignore
            normalized = self.chats._normalize(raw_text)
            if self.chats.is_ignored(normalized):
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
            response, status_code = self._message(sid, token, body, client, now)
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
            return {'error': 'Chat temporarily unavailable'}, 503

    def _message(self, sid, token, body, client, now=None):
        try:
            if not getattr(self.config, 'chat_enabled', False):
                return {'error': 'Chat unavailable'}, 404
            kind, text = screen_message(body)
            if kind == 'invalid' or (kind != 'blocked' and not text):
                return {'error': 'Invalid message'}, 400
            auth = self._auth(sid, token, now)
            if auth is None:
                return {'error': 'Unauthorized'}, 401
            auth_status = auth.get('status', 'active')
            session_status = 'ended' if auth_status in ('ending','ended') else 'active'
            allowed, retry = self.chats.rate(client, 'message', now)
            if not allowed:
                return {'error': 'Rate limit exceeded', 'retry_after': retry}, 429
            greeting_re = re.compile(r'^\s*(hi|hello|thanks|thank\s?you)\s*[!?.]*\s*$', re.IGNORECASE)
            if kind == 'blocked' or greeting_re.match(text):
                return {
                    'status': 'ignored',
                    'answer': NEUTRAL if kind == 'blocked' else 'Hi! How can we help you with Coastal Cornerstone Construction today?',
                    'sources': [],
                    'faq_ids': [],
                    'session_status': session_status,
                }, 200
            self.chats.finalize_due(self.mail.make_payload, now)
            op, reason = self.chats.begin_message(sid, text, now)
            if not op:
                if reason in ('missing', 'expired'):
                    return {'error': 'Session expired or invalid'}, 401
                elif reason == 'ended':
                    return {'error': 'Chat ended; start a new chat'}, 409
                elif reason == 'turn_limit':
                    return {'error': 'Chat message limit reached'}, 409
                elif reason == 'busy':
                    return {'error': 'A message is already processing'}, 409
                else:
                    return {'error': 'Chat temporarily unavailable'}, 503
            return self._respond(sid, op, text, kind, now)
        except Exception:
            return {'error': 'Chat temporarily unavailable'}, 503

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

    def _respond(self, sid, op, text, kind, now=None):
        try:
            ids = self._curated_ids(text) if kind != 'blocked' else []
            if ids and 'faq-027' in ids:
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

            completed = self.chats.complete_message(sid, op, answer, sources, faq_ids, now)
            if not completed:
                return ({'error':'Chat state changed; refresh the conversation'},409)

            self.chats.finalize_due(self.mail.make_payload, now)
            snapshot = self.chats.snapshot(sid)
            session_status = snapshot['status'] if snapshot else 'ended'

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
                return {'error': 'Chat unavailable'}, 404
            validated, reason = validate_contact(body)
            if validated is None:
                return {'error': 'Contact form not accepted'}, 400
            if self._auth(sid, token, now) is None:
                return {'error': 'Unauthorized'}, 401
            allowed, retry = self.chats.rate(client, 'contact', now)
            if not allowed:
                return {'error': 'Rate limit exceeded', 'retry_after': retry}, 429
            result = self.chats.put_contact(sid, validated, self.mail.make_payload, now)
            if result in ('accepted', 'duplicate'):
                return {'ok': True, 'contact_received': True}, 200
            if result == 'conflict':
                return {'error': 'Contact already received'}, 409
            if result in ('missing', 'expired'):
                return {'error': 'Unauthorized'}, 401
            return {'error': 'Chat temporarily unavailable'}, 503
        except Exception:
            return {'error': 'Chat temporarily unavailable'}, 503

    def end(self, sid, token, now=None):
        try:
            if not getattr(self.config, 'chat_enabled', False):
                return ({'error': 'Chat unavailable'}, 404)
            if self._auth(sid, token, now) is None:
                return ({'error': 'Unauthorized'}, 401)
            if not self.chats.request_end(sid, self.mail.make_payload, now):
                return ({'error': 'Unauthorized'}, 401)
            return ({'ok': True, 'status': 'ended'}, 200)
        except Exception:
            return ({'error': 'Chat temporarily unavailable'}, 503)

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
