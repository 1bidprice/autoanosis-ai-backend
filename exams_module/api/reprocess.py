"""
Autoanosis Exams — Re-processing Endpoint
==========================================
Allows re-processing existing documents through the AI normalizer.
This is used to upgrade legacy reports (created by the regex normalizer)
to the new format with units, reference ranges, and abnormal flags.

Endpoint:
  POST /exams/admin/reprocess-all   — re-process all documents through AI normalizer

Auth: Requires AUTOA_AI_PROXY_SECRET in X-Admin-Secret header.
"""
import os
import logging
from flask import Blueprint, request, jsonify
from sqlalchemy.orm import joinedload

from exams_module.db.database import get_db
from exams_module.models.exam_models import ExamDocument, ExamReport, ExamResult
from exams_module.services.exam_service import process_document

logger = logging.getLogger(__name__)

reprocess_bp = Blueprint("reprocess", __name__, url_prefix="/exams/admin")


def _require_admin_secret():
    """Verify admin secret for protected endpoints."""
    secret = os.environ.get("AUTOA_AI_PROXY_SECRET", "")
    provided = request.headers.get("X-Admin-Secret", "").strip()
    if not secret or not provided or secret != provided:
        return False
    return True


@reprocess_bp.route("/reprocess-all", methods=["POST"])
def reprocess_all_documents():
    """
    Re-process all existing documents through the AI normalizer.
    Deletes old reports/results and creates new ones.
    
    Auth: X-Admin-Secret header must match AUTOA_AI_PROXY_SECRET.
    """
    if not _require_admin_secret():
        return jsonify({"error": "unauthorized"}), 401

    gen = get_db()
    db = next(gen)
    
    results_summary = {
        "total_documents": 0,
        "reprocessed": 0,
        "failed": 0,
        "skipped": 0,
        "details": []
    }

    try:
        # Get all documents that have raw_text
        documents = (
            db.query(ExamDocument)
            .filter(ExamDocument.raw_text.isnot(None))
            .filter(ExamDocument.raw_text != "")
            .order_by(ExamDocument.created_at.desc())
            .all()
        )

        results_summary["total_documents"] = len(documents)

        for doc in documents:
            try:
                # Delete existing reports and results for this document
                old_reports = (
                    db.query(ExamReport)
                    .filter(ExamReport.document_id == doc.id)
                    .all()
                )
                
                for old_report in old_reports:
                    # Delete results for this report
                    db.query(ExamResult).filter(
                        ExamResult.report_id == old_report.id
                    ).delete()
                    db.delete(old_report)
                
                db.flush()

                # Re-process through AI normalizer
                result = process_document(db, doc)
                db.flush()

                results_summary["reprocessed"] += 1
                results_summary["details"].append({
                    "document_id": doc.id,
                    "patient_id": doc.patient_id,
                    "status": "success",
                    "normalization_status": result.get("normalization_status"),
                    "report_count": len(result.get("report_ids", [])),
                })

            except Exception as e:
                logger.error(f"[REPROCESS] Failed doc {doc.id}: {e}")
                results_summary["failed"] += 1
                results_summary["details"].append({
                    "document_id": doc.id,
                    "patient_id": doc.patient_id,
                    "status": "failed",
                    "error": str(e),
                })

        db.commit()
        logger.info(
            f"[REPROCESS] Complete: {results_summary['reprocessed']} reprocessed, "
            f"{results_summary['failed']} failed out of {results_summary['total_documents']}"
        )
        return jsonify(results_summary), 200

    except Exception as e:
        db.rollback()
        logger.error(f"[REPROCESS] Fatal error: {e}")
        return jsonify({"error": "reprocess_failed", "detail": str(e)}), 500
    finally:
        db.close()


@reprocess_bp.route("/reprocess/<int:document_id>", methods=["POST"])
def reprocess_single_document(document_id):
    """
    Re-process a single document through the AI normalizer.
    
    Auth: X-Admin-Secret header must match AUTOA_AI_PROXY_SECRET.
    """
    if not _require_admin_secret():
        return jsonify({"error": "unauthorized"}), 401

    gen = get_db()
    db = next(gen)

    try:
        doc = db.query(ExamDocument).filter(ExamDocument.id == document_id).first()
        if not doc:
            return jsonify({"error": "document_not_found"}), 404

        # Delete existing reports and results
        old_reports = (
            db.query(ExamReport)
            .filter(ExamReport.document_id == doc.id)
            .all()
        )
        for old_report in old_reports:
            db.query(ExamResult).filter(
                ExamResult.report_id == old_report.id
            ).delete()
            db.delete(old_report)
        db.flush()

        # Re-process
        result = process_document(db, doc)
        db.commit()

        return jsonify({
            "document_id": doc.id,
            "patient_id": doc.patient_id,
            "status": "success",
            "normalization_status": result.get("normalization_status"),
            "report_ids": result.get("report_ids", []),
        }), 200

    except Exception as e:
        db.rollback()
        logger.error(f"[REPROCESS] Failed doc {document_id}: {e}")
        return jsonify({"error": "reprocess_failed", "detail": str(e)}), 500
    finally:
        db.close()
