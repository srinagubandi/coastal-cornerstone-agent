"""Basic data minimization, not a promise of anonymity or complete PII detection."""
import ipaddress
import re
import unicodedata

EMAIL = re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w.-]+\.[A-Za-z]{2,}")
URL = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>]+")
PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{6,}\d)(?!\w)")
TOKEN = re.compile(r"(?i)\b(?:sk-[a-z0-9_-]{8,}|re_[a-z0-9_-]{8,}|bearer\s+\S+|(?:api[_ -]?key|password|secret)\s*[:=]\s*\S+)")
IP_CANDIDATE = re.compile(r"(?<![\w])(?:\[)?[A-Fa-f0-9:.]+(?:\])?(?:%[\w.-]+)?(?![\w])")
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")
UNSUPPORTED = re.compile(r"(?i)\b(?:quotes?|quotations?|prices?|pricing|cost estimate|warrant(?:y|ies)|availability|available (?:today|now)|engineering|structural calculations?|load bearing|customer records?|crm|private (?:data|records)|exploit|hack|ignore (?:all |previous )?instructions|system prompt|execute|book(?:ing)?|schedule (?:a|my)|send (?:an? )?email|credit card|social security)\b")


def redact(text, limit=1500):
    text = unicodedata.normalize("NFKC", str(text))
    text = CONTROL.sub(" ", text)
    text = TOKEN.sub("[credential removed]", text)
    text = URL.sub("[URL removed]", text)
    text = EMAIL.sub("[email removed]", text)

    def hide_ip(match):
        value = match.group().strip("[]").split("%", 1)[0]
        # Do not redact ordinary words/numbers; require actual IPv4/IPv6 parsing.
        try:
            ipaddress.ip_address(value)
            return "[IP removed]"
        except ValueError:
            return match.group()
    text = IP_CANDIDATE.sub(hide_ip, text)
    text = PHONE.sub("[phone removed]", text)
    return " ".join(text.split())[:limit]


def normalize(text):
    return " ".join(re.sub(r"[^\w]+", " ", unicodedata.normalize("NFKC", text).casefold()).split())


def validate_question(body):
    if not isinstance(body, dict) or set(body) != {"question"}:
        raise ValueError("Only the question field is accepted")
    q = body["question"]
    if not isinstance(q, str) or not 2 <= len(q.strip()) <= 1500:
        raise ValueError("question must contain 2 to 1500 characters")
    if any(unicodedata.category(c) == "Cs" for c in q):
        raise ValueError("Invalid Unicode")
    q = redact(q.strip())
    if len(normalize(q)) < 2:
        raise ValueError("question must contain readable text")
    return q


def client_ip(peer, headers, trust_proxy=False):
    # Railway must overwrite/sanitize X-Forwarded-For and prevent direct origin access.
    # Only the rightmost hop is considered, never an attacker-supplied first hop.
    candidate = peer
    if trust_proxy:
        candidate = headers.get("X-Forwarded-For", "").split(",")[-1].strip() or peer
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return str(ipaddress.ip_address(peer))


def csv_safe(value):
    text = str(value)
    dangerous = text.startswith(("\t", "\r", "\n")) or text.lstrip().startswith(("=", "+", "-", "@"))
    return "'" + text if dangerous else text
