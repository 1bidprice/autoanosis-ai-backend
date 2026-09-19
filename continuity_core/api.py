"""Read-only HTTP surface for Continuity Core v1."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from identity import verify_identity_token
from .adapter import facts_from_autoanosis_context
from .service import build_continuity_summary


continuity_bp = Blueprint("continuity_core", __name__, url_prefix="/continuity/v1")


def _authenticated_user_id() -> tuple[int | None, tuple | None]:
    token = request.headers.get("X-Identity-Token", "").strip()
    if not token:
        body = request.get_json(silent=True) or {}
        token = str(body.get("identity_token") or "").strip()

    if not token:
        return None, (jsonify({"error": "Identity token required"}), 401)

    valid, payload, error = verify_identity_token(token)
    if not valid or not payload:
        return None, (jsonify({"error": "Invalid identity token", "reason": error}), 401)

    user_id = payload.get("uid")
    if not isinstance(user_id, int) or user_id <= 0:
        return None, (jsonify({"error": "Invalid identity token payload"}), 401)

    return user_id, None


@continuity_bp.route("/preview", methods=["POST"])
def continuity_preview():
    """Derive a continuity summary from an existing Autoanosis snapshot.

    This endpoint is intentionally read-only. It writes nothing to the DB and
    exists to validate the Continuity Core contract against today's WP/mobile
    payloads before persistence is introduced.
    """

    user_id, error_response = _authenticated_user_id()
    if error_response:
        return error_response

    data = request.get_json(silent=True) or {}
    context = data.get("wp_context") or data.get("context") or data.get("medical_snapshot")
    if not isinstance(context, dict):
        return jsonify({"error": "context must be an object"}), 400

    required_domains = data.get("required_domains") or []
    if not isinstance(required_domains, list):
        return jsonify({"error": "required_domains must be an array"}), 400

    facts = facts_from_autoanosis_context(context)
    summary = build_continuity_summary(facts, required_domains=required_domains)

    # Do not echo identity token or raw input. Patient id is included only as
    # the authenticated subject id so callers can verify subject isolation.
    return jsonify(
        {
            "subject_user_id": user_id,
            "continuity": summary,
        }
    ), 200
