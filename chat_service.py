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
        try:
            if not isinstance(result, dict) or result.get('status') != 'answered':
                return ('needs_help', HUMAN, [], [])
            faq_ids = result.get('faq_ids')
            if not isinstance(faq_ids, list) or not (1 <= len(faq_ids) <= 3):
                return ('needs_help', HUMAN, [], [])
            if len(set(faq_ids)) != len(faq_ids):
                return ('needs_help', HUMAN, [], [])
            selected_faqs = []
            for fid in faq_ids:
                if not isinstance(fid, str):
                    return ('needs_help', HUMAN, [], [])
                faq = self.agent.faqs.get(fid)
                if not faq:
                    return ('needs_help', HUMAN, [], [])
                if not (faq.get('status') == 'source_verified' and faq.get('runtime_eligible') is True):
                    return ('needs_help', HUMAN, [], [])
                answer = faq.get('answer')
                if not isinstance(answer, str) or not answer:
                    return ('needs_help', HUMAN, [], [])
                source_urls = faq.get('source_urls')
                if not isinstance(source_urls, list) or len(source_urls) == 0:
                    return ('needs_help', HUMAN, [], [])
                valid_urls = []
                for u in source_urls:
                    if not isinstance(u, str) or not u.startswith('https://'):
                        return ('needs_help', HUMAN, [], [])
                    if not valid_source(u):
                        return ('needs_help', HUMAN, [], [])
                    valid_urls.append(u)
                selected_faqs.append((faq, answer, valid_urls))
            answer_parts = [item[1] for item in selected_faqs]
            combined = '\n\n'.join(answer_parts)
            if len(combined) > 12000:
                return ('needs_help', HUMAN, [], [])
            seen = set()
            sources = []
            for item in selected_faqs:
                for url in item[2]:
                    if url not in seen:
                        seen.add(url)
                        sources.append(url)
            ids_copy = list(faq_ids)
            return ('answered', combined, sources, ids_copy)
        except Exception:
            return ('needs_help', HUMAN, [], [])

    def message(self, sid, token, body, client, now=None):
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
            greeting_re = re.compile(r'^\s*(hi|hello|thanks|thank\s?you)\s*[!?.]*\s*$', re.IGNORECASE)
            if kind == 'blocked' or greeting_re.match(text):
                return {
                    'status': 'ignored',
                    'answer': NEUTRAL,
                    'sources': [],
                    'faq_ids': [],
                    'session_status': session_status,
                }, 200
            self.chats.finalize_due(self.mail.make_payload, now)
            allowed, retry = self.chats.rate(client, 'message', now)
            if not allowed:
                return {'error': 'Rate limit exceeded', 'retry_after': retry}, 429
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

    def _respond(self, sid, op, text, kind, now=None):
        try:
            if kind == 'human':
                status = 'needs_help'
                answer = HUMAN
                sources = []
                faq_ids = []
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
