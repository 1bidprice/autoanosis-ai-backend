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
import threading
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
# Role gate — backed by the dedicated role_sync push store.
# WordPress pushes roles to POST /internal/role-sync on every login.
# Deny-by-default: empty set (no cached entry, expired, or push never received).
# ---------------------------------------------------------------------------
_ALLOWED_ROLES = frozenset({"doctor", "administrator"})


def _get_wp_roles(uid: int) -> set:
    """Return cached roles for uid from the role_sync push store."""
    from exams_module.api.role_sync import get_cached_roles
    return get_cached_roles(uid)


def _require_admin_token():
    """
    Doctor/Admin gate.
    1. Verifies X-Identity-Token (HMAC, expiry).
    2. Reads roles from the dedicated role_sync push store (WordPress→Render push).
       Deny-by-default: no cached entry, expired cache, or invalid push → 403.
    3. Allows only users whose roles intersect {doctor, administrator}.
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
    Combined endpoint: ingest OCR text AND run the normalizer asynchronously.
    Returns 202 Accepted immediately after document creation so the WordPress
    bridge (30s timeout) never times out. Normalization runs in a background
    thread and updates the document/report records when complete.
    Body (JSON): { sha256, raw_text, source_type?, original_filename?, mime_type? }
    Requires: X-Identity-Token header.
    Returns: { document_id, status, async: true }
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
        doc_id = doc.id
        db.commit()
        logger.info(f"[EXAMS] Document created async: {doc_id} for patient {uid}")
    except Exception as e:
        db.rollback()
        logger.error(f"[EXAMS] ingest_from_ocr create error: {e}")
        return jsonify({"error": "ingestion_failed", "detail": str(e)}), 500
    finally:
        db.close()

    # ── Background normalization ──────────────────────────────────────────────
    def _run_normalization(document_id: int):
        """Run process_document in a background thread with its own DB session."""
        bg_db = _db_session()
        try:
            bg_doc = bg_db.query(ExamDocument).filter(ExamDocument.id == document_id).first()
            if not bg_doc:
                logger.error(f"[EXAMS_BG] Document {document_id} not found in background thread")
                return
            result = process_document(bg_db, bg_doc)
            bg_db.commit()
            logger.info(
                f"[EXAMS_BG] Async process complete: doc={document_id} "
                f"norm={result.get('normalization_status')} "
                f"patient={uid}"
            )
        except Exception as e:
            bg_db.rollback()
            logger.error(f"[EXAMS_BG] Background normalization failed for doc {document_id}: {e}")
        finally:
            bg_db.close()

    t = threading.Thread(target=_run_normalization, args=(doc_id,), daemon=True)
    t.start()

    return jsonify({
        "document_id": doc_id,
        "status": "pending",
        "async": True,
        "message": "Document received. Normalization running in background.",
    }), 202


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

        # Map normalization_status → mobile-facing status field
        _STATUS_MAP = {
            "auto_verified":      "completed",
            "manually_corrected": "completed",
            "published":          "completed",
            "needs_review":       "needs_review",
            "rejected":           "rejected",
        }
        out = []
        for r in reports:
            mobile_status = _STATUS_MAP.get(r.normalization_status or "", "pending")

            # Determine report_category for mobile display logic:
            # "numeric" = has numeric results (lab/urine)
            # "narrative" = imaging/ultrasound/MRI/CT with text findings
            # "mixed" = both numeric results AND narrative text
            has_numeric = len(r.results) > 0
            has_narrative = bool(r.narrative_text or r.findings_json)
            if has_numeric and has_narrative:
                report_category = "mixed"
            elif has_narrative:
                report_category = "narrative"
            else:
                report_category = "numeric"

            # Build human-readable display_name
            _DISPLAY_MAP = {
                "imaging_report": "Απεικονιστική Εξέταση",
                "ultrasound_report": "Υπερηχογράφημα",
                "xray_report": "Ακτινογραφία",
                "mri_report": "MRI / Μαγνητική Τομογραφία",
                "ct_report": "CT / Αξονική Τομογραφία",
                "lab_panel": "Αιματολογικές Εξετάσεις",
                "urine": "Ανάλυση Ούρων",
                "imaging": "Απεικονιστική Εξέταση",
                "cgm_report": "Αναφορά Αισθητήρα Γλυκόζης",
                "unknown": "Ιατρική Αναφορά",
            }
            display_name = r.display_name or _DISPLAY_MAP.get(r.exam_type, r.exam_type)
            out.append({
                "id": r.id,
                "patient_id": r.patient_id,
                "exam_type": r.exam_type,
                "exam_category": r.exam_category,
                "display_name": display_name,
                "report_category": report_category,
                "status": mobile_status,
                "normalization_status": r.normalization_status,
                "result_count": len(r.results),
                "abnormal_count": sum(1 for x in r.results if x.abnormal_flag in ("H", "L", "A", "HH", "LL", "CRITICAL")),
                "confidence_score": float(r.confidence_score) if r.confidence_score else None,
                "performed_at": r.performed_at.isoformat() if r.performed_at else None,
                "lab_name": r.lab_name,
                "ordering_doctor": r.ordering_doctor,
                # ── Narrative / imaging fields ──
                "narrative_text": r.narrative_text,
                "summary": r.summary,
                "findings": r.findings_json or [],
                # ── Edit audit trail ──
                "corrected_fields": r.corrected_fields or {},
                "edited_by": r.edited_by,
                "edited_at": r.edited_at.isoformat() if r.edited_at else None,
                "source_lineage": r.source_lineage or {},
                # ── Numeric results (lab/urine) ──
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
                # ── Raw impressions (for backward compat + doctor dashboard) ──
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

        # Build report_summary: one entry per report, ordered by performed_at DESC.
        # Anchor date is strictly performed_at (never created_at or upload date).
        # This is ADDITIVE — structured_exam_results is preserved unchanged.
        # v4: includes narrative_text, summary, findings for imaging reports.
        _DISPLAY_MAP = {
            "imaging_report": "Απεικονιστική Εξέταση",
            "ultrasound_report": "Υπερηχογράφημα",
            "xray_report": "Ακτινογραφία",
            "mri_report": "MRI / Μαγνητική Τομογραφία",
            "ct_report": "CT / Αξονική Τομογραφία",
            "lab_panel": "Αιματολογικές Εξετάσεις",
            "urine": "Ανάλυση Ούρων",
            "imaging": "Απεικονιστική Εξέταση",
            "cgm_report": "Αναφορά Αισθητήρα Γλυκόζης",
            "unknown": "Ιατρική Αναφορά",
        }

        report_summary = []
        # Also build narrative_exam_context for AI: one entry per narrative/imaging report
        narrative_exam_context = []

        for r in reports:
            abnormal_flags = {"H", "L", "A", "HH", "LL", "CRITICAL"}
            abnormal_count = sum(
                1 for x in r.results
                if x.abnormal_flag and x.abnormal_flag.upper() in abnormal_flags
            )
            display_name = r.display_name or _DISPLAY_MAP.get(r.exam_type, r.exam_type)

            report_summary.append({
                "report_id": r.id,
                "exam_type": r.exam_type or "Εξέταση",
                "display_name": display_name,
                "performed_at": r.performed_at.strftime("%Y-%m-%d") if r.performed_at else None,
                "result_count": len(r.results),
                "abnormal_count": abnormal_count,
                # Include summary for AI context (short version)
                "summary": r.summary or None,
                "has_narrative": bool(r.narrative_text or r.findings_json),
            })

            # For imaging/narrative reports: add full narrative to AI context
            if r.narrative_text or r.findings_json:
                findings_text = ""
                if r.findings_json:
                    findings_parts = []
                    for f in r.findings_json:
                        section = f.get("section", "").title()
                        text = f.get("text", "")
                        if section and text:
                            findings_parts.append(f"{section}: {text}")
                        elif text:
                            findings_parts.append(text)
                    findings_text = "\n".join(findings_parts)

                narrative_exam_context.append({
                    "report_id": r.id,
                    "exam_type": r.exam_type,
                    "display_name": display_name,
                    "performed_at": r.performed_at.strftime("%Y-%m-%d") if r.performed_at else None,
                    "lab_name": r.lab_name,
                    "ordering_doctor": r.ordering_doctor,
                    # Full narrative for AI to read
                    "narrative_text": r.narrative_text or findings_text or None,
                    "summary": r.summary,
                    "findings": r.findings_json or [],
                })

        # Sort by performed_at DESC (None values go last)
        report_summary.sort(
            key=lambda x: x["performed_at"] or "0000-00-00",
            reverse=True
        )
        narrative_exam_context.sort(
            key=lambda x: x["performed_at"] or "0000-00-00",
            reverse=True
        )

        # Fetch medical documents archive for AI context
        medical_docs_list = []
        try:
            from exams_module.models.medical_document_model import MedicalDocument
            docs = (
                db.query(MedicalDocument)
                .filter(MedicalDocument.patient_id == patient_id)
                .order_by(MedicalDocument.uploaded_at.desc())
                .limit(20)
                .all()
            )
            for d in docs:
                medical_docs_list.append({
                    "id": d.id,
                    "document_title": d.document_title or d.original_filename,
                    "document_category": d.document_category or "general",
                    "notes": d.notes or "",
                    "document_date": d.document_date.isoformat() if d.document_date else None,
                    "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
                    "mime_type": d.mime_type or "",
                    "extracted_text": d.extracted_text or "",
                })
        except Exception as _doc_err:
            logger.warning(f"[SNAPSHOT] Could not fetch medical_documents: {_doc_err}")

        return jsonify({
            "patient_id": patient_id,
            "structured_exam_results": structured_results,
            "report_count": len(reports),
            "result_count": len(structured_results),
            "report_summary": report_summary,
            # NEW: narrative/imaging reports for AI context
            "narrative_exam_context": narrative_exam_context,
            "narrative_report_count": len(narrative_exam_context),
            # Medical documents archive
            "medical_documents": medical_docs_list,
            "medical_documents_count": len(medical_docs_list),
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

# ---------------------------------------------------------------------------
# PATCH /exams/patients/<patient_id>/reports/<report_id>/deactivate
# User-facing soft-delete: sets report.status = 'deleted'
# Auth: X-Identity-Token (patient must own the report)
# ---------------------------------------------------------------------------
@exams_bp.route("/patients/<int:patient_id>/reports/<report_id>/deactivate", methods=["PATCH"])
def deactivate_patient_report(patient_id, report_id):
    """
    Soft-delete a single exam report for the authenticated patient.
    Sets report.status = 'deleted' — excluded from all future reports/snapshot queries.
    The underlying document and results are preserved in the database.

    Auth: X-Identity-Token header (uid must match patient_id).
    Returns: { "deactivated": true, "report_id": "...", "patient_id": ... }
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
        report = (
            db.query(ExamReport)
            .filter(
                ExamReport.id == report_id,
                ExamReport.patient_id == patient_id,
            )
            .first()
        )
        if not report:
            return jsonify({"error": "not_found", "report_id": report_id}), 404
        if report.status == "deleted":
            return jsonify({
                "deactivated": True,
                "report_id": report_id,
                "patient_id": patient_id,
                "note": "already_deleted",
            }), 200

        report.status = "deleted"
        # Also mark the underlying document as deleted so the duplicate-check
        # allows the patient to re-upload the same file after deletion.
        if report.document_id:
            doc = db.query(ExamDocument).filter(ExamDocument.id == report.document_id).first()
            if doc:
                doc.status = "deleted"
        db.commit()
        logger.info(
            "[EXAMS] Report soft-deleted: report_id=%s patient_id=%s document_id=%s",
            report_id, patient_id, report.document_id,
        )
        return jsonify({
            "deactivated": True,
            "report_id": report_id,
            "patient_id": patient_id,
        }), 200
    except Exception as e:
        db.rollback()
        logger.error(f"[EXAMS] deactivate_patient_report error: {e}")
        return jsonify({"error": "deactivate_failed", "detail": str(e)}), 500
    finally:
        db.close()


# ---------------------------------------------------------------------------
# PATCH /exams/patients/<patient_id>/reports/<report_id>
# Universal report edit endpoint — user/doctor/admin can correct any field.
# Original OCR/raw archive (ExamDocument.ocr_text) is NEVER modified.
# All corrections are stored in corrected_fields with audit trail.
# Auth: X-Identity-Token (patient must own the report)
# ---------------------------------------------------------------------------

_EDITABLE_FIELDS = {
    "display_name", "exam_type", "exam_category", "performed_at",
    "lab_name", "ordering_doctor", "narrative_text", "summary",
    "findings_json",
}

_NUMERIC_RESULT_EDITABLE = {
    "display_name", "value_numeric", "value_text", "unit",
    "reference_low", "reference_high", "reference_text", "abnormal_flag",
    "clinical_group",
}


@exams_bp.route("/patients/<int:patient_id>/reports/<report_id>", methods=["PATCH"])
def patch_patient_report(patient_id, report_id):
    """
    Edit a report's fields with full audit trail.
    Editable report fields: display_name, exam_type, exam_category, performed_at,
      lab_name, ordering_doctor, narrative_text, summary, findings_json.
    Editable numeric results: pass results[] array with {id, ...fields}.
    All original values are preserved in corrected_fields JSON.

    Body (JSON):
    {
      "display_name": "Υπερηχογράφημα Άνω/Κάτω Κοιλίας",
      "exam_type": "ultrasound_report",
      "performed_at": "2026-05-15",
      "narrative_text": "...",
      "summary": "...",
      "findings_json": [...],
      "results": [
        {"id": "...", "value_numeric": 5.2, "unit": "mg/L", "abnormal_flag": "normal"}
      ]
    }
    """
    import os, hmac as _hmac, hashlib, time
    from datetime import datetime as _dt

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

    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({"error": "empty_body"}), 400

    db = _db_session()
    try:
        from exams_module.models.exam_models import ExamResult as _ExamResult
        report = (
            db.query(ExamReport)
            .options(joinedload(ExamReport.results))
            .filter(
                ExamReport.id == report_id,
                ExamReport.patient_id == patient_id,
                ExamReport.status != "deleted",
            )
            .first()
        )
        if not report:
            return jsonify({"error": "not_found", "report_id": report_id}), 404

        now_iso = _dt.utcnow().isoformat()
        corrected = dict(report.corrected_fields or {})
        changed_fields = []

        # ── Edit report-level fields ──
        for field in _EDITABLE_FIELDS:
            if field not in data:
                continue
            new_val = data[field]
            old_val = getattr(report, field, None)

            # Special handling for performed_at
            if field == "performed_at":
                from exams_module.services.exam_service import _parse_date
                new_val = _parse_date(str(new_val)) if new_val else None
                old_val_str = old_val.isoformat() if old_val else None
                new_val_str = new_val.isoformat() if new_val else None
                if old_val_str != new_val_str:
                    corrected[field] = {
                        "original": old_val_str,
                        "corrected": new_val_str,
                        "edited_at": now_iso,
                        "edited_by": authed_uid,
                    }
                    setattr(report, field, new_val)
                    changed_fields.append(field)
                continue

            # Convert old_val for JSON serialisation
            old_val_s = str(old_val) if old_val is not None else None
            new_val_s = str(new_val) if new_val is not None else None

            if old_val_s != new_val_s:
                corrected[field] = {
                    "original": old_val_s,
                    "corrected": new_val_s,
                    "edited_at": now_iso,
                    "edited_by": authed_uid,
                }
                setattr(report, field, new_val)
                changed_fields.append(field)

        # ── Edit numeric results ──
        results_edits = data.get("results", [])
        for edit in results_edits:
            result_id = edit.get("id")
            if not result_id:
                continue
            result = next((x for x in report.results if x.id == result_id), None)
            if not result:
                continue
            for rf in _NUMERIC_RESULT_EDITABLE:
                if rf not in edit:
                    continue
                old_rv = getattr(result, rf, None)
                new_rv = edit[rf]
                old_rv_s = str(old_rv) if old_rv is not None else None
                new_rv_s = str(new_rv) if new_rv is not None else None
                if old_rv_s != new_rv_s:
                    field_key = f"result_{result_id}_{rf}"
                    corrected[field_key] = {
                        "original": old_rv_s,
                        "corrected": new_rv_s,
                        "edited_at": now_iso,
                        "edited_by": authed_uid,
                    }
                    from decimal import Decimal, InvalidOperation
                    if rf in ("value_numeric", "reference_low", "reference_high"):
                        try:
                            setattr(result, rf, Decimal(str(new_rv)) if new_rv is not None else None)
                        except (InvalidOperation, TypeError):
                            setattr(result, rf, None)
                    else:
                        setattr(result, rf, new_rv)
                    changed_fields.append(field_key)

        if not changed_fields:
            return jsonify({"updated": False, "message": "No changes detected"}), 200

        # Persist audit trail
        report.corrected_fields = corrected
        report.edited_by = authed_uid
        report.edited_at = _dt.utcnow()
        report.updated_at = _dt.utcnow()
        # Promote to manually_corrected so it passes through filters
        if report.normalization_status == "needs_review":
            report.normalization_status = "manually_corrected"

        db.commit()
        logger.info(
            "[EXAMS] Report edited: report_id=%s patient_id=%s fields=%s",
            report_id, patient_id, changed_fields,
        )
        return jsonify({
            "updated": True,
            "report_id": report_id,
            "changed_fields": changed_fields,
            "edited_at": now_iso,
        }), 200

    except Exception as e:
        db.rollback()
        logger.error(f"[EXAMS] patch_patient_report error: {e}")
        return jsonify({"error": "edit_failed", "detail": str(e)}), 500
    finally:
        db.close()
