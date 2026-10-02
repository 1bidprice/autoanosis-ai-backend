"""Autoanosis AI backend environment contract.

The service must know explicitly whether it is running as development, staging,
or production. Staging/production are forbidden from silently falling back to
local SQLite or production origins.
"""

from dataclasses import dataclass
import os
from urllib.parse import urlparse

ALLOWED_ENVS = {"development", "staging", "production"}
PRODUCTION_ORIGINS = {"https://autoanosis.com", "https://www.autoanosis.com"}
REQUIRED_SECRET_KEYS = (
    "OPENAI_API_KEY",
    "AUTOA_AI_PROXY_SECRET",
    "AUTOANOSIS_IDENTITY_SECRET",
    "AUTOA_ROLE_SYNC_SECRET",
    "ADMIN_SECRET",
)


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"[Autoanosis env] Missing required {name}.")
    return value


def _normalize_origin(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise RuntimeError("[Autoanosis env] Every allowed origin must be an absolute HTTPS URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError("[Autoanosis env] Allowed origins must not include credentials/query/fragment.")
    path = parsed.path.rstrip("/")
    if path:
        raise RuntimeError("[Autoanosis env] Allowed origins must be origins only, without a path.")
    return f"{parsed.scheme}://{parsed.netloc}".lower()


@dataclass(frozen=True)
class Settings:
    environment: str
    allowed_origins: tuple[str, ...]
    database_url: str
    admin_secret: str
    proxy_secret: str
    identity_secret: str
    role_sync_secret: str



def load_settings() -> Settings:
    environment = _required("AUTOANOSIS_ENV").lower()
    if environment not in ALLOWED_ENVS:
        raise RuntimeError("[Autoanosis env] AUTOANOSIS_ENV must be development, staging, or production.")

    origins_raw = _required("AUTOANOSIS_ALLOWED_ORIGINS")
    allowed_origins = tuple(
        dict.fromkeys(
            _normalize_origin(part)
            for part in origins_raw.split(",")
            if part.strip()
        )
    )
    if not allowed_origins:
        raise RuntimeError("[Autoanosis env] At least one allowed origin is required.")

    database_url = os.environ.get("DATABASE_URL", "").strip()

    if environment == "production":
        if set(allowed_origins) != PRODUCTION_ORIGINS:
            raise RuntimeError(
                "[Autoanosis env] Production must use exactly the canonical Autoanosis origins."
            )
        if not database_url or database_url.startswith("sqlite"):
            raise RuntimeError("[Autoanosis env] Production requires an explicit non-SQLite DATABASE_URL.")
    elif environment == "staging":
        if set(allowed_origins) & PRODUCTION_ORIGINS:
            raise RuntimeError("[Autoanosis env] Staging must not allow production Autoanosis origins.")
        if not database_url or database_url.startswith("sqlite"):
            raise RuntimeError("[Autoanosis env] Staging requires an isolated non-SQLite DATABASE_URL.")
    else:
        # Local development may use SQLite, but must still be explicit.
        database_url = database_url or "sqlite:///./autoanosis_exams.db"

    # All deployed environments require explicit secrets. Keeping this rule in
    # development too prevents CI/local runs from accidentally exercising admin
    # or identity paths with public defaults.
    for key in REQUIRED_SECRET_KEYS:
        _required(key)

    return Settings(
        environment=environment,
        allowed_origins=allowed_origins,
        database_url=database_url,
        admin_secret=_required("ADMIN_SECRET"),
        proxy_secret=_required("AUTOA_AI_PROXY_SECRET"),
        identity_secret=_required("AUTOANOSIS_IDENTITY_SECRET"),
        role_sync_secret=_required("AUTOA_ROLE_SYNC_SECRET"),
    )


SETTINGS = load_settings()
