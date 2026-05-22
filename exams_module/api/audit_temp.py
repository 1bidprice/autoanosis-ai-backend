"""
Admin audit and management endpoints for the Autoanosis Exams subsystem.
Auth: X-Admin-Secret header must match AUTOA_AI_PROXY_SECRET env var.
"""
import os
import logging
from flask import Blueprint, request, jsonify
from sqlalchemy.orm import joinedload
from exams_module.db.database import get_db
from exams_module.models.exam_models import ExamDocument, ExamReport, ExamResult, ExamReviewQueue

logger = logging.getLogger(__name__)
audit_bp = Blueprint("audit", __name__, url_prefix="/exams/admin")


def _require_admin():
    secret = os.environ.get("AUTOA_AI_PROXY_SECRET", "")
    provided = request.headers.get("X-Admin-Secret", "").strip()
    return bool(secret and provided and secret == provided)


@audit_bp.route("/audit-patient/<int:patient_id>", methods=["GET"])
def audit_patient(patient_id):
    if not _require_admin():
        return jsonify({"error": "unauthorized"}), 401
    gen = get_db()
    db = next(gen)
    try:
        # 1. All documents for this patient
        docs = db.query(ExamDocument).filter(
            ExamDocument.patient_id == patient_id
        ).order_by(ExamDocument.uploaded_at.desc()).all()

        docs_out = []
        for d in docs:
            docs_out.append({
                "id": d.id,
                "patient_id": d.patient_id,
                "source_type": d.source_type,
                "sha256": d.sha256[:16] + "..." if d.sha256 else None,
                "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
                "status": d.status,
                "classifier_label": d.classifier_label,
                "is_duplicate": d.is_duplicate,
                "original_filename": d.original_filename,
                "ocr_preview": (d.ocr_text or "")[:200],
                "review_reason": d.review_reason,
            })

        # 2. All reports for this patient
        reports = db.query(ExamReport).options(
            joinedload(ExamReport.results)
        ).filter(
            ExamReport.patient_id == patient_id
        ).order_by(ExamReport.created_at.desc()).all()

        reports_out = []
        for r in reports:
            reports_out.append({
                "id": r.id,
                "document_id": r.document_id,
                "exam_type": r.exam_type,
                "exam_category": r.exam_category,
                "performed_at": r.performed_at.isoformat() if r.performed_at else None,
                "normalization_status": r.normalization_status,
                "confidence_score": float(r.confidence_score) if r.confidence_score else None,
                "status": r.status,
                "parser_version": r.parser_version,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "lab_name": r.lab_name,
                "results_count": len(r.results),
                "result_names": [x.display_name for x in r.results[:10]],
            })

        # 3. Review queue
        reviews = db.query(ExamReviewQueue).filter(
            ExamReviewQueue.patient_id == patient_id
        ).all()
        reviews_out = [{
            "id": q.id,
            "document_id": q.document_id,
            "reason_code": q.reason_code,
            "reason_text": q.reason_text,
            "resolution_status": q.resolution_status,
        } for q in reviews]

        return jsonify({
            "patient_id": patient_id,
            "documents_count": len(docs_out),
            "documents": docs_out,
            "reports_count": len(reports_out),
            "reports": reports_out,
            "review_queue_count": len(reviews_out),
            "review_queue": reviews_out,
        }), 200
    except Exception as e:
        logger.error(f"[AUDIT] Error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@audit_bp.route("/audit-all", methods=["GET"])
def audit_all():
    if not _require_admin():
        return jsonify({"error": "unauthorized"}), 401
    gen = get_db()
    db = next(gen)
    try:
        doc_count = db.query(ExamDocument).count()
        report_count = db.query(ExamReport).count()
        result_count = db.query(ExamResult).count()

        # Get all unique patients
        from sqlalchemy import distinct
        patients = db.query(distinct(ExamDocument.patient_id)).all()
        patient_ids = [p[0] for p in patients]

        # Per-patient summary
        summaries = []
        for pid in patient_ids:
            d_count = db.query(ExamDocument).filter(ExamDocument.patient_id == pid).count()
            r_count = db.query(ExamReport).filter(ExamReport.patient_id == pid).count()
            summaries.append({"patient_id": pid, "documents": d_count, "reports": r_count})

        return jsonify({
            "total_documents": doc_count,
            "total_reports": report_count,
            "total_results": result_count,
            "patients": summaries,
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@audit_bp.route("/delete-document/<document_id>", methods=["DELETE"])
def delete_document(document_id):
    """
    Permanently delete a document and all its associated reports, results,
    and review queue entries. Admin-only. Irreversible.

    Body (JSON): { "confirm": true }  — required safety check
    """
    if not _require_admin():
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    if not body.get("confirm"):
        return jsonify({"error": "missing_confirm", "message": "Send { \"confirm\": true } to confirm deletion"}), 400

    gen = get_db()
    db = next(gen)
    try:
        doc = db.query(ExamDocument).filter(ExamDocument.id == document_id).first()
        if not doc:
            return jsonify({"error": "not_found", "document_id": document_id}), 404

        patient_id = doc.patient_id

        # 1. Delete all ExamResults for all reports of this document
        reports = db.query(ExamReport).filter(ExamReport.document_id == document_id).all()
        report_ids = [r.id for r in reports]
        results_deleted = 0
        for rid in report_ids:
            n = db.query(ExamResult).filter(ExamResult.report_id == rid).delete(synchronize_session=False)
            results_deleted += n

        # 2. Delete all ExamReports for this document
        reports_deleted = db.query(ExamReport).filter(ExamReport.document_id == document_id).delete(synchronize_session=False)

        # 3. Delete ExamReviewQueue entries for this document
        queue_deleted = db.query(ExamReviewQueue).filter(ExamReviewQueue.document_id == document_id).delete(synchronize_session=False)

        # 4. Delete the document itself
        db.delete(doc)
        db.commit()

        logger.warning(
            f"[AUDIT] DELETED document={document_id} patient={patient_id} "
            f"reports={reports_deleted} results={results_deleted} queue={queue_deleted}"
        )

        return jsonify({
            "deleted": True,
            "document_id": document_id,
            "patient_id": patient_id,
            "reports_deleted": reports_deleted,
            "results_deleted": results_deleted,
            "queue_entries_deleted": queue_deleted,
        }), 200

    except Exception as e:
        db.rollback()
        logger.error(f"[AUDIT] Delete error for document {document_id}: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@audit_bp.route("/resolve-review/<review_id>", methods=["POST"])
def resolve_review(review_id):
    """
    Mark a review queue entry as resolved (accepted or rejected).
    Body (JSON): { "resolution": "accepted" | "rejected", "note": "optional" }
    """
    if not _require_admin():
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    resolution = body.get("resolution")
    if resolution not in ("accepted", "rejected"):
        return jsonify({"error": "invalid_resolution", "allowed": ["accepted", "rejected"]}), 400

    gen = get_db()
    db = next(gen)
    try:
        item = db.query(ExamReviewQueue).filter(ExamReviewQueue.id == review_id).first()
        if not item:
            return jsonify({"error": "not_found", "review_id": review_id}), 404

        item.resolution_status = resolution
        if body.get("note"):
            item.reason_text = (item.reason_text or "") + f" | Admin note: {body['note']}"

        # If accepted, mark the associated report as manually_corrected
        if resolution == "accepted":
            reports = db.query(ExamReport).filter(ExamReport.document_id == item.document_id).all()
            for r in reports:
                if r.normalization_status in ("needs_review", "low_confidence"):
                    r.normalization_status = "manually_corrected"

        db.commit()
        logger.info(f"[AUDIT] Review {review_id} resolved as {resolution}")
        return jsonify({"resolved": True, "review_id": review_id, "resolution": resolution}), 200

    except Exception as e:
        db.rollback()
        logger.error(f"[AUDIT] Resolve error for review {review_id}: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /exams/admin/db-state
# Read-only snapshot: last 20 documents + reports across all patients.
# Auth: X-Admin-Secret header.
# ---------------------------------------------------------------------------
@audit_bp.route("/db-state", methods=["GET"])
def db_state():
    """
    Returns the last 20 documents and last 20 reports (all patients).
    Also counts orphan documents (documents with no associated report).
    Used to diagnose empty-list issues without needing DB shell access.
    """
    if not _require_admin():
        return jsonify({"error": "unauthorized"}), 401

    gen = get_db()
    db = next(gen)
    try:
        from sqlalchemy import not_, exists

        docs = db.query(ExamDocument).order_by(ExamDocument.uploaded_at.desc()).limit(20).all()
        reports = db.query(ExamReport).order_by(ExamReport.created_at.desc()).limit(20).all()

        docs_out = [
            {
                "id": d.id,
                "patient_id": d.patient_id,
                "status": d.status,
                "sha256_prefix": (d.sha256 or "")[:12],
                "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
                "source_type": d.source_type,
            }
            for d in docs
        ]
        reports_out = [
            {
                "id": r.id,
                "patient_id": r.patient_id,
                "document_id": r.document_id,
                "exam_type": r.exam_type,
                "normalization_status": r.normalization_status,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in reports
        ]

        orphan_count = db.query(ExamDocument).filter(
            ~exists().where(ExamReport.document_id == ExamDocument.id)
        ).count()

        return jsonify({
            "last_20_documents": docs_out,
            "last_20_reports": reports_out,
            "orphan_documents_count": orphan_count,
        }), 200

    except Exception as e:
        logger.error("[DB-STATE] Error: %s", e)
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ---------------------------------------------------------------------------
# POST /exams/admin/reprocess-failed
# Re-runs normalization for documents stuck in "uploaded" / "needs_review"
# that have NO associated ExamReport — recovers uploads that failed during
# a broken migration window (e.g. missing columns crash in background thread).
# Auth: X-Admin-Secret header.
# ---------------------------------------------------------------------------
@audit_bp.route("/reprocess-failed", methods=["POST"])
def reprocess_failed():
    """
    Finds orphan documents (no ExamReport) and re-runs process_document().
    Optional body: { "patient_id": 123 }  — limit to one patient.
    """
    if not _require_admin():
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    target_patient = body.get("patient_id")

    gen = get_db()
    db = next(gen)
    try:
        from exams_module.services.exam_service import process_document
        from sqlalchemy import not_, exists

        q = db.query(ExamDocument).filter(
            ExamDocument.status.in_(["uploaded", "needs_review", "normalized"]),
            ~exists().where(ExamReport.document_id == ExamDocument.id),
        )
        if target_patient:
            q = q.filter(ExamDocument.patient_id == int(target_patient))

        orphan_docs = q.order_by(ExamDocument.uploaded_at.desc()).all()

        results = []
        for doc in orphan_docs:
            try:
                result = process_document(db, doc)
                db.commit()
                results.append({
                    "document_id": doc.id,
                    "patient_id": doc.patient_id,
                    "normalization_status": result.get("normalization_status"),
                    "report_ids": result.get("report_ids", []),
                    "results_count": result.get("results_count", 0),
                    "success": True,
                })
                logger.info(
                    "[REPROCESS] doc=%s patient=%s → %s",
                    doc.id, doc.patient_id, result.get("normalization_status"),
                )
            except Exception as doc_err:
                db.rollback()
                logger.error("[REPROCESS] doc=%s failed: %s", doc.id, doc_err)
                results.append({
                    "document_id": doc.id,
                    "patient_id": doc.patient_id,
                    "success": False,
                    "error": str(doc_err),
                })

        return jsonify({
            "reprocessed": len(results),
            "results": results,
        }), 200

    except Exception as e:
        db.rollback()
        logger.error("[REPROCESS] Fatal error: %s", e)
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ---------------------------------------------------------------------------
# POST /exams/admin/reclean-cgm
# For existing CGM reports that already have artifact rows (AGP labels, axis
# labels, etc.), delete those dirty ExamResult rows and re-run normalization
# so only clean clinical metrics remain.
# Auth: X-Admin-Secret header.
# ---------------------------------------------------------------------------
@audit_bp.route("/reclean-cgm", methods=["POST"])
def reclean_cgm():
    """
    Finds all CGM reports (exam_type='cgm_report') that have artifact result
    rows, deletes ALL their ExamResult rows, then re-runs process_document()
    to repopulate with clean results using the updated CGM artifact filter.
    Optional body: { "patient_id": 123 }
    """
    if not _require_admin():
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    target_patient = body.get("patient_id")

    gen = get_db()
    db = next(gen)
    try:
        from exams_module.services.exam_service import process_document

        # Artifact display_name fragments to detect dirty reports
        _artifact_fragments = [
            "agp", "\u03b4\u03b9\u03b1\u03ba\u03cd\u03bc\u03b1\u03bd\u03c3\u03b7\u03c2", "\u03b4\u03b9\u03b1\u03ba\u03c5\u03bc\u03b1\u03bd\u03c3\u03b7\u03c2",
            "\u03ba\u03b1\u03bc\u03c0\u03cd\u03bb\u03b5\u03c2 \u03b3\u03bb\u03c5\u03ba\u03cc\u03b6\u03b7\u03c2", "\u03ba\u03b1\u03bc\u03c0\u03c5\u03bb\u03b5\u03c2 \u03b3\u03bb\u03c5\u03ba\u03bf\u03b6\u03b7\u03c2",
            "\u03b4\u03b9\u03ac\u03bc\u03b5\u03c3\u03bf\u03c2", "\u03b4\u03b9\u03b1\u03bc\u03b5\u03c3\u03bf\u03c2",
            "\u03b4\u03b9\u03ac\u03c3\u03c4\u03b7\u03bc\u03b1", "\u03b4\u03b9\u03b1\u03c3\u03c4\u03b7\u03bc\u03b1",
            "\u03c0\u03bf\u03bb\u03cd\u03b7\u03bc\u03b5\u03c1\u03b5\u03c2", "\u03c0\u03bf\u03bb\u03c5\u03b7\u03bc\u03b5\u03c1\u03b5\u03c2",
            "\u03c4\u03ac\u03c3\u03b5\u03b9\u03c2", "\u03c4\u03b1\u03c3\u03b5\u03b9\u03c2",
            "interquartile", "interdecile",
        ]

        q = db.query(ExamReport).filter(ExamReport.exam_type == "cgm_report")
        if target_patient:
            q = q.filter(ExamReport.patient_id == int(target_patient))
        cgm_reports = q.all()

        cleaned = []
        for report in cgm_reports:
            # Check if this report has any artifact rows
            existing_results = db.query(ExamResult).filter(
                ExamResult.report_id == report.id
            ).all()
            has_artifacts = any(
                any(frag in (r.display_name or "").lower() for frag in _artifact_fragments)
                for r in existing_results
            )
            if not has_artifacts:
                continue  # already clean

            doc_id = report.document_id
            patient_id = report.patient_id
            report_id = report.id

            # Delete all ExamResult rows for this report
            deleted = db.query(ExamResult).filter(
                ExamResult.report_id == report.id
            ).delete(synchronize_session=False)

            # Delete the old report so process_document creates a fresh one
            db.delete(report)
            db.flush()

            # Get the parent document and re-run normalization
            doc = db.query(ExamDocument).filter(
                ExamDocument.id == doc_id
            ).first()
            if not doc:
                db.commit()
                cleaned.append({
                    "report_id": report_id,
                    "document_id": doc_id,
                    "patient_id": patient_id,
                    "success": False,
                    "error": "document_not_found",
                    "deleted_results": deleted,
                })
                continue

            try:
                result = process_document(db, doc)
                db.commit()
                cleaned.append({
                    "report_id": report_id,
                    "document_id": doc_id,
                    "patient_id": patient_id,
                    "deleted_results": deleted,
                    "new_results_count": result.get("results_count", 0),
                    "normalization_status": result.get("normalization_status"),
                    "success": True,
                })
                logger.info(
                    "[RECLEAN-CGM] report=%s doc=%s patient=%s \u2192 deleted %d artifacts, new=%d results",
                    report_id, doc_id, patient_id, deleted, result.get("results_count", 0),
                )
            except Exception as proc_err:
                db.rollback()
                logger.error("[RECLEAN-CGM] doc=%s failed: %s", doc_id, proc_err)
                cleaned.append({
                    "report_id": report_id,
                    "document_id": doc_id,
                    "patient_id": patient_id,
                    "success": False,
                    "error": str(proc_err),
                    "deleted_results": deleted,
                })

        return jsonify({
            "cgm_reports_scanned": len(cgm_reports),
            "reports_recleaned": len(cleaned),
            "results": cleaned,
        }), 200

    except Exception as e:
        db.rollback()
        logger.error("[RECLEAN-CGM] Fatal: %s", e)
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()
