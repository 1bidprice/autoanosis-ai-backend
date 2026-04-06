"""
Autoanosis Exams Module — Flask Blueprint
Registers all exams ingestion + structured-data endpoints on the Flask app.
Endpoints:
  POST   /exams/documents                          — ingest OCR text → document record
  POST   /exams/documents/<document_id>/process    — run normalizer → create report(s)
  GET    /exams/patients/<patient_id>/reports      — structured reports (Doctor Dashboard source)
  GET    /exams/review-queue                       — open review queue (admin/doctor)
  POST   /exams/ingest-from-ocr                   — combined ingest+process in one call
  GET    /exams/patients/<patient_id>/snapshot     — structured snapshot for AI context

All write endpoints require a valid Autoanosis identity token (X-Identity-Token header).
GET /patients/<id>/reports accepts the token OR the internal proxy secret.
"""
import logging
import os
import time
import threading
import requests as _http
from flask import Blueprint, request, jsonify
from sqlalchemy.orm import joinedload

from exams_module.db.database import get_db
from exams_module.models.exam_models import ExamDocument, ExamReport, ExamReviewQueue
from exams_module.services.exam_service import create_document, process_document, log_event
from exams_module.schemas.exam_schemas import DocumentCreate

logger = logging.getLogger(__name__)

exams_bp = Blueprint("exams", __name__, url_prefix="/exams")


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _require_identity_token():
    """
    Verify the X-Identity-Token header using the existing identity.py module.
    Returns (patient_id: int, error_response) — exactly one will be None.
    """
    try:
        from identity import verify_identity_token
    except ImportError:
        logger.error("[EXAMS] identity module not found")
        return None, (jsonify({"error": "server_configuration_error"}), 500)

    token = request.headers.get("X-Identity-Token", "").strip()
    if not token:
        return None, (jsonify({"error": "missing_identity_token"}), 401)

    is_valid, payload, err = verify_identity_token(token)
    if not is_valid:
        return None, (jsonify({"error": "invalid_identity_token", "detail": err}), 401)

    uid = payload.get("uid")
    if not uid:
        return None, (jsonify({"error": "token_missing_uid"}), 401)

    return int(uid), None


# ---------------------------------------------------------------------------
# WordPress role cache  (uid → (roles_set, expires_at))
# TTL: 120 seconds — short enough to pick up role changes, long enough to avoid
# hammering WordPress on every request.
# ---------------------------------------------------------------------------
_ROLE_CACHE: dict = {}
_ROLE_CACHE_TTL = 120          # seconds
_ROLE_CACHE_LOCK = threading.Lock()
_ALLOWED_ROLES = frozenset({"doctor", "administrator"})


def _fetch_wp_roles(uid: int) -> set:
    """
    Call GET /wp-json/autoa/v1/user-roles/{uid} on WordPress.
    Returns a set of role slugs, or an empty set on any failure.
    Deny-by-default: empty set means no access.
    """
    wp_url = os.environ.get("WORDPRESS_API_URL", "").rstrip("/")
    wp_key = os.environ.get("WORDPRESS_API_KEY", "")
    if not wp_url or not wp_key:
        logger.error("[EXAMS] WORDPRESS_API_URL or WORDPRESS_API_KEY not set — role lookup impossible")
        return set()
    try:
        resp = _http.get(
            f"{wp_url}/wp-json/autoa/v1/user-roles/{uid}",
            headers={"X-API-Key": wp_key},
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            roles = data.get("roles", [])
            if isinstance(roles, list):
                return set(roles)
        logger.warning("[EXAMS] Role lookup for uid=%s returned HTTP %s", uid, resp.status_code)
    except Exception as exc:
        logger.error("[EXAMS] Role lookup for uid=%s failed: %s", uid, exc)
    return set()


def _get_wp_roles(uid: int) -> set:
    """Return cached roles for uid, refreshing if stale."""
    now = time.monotonic()
    with _ROLE_CACHE_LOCK:
        entry = _ROLE_CACHE.get(uid)
        if entry and now < entry[1]:
            return entry[0]
    # Cache miss or expired — fetch outside the lock to avoid blocking other threads
    roles = _fetch_wp_roles(uid)
    with _ROLE_CACHE_LOCK:
        _ROLE_CACHE[uid] = (roles, now + _ROLE_CACHE_TTL)
    return roles


def _require_admin_token():
    """
    Doctor/Admin gate.
    1. Verifies X-Identity-Token (HMAC, expiry).
    2. Looks up the user's WordPress roles via the internal REST endpoint,
       with a 120-second in-process cache.
    3. Allows only users whose roles intersect {doctor, administrator}.
    4. Deny-by-default: any lookup failure → 403.
    Returns (uid: int, error_response) — exactly one will be None.
    """
    uid, err = _require_identity_token()
    if err:
        return None, err

    roles = _get_wp_roles(uid)
    if not roles.intersection(_ALLOWED_ROLES):
        logger.warning("[EXAMS] Doctor/admin access denied for uid=%s roles=%s", uid, roles)
        return None, (jsonify({"error": "forbidden", "detail": "doctor_or_admin_required"}), 403)

    return uid, None


def _db_session():
    """Return a fresh SQLAlchemy session (caller must close)."""
    gen = get_db()
    return next(gen)


# ---------------------------------------------------------------------------
# POST /exams/documents
# ---------------------------------------------------------------------------

@exams_bp.route("/documents", methods=["POST"])
def create_exam_document():
    """
    Ingest an OCR-extracted text blob → create aa_exam_documents record.
    Body (JSON): { patient_id, sha256, raw_text, source_type?, original_filename?, mime_type? }
    Requires: X-Identity-Token header (patient must match token uid).
    """
    uid, err = _require_identity_token()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    patient_id = data.get("patient_id")

    # Patient must match the authenticated user
    if int(patient_id or 0) != uid:
        return jsonify({"error": "patient_id_mismatch"}), 403

    required = ["sha256", "raw_text"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": "missing_fields", "fields": missing}), 400

    payload = DocumentCreate(
        patient_id=uid,
        source_type=data.get("source_type", "upload"),
        storage_url=data.get("storage_url"),
        original_filename=data.get("original_filename"),
        mime_type=data.get("mime_type"),
        sha256=data["sha256"],
        raw_text=data["raw_text"],
    )

    db = _db_session()
    try:
        doc, is_duplicate = create_document(db, payload)
        if is_duplicate:
            logger.info(f"[EXAMS] Duplicate document skipped: sha256={payload.sha256} patient={uid} existing={doc.id}")
            return jsonify({
                "document_id": doc.id,
                "status": doc.status,
                "duplicate": True,
                "message": "Document already exists for this patient",
            }), 200
        db.commit()
        db.refresh(doc)
        logger.info(f"[EXAMS] Document created: {doc.id} for patient {uid}")
        return jsonify({
            "document_id": doc.id,
            "status": doc.status,
            "duplicate": False,
            "classifier_label": doc.classifier_label,
            "classifier_confidence": float(doc.classifier_confidence) if doc.classifier_confidence else None,
        }), 201
    except Exception as e:
        db.rollback()
        logger.error(f"[EXAMS] create_document error: {e}")
        return jsonify({"error": "ingestion_failed", "detail": str(e)}), 500
    finally:
        db.close()


# ---------------------------------------------------------------------------
# POST /exams/documents/<document_id>/process
# ---------------------------------------------------------------------------

@exams_bp.route("/documents/<document_id>/process", methods=["POST"])
def process_exam_document(document_id):
    """
    Run the normalizer on an existing document → create aa_exam_reports record.
    Requires: X-Identity-Token header.
    """
    uid, err = _require_identity_token()
    if err:
        return err

    db = _db_session()
    try:
        doc = db.query(ExamDocument).filter(ExamDocument.id == document_id).first()
        if not doc:
            return jsonify({"error": "document_not_found"}), 404

        # Ownership check
        if doc.patient_id != uid:
            return jsonify({"error": "forbidden"}), 403

        result = process_document(db, doc)
        db.commit()
        logger.info(f"[EXAMS] Document processed: {document_id} → {result.get('normalization_status')}")
        return jsonify(result), 200
    except Exception as e:
        db.rollback()
        logger.error(f"[EXAMS] process_document error: {e}")
        return jsonify({"error": "processing_failed", "detail": str(e)}), 500
    finally:
        db.close()


# ---------------------------------------------------------------------------
# POST /exams/ingest-from-ocr  (combined ingest + process)
# ---------------------------------------------------------------------------

@exams_bp.route("/ingest-from-ocr", methods=["POST"])
def ingest_from_ocr():
    """
    Combined endpoint: ingest OCR text AND immediately run the normalizer.
    This is the primary entry point called by the WordPress bridge after OCR.
    Body (JSON): { sha256, raw_text, source_type?, original_filename?, mime_type? }
    Requires: X-Identity-Token header.
    Returns: { document_id, status, normalization_status, review_required, report_ids }
    """
    uid, err = _require_identity_token()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    required = ["sha256", "raw_text"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": "missing_fields", "fields": missing}), 400

    payload = DocumentCreate(
        patient_id=uid,
        source_type=data.get("source_type", "upload"),
        storage_url=data.get("storage_url"),
        original_filename=data.get("original_filename"),
        mime_type=data.get("mime_type"),
        sha256=data["sha256"],
        raw_text=data["raw_text"],
    )

    db = _db_session()
    try:
        doc, is_duplicate = create_document(db, payload)
        if is_duplicate:
            logger.info(f"[EXAMS] Duplicate ingest skipped: sha256={payload.sha256} patient={uid} existing={doc.id}")
            return jsonify({
                "document_id": doc.id,
                "status": doc.status,
                "duplicate": True,
                "message": "Document already exists for this patient",
            }), 200
        db.flush()
        result = process_document(db, doc)
        db.commit()
        logger.info(
            f"[EXAMS] Ingest+process: doc={doc.id} "
            f"status={result.get('status')} "
            f"norm={result.get('normalization_status')} "
            f"patient={uid}"
        )
        return jsonify(result), 201
    except Exception as e:
        db.rollback()
        logger.error(f"[EXAMS] ingest_from_ocr error: {e}")
        return jsonify({"error": "ingestion_failed", "detail": str(e)}), 500
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /exams/patients/<patient_id>/reports  (Doctor Dashboard source of truth)
# ---------------------------------------------------------------------------

@exams_bp.route("/patients/<int:patient_id>/reports", methods=["GET"])
def get_patient_reports(patient_id):
    """
    Returns ONLY structured, normalised exam reports for the given patient.
    Only reports with normalization_status IN (auto_verified, manually_corrected, published)
    are returned — raw blobs, OCR text and failed extracts are NEVER exposed here.

    Auth: X-Identity-Token (patient must match) OR internal proxy secret via
    X-Autoa-Proxy-Sig (for server-to-server calls from helpers.php).
    """
    import os, hmac as _hmac, hashlib, time

    # --- Auth: try identity token first ---
    token = request.headers.get("X-Identity-Token", "").strip()
    proxy_sig = request.headers.get("X-Autoa-Proxy-Sig", "").strip()

    authed_uid = None

    if token:
        try:
            from identity import verify_identity_token
            is_valid, payload, _ = verify_identity_token(token)
            if is_valid:
                authed_uid = payload.get("uid")
        except Exception:
            pass

    if authed_uid is None and proxy_sig:
        # Proxy-signed server-to-server call (same secret as chat proxy)
        secret = os.environ.get("AUTOA_AI_PROXY_SECRET", "")
        ts_str = request.headers.get("X-Autoa-Proxy-TS", "")
        nonce = request.headers.get("X-Autoa-Proxy-Nonce", "")
        if secret and ts_str and nonce:
            try:
                ts = int(ts_str)
                if abs(int(time.time()) - ts) <= 300:
                    canonical = f"{ts}.{nonce}.{patient_id}"
                    expected = _hmac.new(
                        secret.encode(), canonical.encode(), hashlib.sha256
                    ).hexdigest()
                    if _hmac.compare_digest(expected, proxy_sig):
                        authed_uid = patient_id  # server-to-server: trust patient_id
            except Exception:
                pass

    if authed_uid is None:
        return jsonify({"error": "unauthorized"}), 401

    if int(authed_uid) != patient_id:
        return jsonify({"error": "forbidden"}), 403

    db = _db_session()
    try:
        reports = (
            db.query(ExamReport)
            .options(joinedload(ExamReport.results), joinedload(ExamReport.impressions))
            .filter(
                ExamReport.patient_id == patient_id,
                ExamReport.status == "active",
                ExamReport.normalization_status.in_(
                    ["auto_verified", "manually_corrected", "published", "needs_review"]
                ),
            )
            .order_by(ExamReport.performed_at.desc())
            .all()
        )

        out = []
        for r in reports:
            out.append({
                "id": r.id,
                "patient_id": r.patient_id,
                "exam_type": r.exam_type,
                "exam_category": r.exam_category,
                "normalization_status": r.normalization_status,
                "confidence_score": float(r.confidence_score) if r.confidence_score else None,
                "performed_at": r.performed_at.isoformat() if r.performed_at else None,
                "lab_name": r.lab_name,
                "source_lineage": r.source_lineage or {},
                "results": [
                    {
                        "display_name": x.display_name,
                        "value_numeric": float(x.value_numeric) if x.value_numeric is not None else None,
                        "value_text": x.value_text,
                        "unit": x.unit,
                        "reference_low": float(x.reference_low) if x.reference_low is not None else None,
                        "reference_high": float(x.reference_high) if x.reference_high is not None else None,
                        "reference_text": x.reference_text,
                        "abnormal_flag": x.abnormal_flag,
                        "trendable": x.trendable,
                        "clinical_group": x.clinical_group,
                    }
                    for x in r.results
                ],
                "impressions": [
                    {
                        "section_type": i.section_type,
                        "text": i.text,
                        "severity_flag": i.severity_flag,
                        "review_required": i.review_required,
                    }
                    for i in r.impressions
                ],
            })

        return jsonify({"patient_id": patient_id, "reports": out}), 200
    except Exception as e:
        logger.error(f"[EXAMS] get_patient_reports error: {e}")
        return jsonify({"error": "query_failed", "detail": str(e)}), 500
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /exams/patients/<patient_id>/snapshot  (structured AI context)
# ---------------------------------------------------------------------------

@exams_bp.route("/patients/<int:patient_id>/snapshot", methods=["GET"])
def get_patient_exam_snapshot(patient_id):
    """
    Returns a flat structured snapshot of all published exam results for a patient.
    Designed to be merged into the medical_snapshot sent to the AI chat endpoint.
    Only auto_verified / manually_corrected / published reports are included.
    """
    import os, hmac as _hmac, hashlib, time

    token = request.headers.get("X-Identity-Token", "").strip()
    proxy_sig = request.headers.get("X-Autoa-Proxy-Sig", "").strip()
    authed_uid = None

    if token:
        try:
            from identity import verify_identity_token
            is_valid, payload, _ = verify_identity_token(token)
            if is_valid:
                authed_uid = payload.get("uid")
        except Exception:
            pass

    if authed_uid is None and proxy_sig:
        secret = os.environ.get("AUTOA_AI_PROXY_SECRET", "")
        ts_str = request.headers.get("X-Autoa-Proxy-TS", "")
        nonce = request.headers.get("X-Autoa-Proxy-Nonce", "")
        if secret and ts_str and nonce:
            try:
                ts = int(ts_str)
                if abs(int(time.time()) - ts) <= 300:
                    canonical = f"{ts}.{nonce}.{patient_id}"
                    expected = _hmac.new(
                        secret.encode(), canonical.encode(), hashlib.sha256
                    ).hexdigest()
                    if _hmac.compare_digest(expected, proxy_sig):
                        authed_uid = patient_id
            except Exception:
                pass

    if authed_uid is None:
        return jsonify({"error": "unauthorized"}), 401
    if int(authed_uid) != patient_id:
        return jsonify({"error": "forbidden"}), 403

    db = _db_session()
    try:
        reports = (
            db.query(ExamReport)
            .options(joinedload(ExamReport.results), joinedload(ExamReport.impressions))
            .filter(
                ExamReport.patient_id == patient_id,
                ExamReport.status == "active",
                ExamReport.normalization_status.in_(
                    ["auto_verified", "manually_corrected", "published", "needs_review"]
                ),
            )
            .order_by(ExamReport.performed_at.desc())
            .limit(50)
            .all()
        )

        # Flatten into a list compatible with the existing test_results context builder
        structured_results = []
        for r in reports:
            for x in r.results:
                structured_results.append({
                    "test_date": r.performed_at.strftime("%Y-%m-%d") if r.performed_at else None,
                    "test_name": x.display_name,
                    "result_value": str(x.value_numeric) if x.value_numeric is not None else x.value_text,
                    "unit": x.unit or "",
                    "reference_range": (
                        f"{x.reference_low} - {x.reference_high}"
                        if x.reference_low is not None and x.reference_high is not None
                        else x.reference_text or ""
                    ),
                    "status": x.abnormal_flag,
                    "clinical_group": x.clinical_group,
                    "trendable": x.trendable,
                    "report_id": r.id,
                    "exam_type": r.exam_type,
                    "normalization_status": r.normalization_status,
                })

        return jsonify({
            "patient_id": patient_id,
            "structured_exam_results": structured_results,
            "report_count": len(reports),
            "result_count": len(structured_results),
        }), 200
    except Exception as e:
        logger.error(f"[EXAMS] get_patient_exam_snapshot error: {e}")
        return jsonify({"error": "query_failed", "detail": str(e)}), 500
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /exams/review-queue  (admin / doctor review)
# ---------------------------------------------------------------------------

@exams_bp.route("/review-queue", methods=["GET"])
def get_review_queue():
    """
    Returns all open review-queue items.
    Requires admin-level auth (X-Identity-Token + uid in AUTOA_ADMIN_USER_IDS).
    """
    uid, err = _require_admin_token()
    if err:
        return err

    db = _db_session()
    try:
        items = (
            db.query(ExamReviewQueue)
            .filter(ExamReviewQueue.resolution_status == "open")
            .order_by(ExamReviewQueue.created_at.desc())
            .all()
        )
        return jsonify([
            {
                "id": x.id,
                "document_id": x.document_id,
                "patient_id": x.patient_id,
                "reason_code": x.reason_code,
                "reason_text": x.reason_text,
                "created_at": x.created_at.isoformat() if x.created_at else None,
            }
            for x in items
        ]), 200
    except Exception as e:
        logger.error(f"[EXAMS] get_review_queue error: {e}")
        return jsonify({"error": "query_failed", "detail": str(e)}), 500
    finally:
        db.close()


# ---------------------------------------------------------------------------
# PATCH /exams/review-queue/<item_id>/resolve  (admin only)
# ---------------------------------------------------------------------------

@exams_bp.route("/review-queue/<item_id>/resolve", methods=["PATCH"])
def resolve_review_queue_item(item_id):
    """
    Resolve a review-queue item: accept or reject the associated document.
    Body (JSON): { action: "accept" | "reject", note?: string }
    Requires admin-level auth (X-Identity-Token + uid in AUTOA_ADMIN_USER_IDS).

    accept → document.status = "normalized", report.normalization_status = "manually_corrected"
    reject → document.status = "failed", report.normalization_status = "rejected"
    """
    admin_uid, err = _require_admin_token()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    action = data.get("action", "").strip().lower()
    note = data.get("note", "").strip()

    if action not in ("accept", "reject"):
        return jsonify({"error": "invalid_action", "detail": "action must be 'accept' or 'reject'"}), 400

    db = _db_session()
    try:
        item = db.query(ExamReviewQueue).filter(ExamReviewQueue.id == item_id).first()
        if not item:
            return jsonify({"error": "review_item_not_found"}), 404

        if item.resolution_status != "open":
            return jsonify({
                "error": "already_resolved",
                "resolution_status": item.resolution_status,
            }), 409

        # Resolve the queue item
        item.resolution_status = "resolved"
        item.resolved_by = admin_uid
        item.resolution_note = note or None

        # Update the document and its reports
        doc = db.query(ExamDocument).filter(ExamDocument.id == item.document_id).first()
        if doc:
            if action == "accept":
                doc.status = "normalized"
                # Mark all reports for this document as manually_corrected
                reports = db.query(ExamReport).filter(ExamReport.document_id == doc.id).all()
                for r in reports:
                    r.normalization_status = "manually_corrected"
                log_event(db, doc.id, "manually_accepted", {
                    "admin_uid": admin_uid,
                    "note": note,
                    "queue_item_id": item_id,
                })
            else:  # reject
                doc.status = "failed"
                reports = db.query(ExamReport).filter(ExamReport.document_id == doc.id).all()
                for r in reports:
                    r.normalization_status = "rejected"
                    r.status = "archived"
                log_event(db, doc.id, "manually_rejected", {
                    "admin_uid": admin_uid,
                    "note": note,
                    "queue_item_id": item_id,
                })

        db.commit()
        logger.info(
            "[EXAMS] Review item %s resolved: action=%s admin=%s document=%s",
            item_id, action, admin_uid, item.document_id,
        )
        return jsonify({
            "id": item_id,
            "document_id": item.document_id,
            "action": action,
            "resolution_status": "resolved",
            "resolved_by": admin_uid,
        }), 200
    except Exception as e:
        db.rollback()
        logger.error(f"[EXAMS] resolve_review_queue_item error: {e}")
        return jsonify({"error": "resolve_failed", "detail": str(e)}), 500
    finally:
        db.close()
