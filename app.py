"""Standard-library HTTP service; Railway supplies public TLS and a /data volume."""
import hmac
import json
import re
from chat_service import ChatService
from chat_http import is_chat_path, serve_chat, chat_headers
import threading
from http import HTTPStatus
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from agent import Agent
from config import BODY_LIMIT, Config, ROOT, ADMIN_EMAIL, RECIPIENT
from dashboard import Dashboard
from digest import Digest
from store import Store
from safety import client_ip
import faq_pages
import os
import admin_faq_http
from faq_review import FAQReview
from notifications import NotificationService
import re

FAQ_ID_RE = re.compile(r'^faq-[0-9]{3}$', re.ASCII)
PUBLIC_ROUTES = {"/health", "/docs", "/docs/", "/openapi.json", "/agent-card.json", "/.well-known/agent-card.json", "/faq", "/ask", "/mcp", "/robots.txt"}
def is_faq_resource(path):
    if not path.startswith('/faq/'):
        return False
    parts = path.split('/')
    if len(parts) != 3:
        return False
    filename = parts[2]
    if filename.endswith('.json'):
        filename = filename[:-5]
    if len(filename) > 100:
        return False
    return bool(FAQ_ID_RE.fullmatch(filename))

TOOLS = [
    {"name": "get_faq", "description": "Read source-verified, runtime-eligible curated business FAQ answers. No private review questions.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string", "maxLength": 100}}, "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}},
    {"name": "ask_company_question", "description": "Read-only source-grounded company information. Exact FAQ matches return verified business facts. General construction queries may return a bounded high-level general explanation explicitly labeled **General construction guidance**, business-topic and output safety checks only. No business commitments, price, schedule, or engineering guarantees. Non-invented fallback review.",
     "inputSchema": {"type": "object", "properties": {"question": {"type": "string", "minLength": 2, "maxLength": 1500}}, "required": ["question"], "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}}
]


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON keys")
        result[key] = value
    return result


def parse_json(raw):
    return json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=strict_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON value")))


def rpc_error(rid, code, message, data=None):
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": rid, "error": error}


class Service:
    def __init__(self, config=None, transport=None):
        self.config = config or Config()
        self.store = Store(self.config.data_dir)
        self.agent = Agent(self.config, self.store, transport)
        self.digest = Digest(self.config, self.store, transport)
        self.notifications = NotificationService(self.config, self.store, transport)
        self.dashboard = Dashboard(self.config, self.store, self.agent, self.digest, self.notifications)
        self.chat = ChatService(self.config, self.store, self.agent, transport)
        self.faq_review = FAQReview(self.store, list(self.agent.public_faq()['faqs']))
        # Seed import
        seed_json = os.environ.get('FAQ_REVIEW_SEED_JSON', '')
        if seed_json:
            try:
                data = json.loads(seed_json)
                if isinstance(data, dict):
                    questions = data.get('questions', [])
                elif isinstance(data, list):
                    questions = data
                else:
                    questions = []
                if questions:
                    self.faq_review.import_questions(questions, actor='system:seed')
            except Exception:
                pass
        elif self.config.review_queue_path.exists():
            try:
                data = json.loads(self.config.review_queue_path.read_text())
                if isinstance(data, dict):
                    questions = data.get('questions', [])
                elif isinstance(data, list):
                    questions = data
                else:
                    questions = []
                if questions:
                    self.faq_review.import_questions(questions, actor='system:seed')
            except Exception:
                pass

    def card(self):
        origin = self.config.public_origin
        return {"kind": "company-information", "version": "1.0.0", "name": "Coastal Cornerstone information agent",
                "description": "Read-only source-verified public company information with bounded general construction guidance. No private systems, business commitments, booking, messaging, or arbitrary browsing.",
                "url": origin or None, "docs_url": origin + "/docs" if origin else "/docs", "endpoint": origin + "/ask" if origin else "/ask",
                "mcp_endpoint": origin + "/mcp" if origin else "/mcp", "instruction_file": origin + "/docs" if origin else "/docs",
                "integration_url": "https://cccbuild-3mhyn4jl.manus.space/ai/",
                "usage_guide_url": "https://cccbuild-3mhyn4jl.manus.space/ai/agent.md",
                "capabilities": {"read_only": True, "source_verified_faq": True, "mcp_json_rpc_tools": [t["name"] for t in TOOLS]},
                "public_faq_resources": {"html_page": "https://cccbuild-3mhyn4jl.manus.space/faq/",
                                         "json_snapshot": origin + "/faq" if origin else "/faq",
                                         "example_faq_html": origin + "/faq/faq-004" if origin else "/faq/faq-004",
                                         "example_faq_json": origin + "/faq/faq-004.json" if origin else "/faq/faq-004.json",
                                         "html_pattern": origin + "/faq/{id}" if origin else "/faq/{id}",
                                         "json_pattern": origin + "/faq/{id}.json" if origin else "/faq/{id}.json"},
                "protocols": {"http_json": True, "mcp": "2025-03-26 tools subset", "full_a2a": False},
                "privacy": "Basic redaction and limited pseudonymity; API/MCP channels do not authenticate a caller's AI identity."}

    def openapi(self):
        answer_schema = {"type": "object", "required": ["status", "answer", "faq_ids", "sources", "review_queued", "knowledge_version", "model_used"],
            "properties": {"status": {"enum": ["answered", "needs_review"]}, "answer": {"type": "string"},
            "faq_ids": {"type": "array", "items": {"type": "string"}}, "sources": {"type": "array", "items": {"type": "string", "format": "uri"}},
            "review_queued": {"type": "boolean"}, "knowledge_version": {"type": "string"}, "model_used": {"type": ["string", "null"]}}}
        faq_schema = {"type": "object", "required": ["version", "business", "faqs"], "properties": {"version": {"type": "string"}, "business": {"type": "string"}, "faqs": {"type": "array", "items": {"type": "object", "required": ["id", "question", "answer", "source_urls", "status", "runtime_eligible"], "properties": {"id": {"type": "string"}, "question": {"type": "string"}, "answer": {"type": "string"}, "source_urls": {"type": "array", "items": {"type": "string", "format": "uri"}}, "tags": {"type": "array", "items": {"type": "string"}}, "status": {"const": "source_verified"}, "runtime_eligible": {"const": True}}}}}}
        faq_item_schema = {"type": "object", "required": ["id", "question", "answer", "source_urls", "status", "runtime_eligible"], "properties": {"id": {"type": "string"}, "question": {"type": "string"}, "answer": {"type": "string"}, "source_urls": {"type": "array", "items": {"type": "string", "format": "uri"}}, "tags": {"type": "array", "items": {"type": "string"}}, "status": {"const": "source_verified"}, "runtime_eligible": {"const": True}}}
        errors = {str(code): {"description": HTTPStatus(code).phrase} for code in (400, 411, 413, 415, 429, 503)}
        paths = {"/ask": {"post": {"operationId": "askCompanyQuestion", "summary": "Source-grounded read-only question (FAQ or General Guidance)", "requestBody": {"required": True, "content": {"application/json": {"schema": TOOLS[1]["inputSchema"]}}}, "responses": {"200": {"description": "Curated business answer, validated general construction guidance, or non-invented fallback", "content": {"application/json": {"schema": answer_schema}}}, **errors}}},
                 "/faq": {"get": {"operationId": "getFaq", "responses": {"200": {"description": "Eligible source-verified business FAQ snapshot", "content": {"application/json": {"schema": faq_schema}}}, "429": {"description": "Read rate limit"}}}},
                 "/mcp": {"post": {"operationId": "mcpTools", "description": "JSON-RPC 2.0 initialize, notifications/initialized, tools/list, tools/call. MCP 2025-03-26 tools subset; no SSE, full lifecycle, or A2A claim.", "requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object", "required": ["jsonrpc", "method"], "properties": {"jsonrpc": {"const": "2.0"}, "id": {"type": ["integer", "string", "null"]}, "method": {"type": "string"}, "params": {"type": "object"}}, "additionalProperties": False}}}}, "responses": {"200": {"description": "JSON-RPC result or error", "content": {"application/json": {"schema": {"type": "object", "required": ["jsonrpc", "id"], "properties": {"jsonrpc": {"const": "2.0"}, "id": {"type": ["integer", "string", "null"]}, "result": {}, "error": {"type": "object"}}}}}}, "204": {"description": "Notification accepted, no content"}, **errors}}}}
        for path in ("/health", "/agent-card.json", "/.well-known/agent-card.json", "/openapi.json", "/docs"):
            paths[path] = {"get": {"responses": {"200": {"description": "Public configuration/discovery"}, "429": {"description": "Read rate limit"}}}}
        paths["/faq/{id}"] = {
            "get": {
                "summary": "Get verified business FAQ HTML page",
                "description": "Returns an HTML page for a specific FAQ record",
                "parameters": [
                    {
                        "name": "id",
                        "in": "path",
                        "required": True,
                        "schema": {
                            "type": "string",
                            "pattern": "^faq-[0-9]{3}$",
                            "maxLength": 100
                        },
                        "description": "FAQ identifier, format: faq-###"
                    }
                ],
                "responses": {
                    "200": {
                        "description": "FAQ HTML page",
                        "content": {"text/html": {}}
                    },
                    "400": {"description": "Bad request"},
                    "404": {"description": "FAQ not found"},
                    "429": {"description": "Too many requests"}
                }
            }
        }
        paths["/faq/{id}.json"] = {
            "get": {
                "summary": "Get verified business FAQ JSON data",
                "description": "Returns JSON with public_faq for a specific FAQ record",
                "parameters": [
                    {
                        "name": "id",
                        "in": "path",
                        "required": True,
                        "schema": {
                            "type": "string",
                            "pattern": "^faq-[0-9]{3}$",
                            "maxLength": 100
                        },
                        "description": "FAQ identifier, format: faq-###"
                    }
                ],
                "responses": {
                    "200": {
                        "description": "FAQ data",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "public_faq": faq_schema["properties"]["faqs"]["items"]
                                    },
                                    "required": ["public_faq"]
                                }
                            }
                        }
                    },
                    "400": {"description": "Bad request"},
                    "404": {"description": "FAQ not found"},
                    "429": {"description": "Too many requests"}
                }
            }
        }
        if "get" not in paths["/mcp"]:
            paths["/mcp"]["get"] = {
                "summary": "MCP GET method not allowed",
                "description": "MCP endpoint only allows POST and OPTIONS; GET returns 405 Method Not Allowed",
                "responses": {
                    "405": {
                        "description": "Method Not Allowed",
                        "headers": {
                            "Allow": {
                                "schema": {
                                    "type": "string",
                                    "example": "POST, OPTIONS"
                                },
                                "description": "Allowed HTTP methods"
                            }
                        }
                    },
                    "429": {"description": "Too many requests"}
                }
            }
        return {"openapi": "3.1.0", "info": {"title": "Coastal Cornerstone public information agent", "version": "1.0.0", "description": "Public read-only FAQ API with bounded general construction guidance. Curated source answers for business facts; validated high-level explanations for general queries. No business commitments, price, schedule, or engineering guarantees."},
                "servers": [{"url": self.config.public_origin or "/"}], "paths": paths}

    def mcp(self, body, client):
        value, status = self._mcp(body, client)
        if (isinstance(body, dict) and body.get("jsonrpc") == "2.0" and isinstance(body.get("method"), str)
                and "id" not in body and not set(body) - {"jsonrpc", "method", "params"}):
            return None, 204
        return value, status

    def _mcp(self, body, client):
        if not isinstance(body, dict):
            return rpc_error(None, -32600, "Invalid Request"), 200
        rid = body.get("id")
        valid_id = rid is None or (isinstance(rid, (str, int)) and not isinstance(rid, bool))
        if not valid_id:
            return rpc_error(None, -32600, "Invalid request ID"), 200
        if body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"), str) or set(body) - {"jsonrpc", "id", "method", "params"}:
            return rpc_error(rid, -32600, "Invalid Request"), 200
        method, params = body["method"], body.get("params", {})
        if not isinstance(params, dict):
            return rpc_error(rid, -32602, "Invalid params"), 200
        notification = "id" not in body
        if method == "notifications/initialized":
            if not notification or params:
                return rpc_error(rid, -32602, "Invalid initialized notification"), 200
            return None, 204
        if method == "initialize":
            if set(params) - {"protocolVersion", "capabilities", "clientInfo"} or any(k in params and not isinstance(params[k], dict) for k in ("capabilities", "clientInfo")) or ("protocolVersion" in params and not isinstance(params["protocolVersion"], str)):
                return rpc_error(rid, -32602, "Invalid initialization params"), 200
            result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "coastal-cornerstone-information", "version": "1.0.0"}, "instructions": "Read-only tools; server-validated exact FAQ evidence or bounded high-level general construction guidance. No full A2A or arbitrary actions."}
        elif method == "tools/list":
            if params:
                return rpc_error(rid, -32602, "Pagination and extra parameters are not supported"), 200
            result = {"tools": TOOLS}
        elif method == "tools/call":
            if set(params) != {"name", "arguments"} or not isinstance(params["name"], str) or not isinstance(params["arguments"], dict):
                self._log_invalid_mcp(params, client)
                return rpc_error(rid, -32602, "Invalid tool params"), 200
            name, args = params["name"], params["arguments"]
            if name == "ask_company_question":
                try:
                    value, status = self.agent.ask(args, client, "MCP")
                except ValueError as exc:
                    return rpc_error(rid, -32602, str(exc)), 200
                if status == 429:
                    return rpc_error(rid, -32029, "Rate limit exceeded", {"retry_after": value["retry_after"]}), 429
            elif name == "get_faq":
                if set(args) - {"id"} or ("id" in args and (not isinstance(args["id"], str) or not 1 <= len(args["id"]) <= 100)):
                    return rpc_error(rid, -32602, "Invalid FAQ arguments"), 200
                value = self.agent.public_faq()
                if "id" in args:
                    faq = self.agent.faqs.get(args["id"])
                    value["faqs"] = [faq] if faq else []
            else:
                self._log_invalid_mcp(params, client)
                return rpc_error(rid, -32602, "Unknown read-only tool"), 200
            result = {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}], "structuredContent": value, "isError": False}
        else:
            return rpc_error(rid, -32601, "Method not found"), 200
        return (None, 204) if notification else ({"jsonrpc": "2.0", "id": rid, "result": result}, 200)

    def _log_invalid_mcp(self, params, client):
        args = params.get("arguments", {}) if isinstance(params, dict) else {}
        q = args.get("question") if isinstance(args, dict) else None
        if isinstance(q, str):
            self.store.log_event(q, "MCP", "invalid", client, reason="invalid_mcp_input")


class Handler(BaseHTTPRequestHandler):
    server_version = "CoastalInformation/1.0"
    sys_version = ""

    @property
    def service(self):
        return self.server.service

    def log_message(self, *args):
        # Standard handler logs raw client IP and request URLs; deliberately disabled.
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def respond(self, status, value=None, content_type="application/json; charset=utf-8", extra=None):
        data = b"" if value is None else value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")
        self.send_header("X-Frame-Options", "DENY")
        if self.service.config.public_origin.startswith("https://"):
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        path = urlsplit(self.path).path
        if is_chat_path(path):
            origin = self.headers.get('Origin')
            extra = {**chat_headers(self.service.config, origin), **(extra or {})}
        if path in PUBLIC_ROUTES or is_faq_resource(path):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        else:
            self.send_header("X-Robots-Tag", "noindex, nofollow, noarchive")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if data:
            self.wfile.write(data)

    def send_error(self, code, message=None, explain=None):
        # Never echo untrusted URLs or parser errors into HTML/logs.
        self.respond(code, {"error": HTTPStatus(code).phrase if code in HTTPStatus._value2member_map_ else "Request rejected"})

    def context(self):
        if sum(len(k) + len(v) for k, v in self.headers.items()) > 16384:
            self.respond(431, {"error": "Headers too large"})
            return None
        ip = client_ip(self.client_address[0], self.headers, self.service.config.trust_proxy)
        return self.service.store.client_hash(ip)

    def limited_read(self, client):
        ok, retry = self.service.store.rate(client, "read")
        if not ok:
            path = urlsplit(self.path).path
            if self.command == "POST" and path in {"/ask", "/mcp"}:
                self.service.store.log_event("[rate-blocked request; body not read]", "API" if path == "/ask" else "MCP",
                                            "rate_blocked", client, reason="transport_read_rate_limit")
            self.respond(429, {"error": "Read rate limit exceeded"}, extra={"Retry-After": str(retry)})
        return ok

    def cookie(self, name):
        try:
            cookies = SimpleCookie()
            cookies.load(self.headers.get("Cookie", ""))
            return cookies[name].value if name in cookies else ""
        except CookieError:
            return ""

    def set_cookie(self, name, token, ttl):
        secure = "; Secure" if self.service.config.cookie_secure else ""
        return f"{name}={token}; Path=/; Max-Age={ttl}; HttpOnly; SameSite=Lax{secure}"

    def session(self, role="admin"):
        if not self.service.dashboard.enabled:
            return None
        name = "ccc_session" if role == "admin" else "ccc_login"
        result = self.service.store.session(self.cookie(name))
        if not result:
            return None
        if (role == "admin" and result["role"] in ("admin", "ben")) or result["role"] == role:
            return result
        return None

    def do_OPTIONS(self):
        if is_chat_path(urlsplit(self.path).path):
            client = self.context()
            if client and self.limited_read(client):
                return serve_chat(self, self.path, client, 'OPTIONS')
            else:
                return None
        if urlsplit(self.path).path in PUBLIC_ROUTES or is_faq_resource(urlsplit(self.path).path):
            self.respond(204)
        else:
            self.respond(403, {"error": "Private endpoints do not support cross-origin access"})

    def do_GET(self):
        try:
            self._get()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except Exception:
            self.respond(503, {"error": "Service temporarily unavailable"})

    def _get(self):
        client = self.context()
        if not client or not self.limited_read(client):
            return
        split = urlsplit(self.path)
        path = split.path
        s = self.service
        if is_chat_path(path):
            return serve_chat(self, path, client, 'GET')
        if path == "/health":
            return self.respond(200, {"status": "ok", "knowledge_count": len(s.agent.faqs), "model_configured": bool(s.config.api_key), "digest_enabled": s.config.digest_enabled})
        if path in {"/agent-card.json", "/.well-known/agent-card.json"}:
            return self.respond(200, s.card())
        if path == "/openapi.json":
            return self.respond(200, s.openapi())
        if path == "/faq":
            return self.respond(200, s.agent.public_faq())
        if path.startswith('/faq/'):
            try:
                if split.query:
                    if path.endswith('.json'):
                        self.respond(400, {'error': 'Query parameters not allowed', 'faq_url': 'https://cccbuild-3mhyn4jl.manus.space/faq/'}, content_type='application/json')
                    else:
                        return self.respond(400, faq_pages.render_faq_error(400, s.config).encode('utf-8'), content_type='text/html; charset=utf-8')
                    return

                filename = path.split('/')[-1]
                is_json = filename.endswith('.json')
                if is_json:
                    filename = filename[:-5]

                if is_faq_resource(path):
                    faq_id = filename
                    faq = s.agent.faqs.get(faq_id)
                    if faq is None:
                        if is_json:
                            self.respond(404, {'error': 'FAQ not found', 'faq_url': 'https://cccbuild-3mhyn4jl.manus.space/faq/'}, content_type='application/json')
                        else:
                            self.respond(404, faq_pages.render_faq_404(None, s.config).encode('utf-8'), content_type='text/html; charset=utf-8')
                        return

                    if is_json:
                        self.respond(200, {'public_faq': faq}, content_type='application/json')
                    else:
                        html = faq_pages.render_faq_html(faq, s.config)
                        self.respond(200, faq_pages.render_faq_html(faq, s.config).encode('utf-8'), content_type='text/html; charset=utf-8')
                else:
                    if is_json:
                        self.respond(404, {'error': 'Invalid FAQ ID format', 'faq_url': 'https://cccbuild-3mhyn4jl.manus.space/faq/'}, content_type='application/json')
                    else:
                        self.respond(404, faq_pages.render_faq_404(None, s.config).encode('utf-8'), content_type='text/html; charset=utf-8')
            except Exception:
                if is_json:
                    self.respond(500, {'error': 'Internal server error'}, content_type='application/json')
                else:
                    self.respond(500, 'Internal server error', content_type='text/plain')
            return
        if path in {"/", "/docs", "/docs/"}:
            return self.respond(200, (ROOT / "docs/index.html").read_bytes(), "text/html; charset=utf-8")
        if path == '/robots.txt':
            return self.respond(200, b'User-agent: *\nDisallow: /\nAllow: /docs\nAllow: /faq\nAllow: /openapi.json\nAllow: /agent-card.json\nAllow: /.well-known/agent-card.json\nAllow: /mcp\nAllow: /ask\nAllow: /health\nAllow: /static/styles.css\nAllow: /robots.txt\n', 'text/plain; charset=utf-8')
        assets = {'/static/styles.css': 'styles.css', '/static/dashboard.js': 'dashboard.js', '/static/login.js': 'login.js', '/static/chat-dashboard.js': 'chat-dashboard.js', '/static/chat-dashboard.css': 'chat-dashboard.css', '/static/faq-review.js': 'faq-review.js', '/static/faq-review.css': 'faq-review.css'}
        if path in assets:
            if path in ('/static/dashboard.js', '/static/chat-dashboard.js', '/static/chat-dashboard.css', '/static/faq-review.js', '/static/faq-review.css') and not self.session():
                return self.respond(401, {'error': 'Authentication required'})
            ctype = "text/css; charset=utf-8" if path.endswith(".css") else "text/javascript; charset=utf-8"
            return self.respond(200, (ROOT / "static" / assets[path]).read_bytes(), ctype)
        if path in {"/dashboard", "/dashboard/", "/dashboard/login"}:
            if not s.dashboard.enabled:
                return self.respond(503, {"error": "Private dashboard is not configured"})
            if path != "/dashboard/login" and not self.session():
                return self.respond(302, extra={"Location": "/dashboard/login"})
            filename = "login.html" if path == "/dashboard/login" else "dashboard.html"
            return self.respond(200, (ROOT / "static" / filename).read_bytes(), "text/html; charset=utf-8")
        if path == "/private/api/dashboard/login-state":
            if not s.dashboard.enabled:
                return self.respond(503, {"error": "Private dashboard is not configured"})
            session = self.session("preauth")
            if session:
                return self.respond(200, {"csrf": session["csrf"]})
            token, csrf = s.store.create_session("preauth")
            return self.respond(200, {"csrf": csrf}, extra={"Set-Cookie": self.set_cookie("ccc_login", token, 600)})
        if path.startswith("/private/"):
            session = self.session()
            if not session:
                return self.respond(401, {"error": "Authentication required"})
            if path == "/private/api/dashboard/session":
                return self.respond(200, {"email": ADMIN_EMAIL if session["role"] == "admin" else RECIPIENT, "role": session["role"], "csrf": session["csrf"], "expires": session["expires"]})
            if path == "/private/api/dashboard/notifications/settings":
                if split.query:
                    return self.respond(400, {'error': 'Query parameters not allowed'})
                return self.respond(200, {'settings': s.dashboard.notification_settings(), 'test_recipient': ADMIN_EMAIL})
            if path == "/private/api/dashboard/notifications/deliveries":
                if split.query:
                    return self.respond(400, {'error': 'Query parameters not allowed'})
                return self.respond(200, {'deliveries': s.dashboard.notification_deliveries()})
            if path == '/private/api/dashboard/chats':
                if split.query:
                    return self.respond(400, {'error': 'Query parameters not allowed'})
                return self.respond(200, s.chat.private_list())
            if path.startswith('/private/api/dashboard/chats/'):
                sid = path[len('/private/api/dashboard/chats/'):]
                split = urlsplit(self.path)
                if split.query:
                    return self.respond(400, {'error': 'Query parameters not allowed'})
                if re.fullmatch(r'[0-9a-f]{32}', sid) is None:
                    return self.respond(404, {'error': 'Not found'})
                result = s.chat.private_detail(sid)
                if isinstance(result, dict):
                    return self.respond(200, result)
                else:
                    return self.respond(404, {'error': 'Not found'})
            if path.startswith('/private/api/dashboard/faq-review/'):
                rem = path[len('/private/api/dashboard/faq-review/'):]
                if not rem.startswith('/'):
                    rem = '/' + rem
                return admin_faq_http.handle_get(self, rem, session)
            query = parse_qs(split.query, keep_blank_values=True)
            if set(query) - {"days"} or len(query.get("days", ["7"])) != 1 or query.get("days", ["7"])[0] not in {"7", "30"}:
                return self.respond(400, {"error": "days must be 7 or 30; no other query parameters are accepted"})
            days = int(query.get("days", ["7"])[0])
            if path == "/private/api/dashboard/summary":
                return self.respond(200, s.dashboard.summary(days))
            if path == "/private/api/dashboard/review-queue":
                if split.query:
                    return self.respond(400, {'error': 'Query parameters not allowed'})
                queue = s.faq_review.review_queue()
                if isinstance(queue, list):
                    return self.respond(200, {'count': len(queue), 'items': queue})
                return self.respond(200, queue)
            if path == "/private/api/dashboard/export.csv":
                return self.respond(200, s.dashboard.csv_export(days), "text/csv; charset=utf-8", {"Content-Disposition": 'attachment; filename="coastal-questions.csv"'})
            if path == "/private/api/dashboard/export.json":
                return self.respond(200, s.dashboard.summary(days), extra={"Content-Disposition": 'attachment; filename="coastal-questions.json"'})
        if path == "/mcp":
            origin = s.config.public_origin
            links = {"html": ("https://cccbuild-3mhyn4jl.manus.space/faq/"),
                     "json": (origin + "/faq" if origin else "/faq"),
                     "example_faq_html": (origin + "/faq/faq-004" if origin else "/faq/faq-004")}
            return self.respond(405, {"error": "Only POST and OPTIONS are supported for MCP", "faq_read_links": links}, extra={"Allow": "POST, OPTIONS"})
        self.respond(404, {"error": "Not found"})

    def read_body(self):
        if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
            raise BodyError(411, "A single Content-Length is required; chunked input is not supported")
        value = self.headers["Content-Length"]
        if not value.isdecimal():
            raise BodyError(400, "Invalid Content-Length")
        length = int(value)
        if length < 1 or length > BODY_LIMIT:
            raise BodyError(413, "JSON body must contain 1 to 8192 bytes")
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise BodyError(415, "Content-Type must be application/json")
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise BodyError(400, "Incomplete request body")
        try:
            return parse_json(raw)
        except (ValueError, UnicodeError, RecursionError):
            raise BodyError(400, "Invalid UTF-8 JSON")

    def do_POST(self):
        try:
            self._post()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except Exception:
            self.respond(503, {"error": "Service temporarily unavailable"})

    def _post(self):
        client = self.context()
        if not client or not self.limited_read(client):
            return
        path = urlsplit(self.path).path
        s = self.service
        if is_chat_path(path):
            return serve_chat(self, path, client, 'POST')
        if path not in {"/ask", "/mcp", "/private/api/dashboard/login", "/private/api/dashboard/logout", "/private/api/dashboard/notifications/update", "/private/api/dashboard/notifications/test"} and not (path.startswith('/private/api/dashboard/chats/') and path.endswith('/review')):
            return self.respond(404, {"error": "Not found"})
        if path.startswith("/private/"):
            if not s.dashboard.enabled:
                return self.respond(503, {"error": "Private dashboard is not configured"})
            is_login = path.endswith("/login")
            if is_login:
                ok, retry = s.store.rate(client, "login")
                if not ok:
                    return self.respond(429, {"error": "Login rate limit exceeded"}, extra={"Retry-After": str(retry)})
            session = self.session("preauth" if is_login else "admin")
            if not s.dashboard.csrf_ok(session, self.headers.get("Origin"), self.headers.get("X-CSRF-Token")):
                return self.respond(403, {"error": "Origin and CSRF validation required"})
            if path.startswith('/private/api/dashboard/faq-review/') and urlsplit(self.path).query:
                return self.respond(400, {'error': 'Query parameters are not allowed'})
        try:
            body = self.read_body()
        except BodyError as exc:
            if path == "/ask":
                s.store.log_event("[invalid request body]", "API", "invalid", client, reason="invalid_body")
            if path == "/mcp" and exc.status == 400:
                return self.respond(400, rpc_error(None, -32700, "Parse error"))
            return self.respond(exc.status, {"error": exc.message})
        if path.startswith('/private/api/dashboard/faq-review/'):
            rem = path[len('/private/api/dashboard/faq-review/'):]
            if not rem.startswith('/'):
                rem = '/' + rem
            return admin_faq_http.handle_post(self, rem, body, session, client)
        if path.startswith('/private/api/dashboard/chats/') and path.endswith('/review'):
            return self.respond(410, {'error': 'This endpoint has been removed. Please use the new FAQ review system.'})
        if path == '/private/api/dashboard/notifications/update':
            if session['role'] not in ('admin', 'ben') or not isinstance(body, dict) or set(body) != {'trigger', 'enabled', 'recipients'}:
                return self.respond(403, {'error': 'Administrator access required'})
            try:
                return self.respond(200, {'settings': s.dashboard.update_notification(body['trigger'], body['enabled'], body['recipients'], session['role'])})
            except (ValueError, TypeError):
                return self.respond(400, {'error': 'Invalid notification setting'})
        if path == '/private/api/dashboard/notifications/test':
            if session['role'] not in ('admin', 'ben') or body != {}:
                return self.respond(403, {'error': 'Administrator access required'})
            result = s.dashboard.send_notification_test(session.get('token', self.cookie('ccc_session') or ''), session['role'])
            if result.get('status') == 'rate_limited':
                return self.respond(429, {'error': 'Test email rate limit reached'})
            return self.respond(200, result)
        if path == "/ask":
            try:
                value, status = s.agent.ask(body, client, "API")
            except ValueError as exc:
                return self.respond(400, {"error": str(exc)})
            return self.respond(status, value, extra={"Retry-After": str(value["retry_after"])} if status == 429 else None)
        if path == "/mcp":
            value, status = s.mcp(body, client)
            retry = value.get("error", {}).get("data", {}).get("retry_after") if isinstance(value, dict) else None
            return self.respond(status, value, extra={"Retry-After": str(retry)} if retry else None)
        if path.endswith("/login"):
            if not isinstance(body, dict) or set(body) != {"email", "password"}:
                return self.respond(400, {"error": "Only email and password are accepted"})
            if not s.dashboard.verify_login(body["email"], body["password"]):
                return self.respond(401, {"error": "Invalid credentials"})
            s.store.revoke_session(self.cookie("ccc_login"))
            role = "admin" if body["email"] == ADMIN_EMAIL else "ben"
            token, csrf = s.store.create_session(role)
            return self.respond(200, {"ok": True, "csrf": csrf}, extra={"Set-Cookie": self.set_cookie("ccc_session", token, 8 * 3600)})
        if body != {}:
            return self.respond(400, {"error": "Logout requires an empty JSON object"})
        s.store.revoke_session(self.cookie("ccc_session"))
        self.respond(200, {"ok": True}, extra={"Set-Cookie": self.set_cookie("ccc_session", "", 0)})


class BodyError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, service):
        self.service = service
        self.slots = threading.BoundedSemaphore(64)
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        pass


if __name__ == "__main__":
    service = Service()
    server = Server(("0.0.0.0", service.config.port), service)
    service.digest.start()
    service.chat.start()
    print("Coastal Cornerstone information service starting; digest " + ("enabled" if service.config.digest_enabled else "paused"), flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        service.digest.stop.set()
        service.chat.stop.set()
        server.server_close()
