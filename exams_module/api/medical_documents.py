"""
Autoanosis — Medical Document Archive API
Endpoints for storing and retrieving arbitrary medical documents
(PDFs, images, articles, referrals) WITHOUT OCR processing.

Endpoints:
  POST   /medical-documents/upload          — upload a document (multipart/form-data)
  GET    /medical-documents/list            — list all documents for the patient
  GET    /medical-documents/<doc_id>        — get document metadata + file data
  DELETE /medical-documents/<doc_id>        — delete a document
  PATCH  /medical-documents/<doc_id>        — update metadata (title, category, date, notes)

Auth: X-Identity-Token (patient JWT) for all endpoints.
"""
import base64
import hashlib
import logging
import os
from datetime import datetime

from flask import Blueprint, request, jsonify

from exams_module.db.database import get_db
from exams_module.models.medical_document_model import MedicalDocument

logger = logging.getLogger(__name__)

medical_docs_bp = Blueprint("medical_documents", __name__, url_prefix="/medical-documents")

# Max file size: 20 MB
MAX_FILE_SIZE = 20 * 1024 * 1024

ALLOWED_CATEGORIES = {
    "general", "lab_result", "imaging", "referral",
    "prescription", "article", "discharge_summary", "other"
}


# ---------------------------------------------------------------------------
# Auth helper — reuse identity module
# ---------------------------------------------------------------------------
def _require_identity():
    """Returns (patient_id: int, error_response). One will be None."""
    try:
        from identity import verify_identity_token
    except ImportError:
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


def _doc_to_dict(doc: MedicalDocument, include_file_data: bool = False) -> dict:
    """Serialize a MedicalDocument to a dict."""
    d = {
        "id": doc.id,
        "patient_id": doc.patient_id,
        "original_filename": doc.original_filename,
        "mime_type": doc.mime_type,
        "file_size_bytes": doc.file_size_bytes,
        "document_title": doc.document_title,
        "document_category": doc.document_category,
        "document_date": doc.document_date.isoformat() if doc.document_date else None,
        "notes": doc.notes,
        "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
    }
    if include_file_data and doc.file_data:
        d["file_data"] = doc.file_data  # base64 string
    return d


# ---------------------------------------------------------------------------
# POST /medical-documents/upload
# ---------------------------------------------------------------------------
@medical_docs_bp.route("/upload", methods=["POST"])
def upload_document():
    """
    Upload a medical document for archiving.
    Accepts multipart/form-data with:
      - file: the document file (required)
      - document_title: optional display title
      - document_category: one of ALLOWED_CATEGORIES (default: general)
      - document_date: ISO date string (optional)
      - notes: optional text notes
    """
    patient_id, err = _require_identity()
    if err:
        return err

    # Get file
    if "file" not in request.files:
        return jsonify({"error": "missing_file"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "empty_filename"}), 400

    file_bytes = f.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        return jsonify({"error": "file_too_large", "max_bytes": MAX_FILE_SIZE}), 413

    # Compute hash
    sha256 = hashlib.sha256(file_bytes).hexdigest()

    # Check for duplicate
    gen = get_db()
    db = next(gen)
    try:
        existing = db.query(MedicalDocument).filter(
            MedicalDocument.patient_id == patient_id,
            MedicalDocument.sha256 == sha256
        ).first()
        if existing:
            return jsonify({
                "duplicate": True,
                "document_id": existing.id,
                "message": "Το αρχείο υπάρχει ήδη στο αρχείο σας",
                "document": _doc_to_dict(existing)
            }), 200

        # Parse metadata from form
        document_title = request.form.get("document_title", "").strip() or f.filename
        document_category = request.form.get("document_category", "general").strip()
        if document_category not in ALLOWED_CATEGORIES:
            document_category = "general"

        document_date = None
        date_str = request.form.get("document_date", "").strip()
        if date_str:
            try:
                document_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        notes = request.form.get("notes", "").strip() or None

        # Encode file as base64
        file_b64 = base64.b64encode(file_bytes).decode("utf-8")

        # Detect mime type
        mime_type = f.content_type or "application/octet-stream"

        doc = MedicalDocument(
            patient_id=patient_id,
            original_filename=f.filename,
            mime_type=mime_type,
            file_size_bytes=len(file_bytes),
            sha256=sha256,
            file_data=file_b64,
            document_title=document_title,
            document_category=document_category,
            document_date=document_date,
            notes=notes,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        logger.info(f"[MEDICAL-DOCS] Uploaded doc={doc.id} patient={patient_id} file={f.filename} size={len(file_bytes)}")

        return jsonify({
            "success": True,
            "document_id": doc.id,
            "document": _doc_to_dict(doc)
        }), 201

    except Exception as e:
        db.rollback()
        logger.error(f"[MEDICAL-DOCS] Upload error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /medical-documents/list
# ---------------------------------------------------------------------------
@medical_docs_bp.route("/list", methods=["GET"])
def list_documents():
    """List all medical documents for the authenticated patient."""
    patient_id, err = _require_identity()
    if err:
        return err

    gen = get_db()
    db = next(gen)
    try:
        docs = db.query(MedicalDocument).filter(
            MedicalDocument.patient_id == patient_id
        ).order_by(MedicalDocument.uploaded_at.desc()).all()

        return jsonify({
            "documents": [_doc_to_dict(d) for d in docs],
            "total": len(docs)
        }), 200

    except Exception as e:
        logger.error(f"[MEDICAL-DOCS] List error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /medical-documents/<doc_id>
# ---------------------------------------------------------------------------
@medical_docs_bp.route("/<doc_id>", methods=["GET"])
def get_document(doc_id):
    """Get a single document with file data."""
    patient_id, err = _require_identity()
    if err:
        return err

    gen = get_db()
    db = next(gen)
    try:
        doc = db.query(MedicalDocument).filter(
            MedicalDocument.id == doc_id,
            MedicalDocument.patient_id == patient_id
        ).first()

        if not doc:
            return jsonify({"error": "not_found"}), 404

        return jsonify(_doc_to_dict(doc, include_file_data=True)), 200

    except Exception as e:
        logger.error(f"[MEDICAL-DOCS] Get error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ---------------------------------------------------------------------------
# DELETE /medical-documents/<doc_id>
# ---------------------------------------------------------------------------
@medical_docs_bp.route("/<doc_id>", methods=["DELETE"])
def delete_document(doc_id):
    """Permanently delete a document."""
    patient_id, err = _require_identity()
    if err:
        return err

    gen = get_db()
    db = next(gen)
    try:
        doc = db.query(MedicalDocument).filter(
            MedicalDocument.id == doc_id,
            MedicalDocument.patient_id == patient_id
        ).first()

        if not doc:
            return jsonify({"error": "not_found"}), 404

        filename = doc.original_filename
        db.delete(doc)
        db.commit()

        logger.info(f"[MEDICAL-DOCS] Deleted doc={doc_id} patient={patient_id} file={filename}")

        return jsonify({"deleted": True, "document_id": doc_id}), 200

    except Exception as e:
        db.rollback()
        logger.error(f"[MEDICAL-DOCS] Delete error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ---------------------------------------------------------------------------
# PATCH /medical-documents/<doc_id>
# ---------------------------------------------------------------------------
@medical_docs_bp.route("/<doc_id>", methods=["PATCH"])
def update_document(doc_id):
    """Update document metadata (title, category, date, notes)."""
    patient_id, err = _require_identity()
    if err:
        return err

    body = request.get_json(silent=True) or {}

    gen = get_db()
    db = next(gen)
    try:
        doc = db.query(MedicalDocument).filter(
            MedicalDocument.id == doc_id,
            MedicalDocument.patient_id == patient_id
        ).first()

        if not doc:
            return jsonify({"error": "not_found"}), 404

        if "document_title" in body:
            doc.document_title = body["document_title"] or doc.original_filename

        if "document_category" in body:
            cat = body["document_category"]
            if cat in ALLOWED_CATEGORIES:
                doc.document_category = cat

        if "document_date" in body:
            date_str = body["document_date"]
            if date_str:
                try:
                    doc.document_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                except ValueError:
                    pass
            else:
                doc.document_date = None

        if "notes" in body:
            doc.notes = body["notes"] or None

        db.commit()
        db.refresh(doc)

        return jsonify({"updated": True, "document": _doc_to_dict(doc)}), 200

    except Exception as e:
        db.rollback()
        logger.error(f"[MEDICAL-DOCS] Update error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()
