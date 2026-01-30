"""
Autoanosis Identity Bridge - Token Verification
Verifies HMAC-SHA256 signed identity tokens from WordPress
"""

import base64
import hmac
import hashlib
import json
import os
import time
from typing import Tuple, Dict, Any, Optional


def _b64url_decode(s: str) -> bytes:
    """
    Decode base64url encoded string
    
    Args:
        s: Base64URL encoded string
        
    Returns:
        Decoded bytes
    """
    # Add padding if needed
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s.encode("utf-8"))


def verify_identity_token(
    token: str, 
    max_clock_skew_seconds: int = 60
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """
    Verify WordPress identity token
    
    Token format: <payload_b64>.<sig_b64>
    Payload JSON: { uid, iat, exp, nonce, iss }
    Signature: HMAC-SHA256(payload_b64, secret)
    
    Args:
        token: The identity token to verify
        max_clock_skew_seconds: Maximum allowed clock skew (default: 60s)
        
    Returns:
        Tuple of (is_valid, payload_dict, error_code)
        - is_valid: True if token is valid
        - payload_dict: Decoded payload if valid, None otherwise
        - error_code: Error code string if invalid, None otherwise
    """
    # Get shared secret from environment
    secret = os.environ.get("AUTOANOSIS_IDENTITY_SECRET", "")
    if not secret:
        return False, None, "missing_server_secret"

    # Check token format
    if not token or "." not in token:
        return False, None, "bad_format"

    try:
        payload_b64, sig_b64 = token.split(".", 1)
    except ValueError:
        return False, None, "bad_format"

    # Compute expected signature
    expected_sig = hmac.new(
        secret.encode("utf-8"),
        payload_b64.encode("utf-8"),
        hashlib.sha256
    ).digest()

    # Decode provided signature
    try:
        provided_sig = _b64url_decode(sig_b64)
    except Exception:
        return False, None, "bad_signature_encoding"

    # Verify signature (timing-safe comparison)
    if not hmac.compare_digest(expected_sig, provided_sig):
        return False, None, "signature_mismatch"

    # Decode and parse payload
    try:
        payload_json = _b64url_decode(payload_b64).decode("utf-8")
        payload = json.loads(payload_json)
    except Exception:
        return False, None, "bad_payload"

    # Validate timestamp fields
    now = int(time.time())
    iat = int(payload.get("iat", 0))
    exp = int(payload.get("exp", 0))

    # Check if token is from the future (with clock skew tolerance)
    if iat - max_clock_skew_seconds > now:
        return False, None, "token_from_future"

    # Check if token is expired (with clock skew tolerance)
    if exp + max_clock_skew_seconds < now:
        return False, None, "token_expired"

    # Validate user ID
    uid = payload.get("uid")
    if not isinstance(uid, int) or uid <= 0:
        return False, None, "invalid_uid"

    # Token is valid
    return True, payload, None


def get_user_id_from_token(token: str) -> Optional[int]:
    """
    Extract user ID from verified token
    
    Args:
        token: The identity token
        
    Returns:
        User ID if token is valid, None otherwise
    """
    is_valid, payload, error = verify_identity_token(token)
    if is_valid and payload:
        return payload.get("uid")
    return None
