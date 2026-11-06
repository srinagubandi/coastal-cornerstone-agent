"""Deployment configuration; request bodies cannot override any of these settings."""
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
MODEL = "deepseek/deepseek-v4-flash"
MODEL_URL = "https://openrouter.ai/api/v1/chat/completions"
PRICING_URL = "https://openrouter.ai/api/v1/models"
EMAIL_URL = "https://api.resend.com/emails"
SENDER = "notifications@propeldock.com"
RECIPIENT = "ben@cccbuild.com"
ADMIN_EMAIL = "sri@srinagubandi.com"
MONTHLY_CAP = 1_000_000  # microUSD, never configurable upwards
MAX_OUTPUT_TOKENS = 8192
BODY_LIMIT = 8192
QUESTION_LIMIT = 1500
ALLOWED_SOURCE_HOSTS = frozenset({"cccbuild.com", "www.cccbuild.com", "cccbuild-3mhyn4jl.manus.space", "cccbuild-website-production.up.railway.app"})


def ceiling(name, default):
    try:
        value = Decimal(os.getenv(name, default))
        if not value.is_finite() or value < 0 or value > Decimal(default):
            raise ValueError("Pricing ceilings may only be lowered")
        return value
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid {name}") from exc


@dataclass(frozen=True)
class Config:
    data_dir: Path = Path(os.getenv("DATA_DIR", str(ROOT / ".private")))
    faq_path: Path = Path(os.getenv("FAQ_PATH", str(ROOT / "data/faq.json")))
    report_path: Path = Path(os.getenv("REPORT_PATH", str(ROOT / "data/report.json")))
    review_queue_path: Path = Path(os.getenv("REVIEW_QUEUE_PATH", str(ROOT / ".private/review-queue.json")))
    public_origin: str = os.getenv("PUBLIC_ORIGIN", "").rstrip("/")
    api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    resend_key: str = os.getenv("RESEND_API_KEY", "")
    admin_hash: str = os.getenv("ADMIN_PASSWORD_HASH", "")
    ben_admin_hash: str = os.getenv("BEN_ADMIN_PASSWORD_HASH", "")
    chat_enabled: bool = os.getenv("CHAT_ENABLED", "false").lower() == "true"
    chat_emails_enabled: bool = os.getenv("CHAT_EMAILS_ENABLED", "false").lower() == "true"
    digest_enabled: bool = os.getenv("DIGEST_ENABLED", "false").lower() == "true"
    trust_proxy: bool = os.getenv("TRUST_PROXY", "false").lower() == "true"
    cookie_secure: bool = os.getenv("COOKIE_SECURE", "true").lower() != "false"
    input_ceiling: Decimal = ceiling("INPUT_PRICE_CEILING", "0.000000091")
    output_ceiling: Decimal = ceiling("OUTPUT_PRICE_CEILING", "0.000000182")
    request_ceiling: Decimal = ceiling("REQUEST_PRICE_CEILING", "0")
    port: int = int(os.getenv("PORT", "3000"))

    def __post_init__(self):
        if os.getenv("OPENROUTER_MODEL", MODEL) != MODEL:
            raise ValueError("The runtime model is pinned and cannot be overridden")
        if os.getenv("DIGEST_FROM", SENDER) != SENDER or os.getenv("DIGEST_TO", RECIPIENT) != RECIPIENT:
            raise ValueError("Digest destinations are fixed; refusing deployment override")
        if self.public_origin:
            u = urlsplit(self.public_origin)
            local = u.hostname in {"localhost", "127.0.0.1", "::1"}
            if u.username or u.password or u.query or u.fragment or u.path or not u.netloc:
                raise ValueError("PUBLIC_ORIGIN must be an origin without a path")
            if u.scheme != "https" and not (u.scheme == "http" and local):
                raise ValueError("PUBLIC_ORIGIN requires HTTPS outside localhost")
            if not self.cookie_secure and not local:
                raise ValueError("Secure cookies cannot be disabled outside localhost")
        elif not self.cookie_secure:
            raise ValueError("Insecure cookies require an explicit localhost PUBLIC_ORIGIN")
