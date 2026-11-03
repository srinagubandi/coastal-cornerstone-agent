"""Standard-library HTTP service; Railway supplies public TLS and a /data volume."""
import hmac
import json
import threading
from http import HTTPStatus
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from agent import Agent
from config import BODY_LIMIT, Config, ROOT
from dashboard import Dashboard
from digest import Digest
from store import Store
from safety import client_ip

PUBLIC_ROUTES = {"/health", "/docs", "/docs/", "/openapi.json", "/agent-card.json", "/.well-known/agent-card.json", "/faq", "/ask", "/mcp"}
TOOLS = [
    {"name": "get_faq", "description": "Read source-verified, runtime-eligible curated FAQs. No private review questions.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string", "maxLength": 100}}, "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}},
    {"name": "ask_company_question", "description": "Read-only source-grounded company information; exact curated answers or a review fallback. No actions or commitments.",
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
        self.dashboard = Dashboard(self.config, self.store, self.agent, self.digest)

    def card(self):
        origin = self.config.public_origin
        return {"kind": "company-information", "version": "1.0.0", "name": "Coastal Cornerstone information agent",
                "description": "Read-only source-verified public company information. No private systems, business commitments, booking, messaging, or arbitrary browsing.",
                "url": origin or None, "docs_url": origin + "/docs" if origin else "/docs", "endpoint": origin + "/ask" if origin else "/ask",
                "mcp_endpoint": origin + "/mcp" if origin else "/mcp", "instruction_file": origin + "/docs" if origin else "/docs",
                "integration_url": "https://cccbuild-3mhyn4jl.manus.space/ai/",
                "usage_guide_url": "https://cccbuild-3mhyn4jl.manus.space/ai/agent.md",
                "capabilities": {"read_only": True, "source_verified_faq": True, "mcp_json_rpc_tools": [t["name"] for t in TOOLS]},
                "protocols": {"http_json": True, "mcp": "2025-03-26 tools subset", "full_a2a": False},
                "privacy": "Basic redaction and limited pseudonymity; API/MCP channels do not authenticate a caller's AI identity."}

    def openapi(self):
        answer_schema = {"type": "object", "required": ["status", "answer", "faq_ids", "sources", "review_queued", "knowledge_version", "model_used"],
            "properties": {"status": {"enum": ["answered", "needs_review"]}, "answer": {"type": "string"},
            "faq_ids": {"type": "array", "items": {"type": "string"}}, "sources": {"type": "array", "items": {"type": "string", "format": "uri"}},
            "review_queued": {"type": "boolean"}, "knowledge_version": {"type": "string"}, "model_used": {"type": ["string", "null"]}}}
        faq_schema = {"type": "object", "required": ["version", "business", "faqs"], "properties": {"version": {"type": "string"}, "business": {"type": "string"}, "faqs": {"type": "array", "items": {"type": "object", "required": ["id", "question", "answer", "source_urls", "status", "runtime_eligible"], "properties": {"id": {"type": "string"}, "question": {"type": "string"}, "answer": {"type": "string"}, "source_urls": {"type": "array", "items": {"type": "string", "format": "uri"}}, "tags": {"type": "array", "items": {"type": "string"}}, "status": {"const": "source_verified"}, "runtime_eligible": {"const": True}}}}}}
        errors = {str(code): {"description": HTTPStatus(code).phrase} for code in (400, 411, 413, 415, 429, 503)}
        paths = {"/ask": {"post": {"operationId": "askCompanyQuestion", "summary": "Source-grounded read-only question", "requestBody": {"required": True, "content": {"application/json": {"schema": TOOLS[1]["inputSchema"]}}}, "responses": {"200": {"description": "Curated answer or non-invented fallback", "content": {"application/json": {"schema": answer_schema}}}, **errors}}},
                 "/faq": {"get": {"operationId": "getFaq", "responses": {"200": {"description": "Eligible source-verified snapshot", "content": {"application/json": {"schema": faq_schema}}}, "429": {"description": "Read rate limit"}}}},
                 "/mcp": {"post": {"operationId": "mcpTools", "description": "JSON-RPC 2.0 initialize, notifications/initialized, tools/list, tools/call. MCP 2025-03-26 tools subset; no SSE, full lifecycle, or A2A claim.", "requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object", "required": ["jsonrpc", "method"], "properties": {"jsonrpc": {"const": "2.0"}, "id": {"type": ["integer", "string", "null"]}, "method": {"type": "string"}, "params": {"type": "object"}}, "additionalProperties": False}}}}, "responses": {"200": {"description": "JSON-RPC result or error", "content": {"application/json": {"schema": {"type": "object", "required": ["jsonrpc", "id"], "properties": {"jsonrpc": {"const": "2.0"}, "id": {"type": ["integer", "string", "null"]}, "result": {}, "error": {"type": "object"}}}}}}, "204": {"description": "Notification accepted, no content"}, **errors}}}}
        for path in ("/health", "/agent-card.json", "/.well-known/agent-card.json", "/openapi.json", "/docs"):
            paths[path] = {"get": {"responses": {"200": {"description": "Public configuration/discovery"}, "429": {"description": "Read rate limit"}}}}
        return {"openapi": "3.1.0", "info": {"title": "Coastal Cornerstone public information agent", "version": "1.0.0", "description": "Public read-only FAQ API. Curated source answers only; no business commitments. Private dashboard is intentionally excluded."},
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
            result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "coastal-cornerstone-information", "version": "1.0.0"}, "instructions": "Read-only tools; exact curated FAQs only. No full A2A or arbitrary actions."}
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
        if path in PUBLIC_ROUTES:
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
        return result if result and result["role"] == role else None

    def do_OPTIONS(self):
        if urlsplit(self.path).path in PUBLIC_ROUTES:
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
        if path == "/health":
            return self.respond(200, {"status": "ok", "knowledge_count": len(s.agent.faqs), "model_configured": bool(s.config.api_key), "digest_enabled": s.config.digest_enabled})
        if path in {"/agent-card.json", "/.well-known/agent-card.json"}:
            return self.respond(200, s.card())
        if path == "/openapi.json":
            return self.respond(200, s.openapi())
        if path == "/faq":
            return self.respond(200, s.agent.public_faq())
        if path in {"/", "/docs", "/docs/"}:
            return self.respond(200, (ROOT / "docs/index.html").read_bytes(), "text/html; charset=utf-8")
        assets = {"/static/styles.css": "styles.css", "/static/dashboard.js": "dashboard.js", "/static/login.js": "login.js"}
        if path in assets:
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
                return self.respond(200, {"email": "sri@srinagubandi.com", "role": "admin", "csrf": session["csrf"], "expires": session["expires"]})
            query = parse_qs(split.query, keep_blank_values=True)
            if set(query) - {"days"} or len(query.get("days", ["7"])) != 1 or query.get("days", ["7"])[0] not in {"7", "30"}:
                return self.respond(400, {"error": "days must be 7 or 30; no other query parameters are accepted"})
            days = int(query.get("days", ["7"])[0])
            if path == "/private/api/dashboard/summary":
                return self.respond(200, s.dashboard.summary(days))
            if path == "/private/api/dashboard/export.csv":
                return self.respond(200, s.dashboard.csv_export(days), "text/csv; charset=utf-8", {"Content-Disposition": 'attachment; filename="coastal-questions.csv"'})
            if path == "/private/api/dashboard/export.json":
                return self.respond(200, s.dashboard.summary(days), extra={"Content-Disposition": 'attachment; filename="coastal-questions.json"'})
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
        if path not in {"/ask", "/mcp", "/private/api/dashboard/login", "/private/api/dashboard/logout"}:
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
        try:
            body = self.read_body()
        except BodyError as exc:
            if path == "/ask":
                s.store.log_event("[invalid request body]", "API", "invalid", client, reason="invalid_body")
            if path == "/mcp" and exc.status == 400:
                return self.respond(400, rpc_error(None, -32700, "Parse error"))
            return self.respond(exc.status, {"error": exc.message})
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
            token, csrf = s.store.create_session()
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
    print("Coastal Cornerstone information service starting; digest " + ("enabled" if service.config.digest_enabled else "paused"), flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        service.digest.stop.set()
        server.server_close()
