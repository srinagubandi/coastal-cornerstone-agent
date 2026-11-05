from urllib.parse import urlsplit

def is_chat_path(path):
    return path in ('/chat/session', '/chat/message', '/chat/contact', '/chat/end')

def chat_origin(config, origin):
    if not isinstance(origin, str):
        return False
    if any(ord(c) < 32 or c == '\x7f' for c in origin):
        return False
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        return False
    allowed = {'https://cccbuild-3mhyn4jl.manus.space', 'https://cccbuild.com', 'https://cccbuild-website-production.up.railway.app'}
    if parsed.scheme == 'https' and origin in allowed:
        return True
    if hasattr(config, 'public_origin') and isinstance(config.public_origin, str):
        public_parsed = urlsplit(config.public_origin)
        if public_parsed.scheme == 'http' and public_parsed.hostname in ('127.0.0.1', 'localhost'):
            if public_parsed.port and 1024 <= public_parsed.port <= 65535:
                if parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1'):
                    try:
                        port = parsed.port or (80 if parsed.scheme == 'http' else 443)
                        if 1024 <= port <= 65535:
                            return True
                    except ValueError:
                        pass
    return False

def chat_headers(config, origin):
    if not chat_origin(config, origin):
        return {}
    return {
        'Access-Control-Allow-Origin': origin,
        'Vary': 'Origin',
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Chat-Session'
    }

import re
from urllib.parse import urlsplit

def serve_chat(handler, path, client, method):
    config = handler.service.config
    if not config.chat_enabled:
        return handler.respond(503, 'Service Unavailable')
    
    origin = handler.headers.get('Origin')
    if not chat_origin(config, origin):
        return handler.respond(403, {'error':'Forbidden'})
        
    extras = chat_headers(config, origin) if origin else {}
    
    if method == 'OPTIONS':
        return handler.respond(204, None, extra=extras)
        
    if not is_chat_path(path):
        return handler.respond(404, 'Not Found')
        
    parsed = urlsplit(path)
    parsed = urlsplit(handler.path)
    if parsed.query:
        return handler.respond(400, 'Bad Request')
        
    if method not in ['GET', 'POST']:
        extras['Allow'] = 'GET, POST, OPTIONS'
        return handler.respond(405, 'Method Not Allowed', extra=extras)
        
    if method == 'GET' and parsed.path != '/chat/session':
        extras['Allow'] = 'POST, OPTIONS'
        return handler.respond(405, 'Method Not Allowed', extra=extras)
        
    if method == 'POST' and parsed.path not in ['/chat/session', '/chat/message', '/chat/contact', '/chat/end']:
        return handler.respond(404, 'Not Found')
        
    auth_header = handler.headers.get('Authorization', '')
    session_header = handler.headers.get('X-Chat-Session', '')
    
    if parsed.path != '/chat/session' or method != 'POST':
        if not auth_header.startswith('Bearer '):
            return handler.respond(401, 'Unauthorized', extra=extras)
        token = auth_header[7:]
        if not (20 <= len(token) <= 256) or re.search(r'\s', token):
            return handler.respond(401, 'Unauthorized', extra=extras)
        if not re.fullmatch(r'[0-9a-f]{32}', session_header):
            return handler.respond(401, 'Unauthorized', extra=extras)
        sid = session_header
        
    try:
        if method == 'POST' and parsed.path == '/chat/session':
            body = handler.read_body()
            if body != {}:
                return handler.respond(400, 'Bad Request')
            result = handler.service.chat.create(client)
            return handler.respond(result[1], result[0], extra=extras)
        elif method == 'GET' and parsed.path == '/chat/session':
            result = handler.service.chat.snapshot(sid, token)
            return handler.respond(result[1], result[0], extra=extras)
        elif method == 'POST' and parsed.path == '/chat/message':
            body = handler.read_body()
            result = handler.service.chat.message(sid, token, body, client)
            return handler.respond(result[1], result[0], extra=extras)
        elif method == 'POST' and parsed.path == '/chat/contact':
            body = handler.read_body()
            result = handler.service.chat.contact(sid, token, body, client)
            return handler.respond(result[1], result[0], extra=extras)
        elif method == 'POST' and parsed.path == '/chat/end':
            body = handler.read_body()
            if body != {}:
                return handler.respond(400, 'Bad Request')
            result = handler.service.chat.end(sid, token)
            return handler.respond(result[1], result[0], extra=extras)
    except Exception as e:
        if getattr(e,'status',None) not in {400,411,413,415}:
            raise
        static_errors = {400: 'Bad Request', 411: 'Length Required', 413: 'Payload Too Large', 415: 'Unsupported Media Type'}
        msg = static_errors.get(getattr(e,'status',400), 'Bad Request')
        return handler.respond(getattr(e,'status',400), msg, extra=extras)
