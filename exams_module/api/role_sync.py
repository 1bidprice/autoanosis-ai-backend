"""
Autoanosis Role Sync — POST /internal/role-sync
================================================
WordPress pushes user roles to this endpoint on every login event.
The backend persists them in the dedicated aa_role_cache PostgreSQL table.

Security model:
  - Every request MUST carry an HMAC-SHA256 signature over the raw JSON body.
  - Shared secret: AUTOA_ROLE_SYNC_SECRET env var (same value in WPCode snippet).
  - Signature header:  X-Autoa-Role-Sig  (hex digest)
  - Timestamp header:  X-Autoa-Role-TS   (Unix seconds, integer string)
  - Requests whose timestamp differs from server time by more than
    TIMESTAMP_TOLERANCE_SECONDS (60) are rejected — replay protection.
  - Deny-by-default: missing or invalid signature → 403.

Persistent store (aa_role_cache):
  - uid         BIGINT PRIMARY KEY
  - roles_json  TEXT   (JSON array)
  - synced_at   TIMESTAMP
  - expires_at  TIMESTAMP  (synced_at + AUTOA_ROLE_CACHE_TTL seconds)
  - Survives restarts, redeploys, and multi-instance setups.
  - TTL default: 300 seconds (AUTOA_ROLE_CACHE_TTL env var).

Authorization helper (get_cached_roles):
  - Returns a set of role slugs for a uid.
  - Returns empty set (deny) if: no row, expires_at < NOW(), or DB error.

Endpoint:
  POST /internal/role-sync
  Headers:
    X-Autoa-Role-TS:  <unix_timestamp>
    X-Autoa-Role-Sig: <hmac_sha256_hex>
  Body (JSON):
    { "uid": 42, "roles": ["doctor"], "timestamp": 1712345678 }
  Response 200:
    { "status": "ok", "uid": 42, "roles": ["doctor"], "expires_in": 300 }
  Response 400:
    { "error": "invalid_payload", "detail": "..." }
  Response 403:
    { "error": "forbidden", "detail": "..." }
"""

import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from flask import Blueprint, request, jsonify
from sqlalchemy import text

from exams_module.db.database import get_db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ROLE_CACHE_TTL: int = int(os.environ.get("AUTOA_ROLE_CACHE_TTL", "300"))   # seconds
TIMESTAMP_TOLERANCE: int = 60                                                # seconds

# ---------------------------------------------------------------------------
# HMAC verification
# ---------------------------------------------------------------------------

def _verify_signature(raw_body: bytes, ts_header: str, sig_header: str) -> tuple:
    """
    Verify HMAC-SHA256 signature.
    Message = ts_header_bytes + b"." + raw_body
    Returns (ok: bool, reason: str).
    """
    secret = os.environ.get("AUTOA_ROLE_SYNC_SECRET", "")
    if not secret:
        logger.error("[ROLE_SYNC] AUTOA_ROLE_SYNC_SECRET not configured — all pushes denied")
        return False, "AUTOA_ROLE_SYNC_SECRET not configured"

    if not ts_header or not sig_header:
        return False, "missing_headers"

    # Replay protection
    try:
        ts = int(ts_header)
    except (ValueError, TypeError):
        return False, "invalid_timestamp_format"

    now_wall = int(time.time())
    delta = abs(now_wall - ts)
    if delta > TIMESTAMP_TOLERANCE:
        return False, f"timestamp_out_of_range (delta={delta}s, tolerance={TIMESTAMP_TOLERANCE}s)"

    # Compute expected signature: HMAC-SHA256(secret, ts + "." + body)
    message = ts_header.encode() + b"." + raw_body
    expected = hmac.new(
        secret.encode(),
        message,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, sig_header):
        return False, "signature_mismatch"

    return True, "ok"


# ---------------------------------------------------------------------------
# Persistent role store helpers
# ---------------------------------------------------------------------------

def get_cached_roles(uid: int) -> set:
    """
    Read roles for uid from aa_role_cache.
    Returns an empty set (deny) if:
      - no row exists for uid
      - expires_at < NOW()
      - any DB error
    This is the ONLY function exams_flask.py uses for role lookups.
    """
    try:
        db_gen = get_db()
        db = next(db_gen)
        try:
            row = db.execute(
                text(
                    "SELECT roles_json, expires_at "
                    "FROM aa_role_cache "
                    "WHERE uid = :uid"
                ),
                {"uid": uid},
            ).fetchone()

            if row is None:
                logger.debug("[ROLE_SYNC] uid=%s — no cached roles (never synced)", uid)
                return set()

            roles_json, expires_at = row

            # Normalise expires_at to offset-aware UTC for comparison
            now_utc = datetime.now(timezone.utc)
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

            if now_utc >= expires_at:
                logger.debug("[ROLE_SYNC] uid=%s — cached roles expired at %s", uid, expires_at)
                return set()

            roles = json.loads(roles_json)
            if not isinstance(roles, list):
                logger.warning("[ROLE_SYNC] uid=%s — roles_json is not a list", uid)
                return set()

            return set(roles)

        finally:
            db.close()

    except Exception as exc:
        logger.error("[ROLE_SYNC] DB error reading roles for uid=%s: %s", uid, exc)
        return set()


def _upsert_roles(uid: int, roles: list, ttl: int) -> datetime:
    """
    Upsert roles for uid into aa_role_cache.
    Returns the expires_at datetime (UTC).
    """
    now_utc = datetime.now(timezone.utc)
    expires_at = now_utc + timedelta(seconds=ttl)
    roles_json = json.dumps(roles)

    db_gen = get_db()
    db = next(db_gen)
    try:
        # PostgreSQL UPSERT — also works on SQLite (INSERT OR REPLACE)
        db.execute(
            text(
                """
                INSERT INTO aa_role_cache (uid, roles_json, synced_at, expires_at)
                VALUES (:uid, :roles_json, :synced_at, :expires_at)
                ON CONFLICT (uid) DO UPDATE
                    SET roles_json = EXCLUDED.roles_json,
                        synced_at  = EXCLUDED.synced_at,
                        expires_at = EXCLUDED.expires_at
                """
            ),
            {
                "uid": uid,
                "roles_json": roles_json,
                "synced_at": now_utc,
                "expires_at": expires_at,
            },
        )
        db.commit()
    finally:
        db.close()

    return expires_at


# ---------------------------------------------------------------------------
# Flask Blueprint
# ---------------------------------------------------------------------------

role_sync_bp = Blueprint("role_sync", __name__, url_prefix="/internal")


@role_sync_bp.route("/role-sync", methods=["POST"])
def receive_role_sync():
    """
    POST /internal/role-sync
    Receives a signed role push from WordPress on user login.
    Verifies HMAC-SHA256 signature, persists roles in aa_role_cache.
    """
    raw_body = request.get_data()
    ts_header = request.headers.get("X-Autoa-Role-TS", "")
    sig_header = request.headers.get("X-Autoa-Role-Sig", "")

    ok, reason = _verify_signature(raw_body, ts_header, sig_header)
    if not ok:
        logger.warning("[ROLE_SYNC] Rejected push — %s", reason)
        return jsonify({"error": "forbidden", "detail": reason}), 403

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "invalid_payload", "detail": "empty_or_non_json_body"}), 400

    uid = data.get("uid")
    roles = data.get("roles")
    timestamp = data.get("timestamp")

    # Validate fields
    if not isinstance(uid, int) or uid <= 0:
        return jsonify({"error": "invalid_payload", "detail": "uid must be a positive integer"}), 400
    if not isinstance(roles, list):
        return jsonify({"error": "invalid_payload", "detail": "roles must be an array"}), 400
    if not isinstance(timestamp, int):
        return jsonify({"error": "invalid_payload", "detail": "timestamp must be an integer"}), 400

    # Sanitise roles — only lowercase strings, max 64 chars each
    clean_roles = [
        str(r).lower()[:64]
        for r in roles
        if isinstance(r, str) and r.strip()
    ]

    try:
        expires_at = _upsert_roles(uid, clean_roles, ROLE_CACHE_TTL)
    except Exception as exc:
        logger.error("[ROLE_SYNC] DB error upserting roles for uid=%s: %s", uid, exc)
        return jsonify({"error": "server_error", "detail": "role_store_write_failed"}), 500

    expires_in = int((expires_at - datetime.now(timezone.utc)).total_seconds())

    logger.info(
        "[ROLE_SYNC] Stored roles for uid=%s roles=%s ttl=%ss expires_at=%s",
        uid, clean_roles, expires_in, expires_at.isoformat(),
    )

    return jsonify({
        "status": "ok",
        "uid": uid,
        "roles": clean_roles,
        "expires_in": expires_in,
    }), 200
