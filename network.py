"""No request-supplied URLs, no redirects, no retries, bounded response bodies."""
import json
import time
import urllib.request
from config import EMAIL_URL, MODEL_URL, PRICING_URL


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Transport:
    def __init__(self):
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, url, body=None, headers=None, timeout=60):
        if url not in {EMAIL_URL, MODEL_URL, PRICING_URL}:
            raise ValueError("Outbound endpoint is not approved")
        data = None if body is None else json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers or {}, method="GET" if body is None else "POST")
        deadline = time.monotonic() + timeout
        with self.opener.open(request, timeout=timeout) as response:
            status = response.status
            chunks, length = [], 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Provider deadline exceeded")
                socket = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
                if socket is not None:
                    socket.settimeout(remaining)
                chunk = response.read1(min(65536, 2_000_001 - length))
                if not chunk:
                    break
                length += len(chunk)
                if length > 2_000_000:
                    raise ValueError("Provider response is too large")
                chunks.append(chunk)
            raw = b"".join(chunks)
            result = json.loads(raw.decode("utf-8"))
            if status not in {200, 201} or not isinstance(result, dict):
                raise ValueError("Invalid provider response")
            return result
