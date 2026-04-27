"""
Autoanosis OCR Endpoint v2.0.0
Handles PDF and image OCR, then immediately triggers the full exams ingestion pipeline.
One upload = one or more structured ExamReport records.

Auth: X-Identity-Token required (same mechanism as /chat and /exams endpoints).
Dedup: sha256 + patient_id checked before any processing.
"""

import os
import io
import base64
import hashlib
import logging

from flask import Blueprint, request, jsonify
from openai import OpenAI

logger = logging.getLogger(__name__)

OCR_MODEL_VERSION = "gpt-4o-mini-v1"
NORMALIZER_VERSION = "v3"

ocr_bp = Blueprint("ocr", __name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ---------------------------------------------------------------------------
# Auth helper (mirrors exams_flask._require_identity_token)
# ---------------------------------------------------------------------------

def _require_identity_token():
    """
    Verify X-Identity-Token. Returns (uid: int, error_response).
    Exactly one will be None.
    """
    try:
        from identity import verify_identity_token
    except ImportError:
        logger.error("[OCR] identity module not found")
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
# POST /ocr  — main entry point
# ---------------------------------------------------------------------------

@ocr_bp.route("/ocr", methods=["POST"])
def process_ocr():
    """
    Upload a PDF or image exam file.
    1. Authenticate via X-Identity-Token.
    2. Compute sha256 of the file bytes.
    3. Extract raw text via OCR.
    4. Call the exams ingestion pipeline (create_document + process_document).
    5. Return document_id, status, duplicate flag, and normalization_status.

    Form fields:
      file         (required) — PDF or image file
      source       (optional) — "mobile_upload" | "web_upload" | "admin_upload"
                                defaults to "mobile_upload"
    """
    uid, err = _require_identity_token()
    if err:
        return err

    if "file" not in request.files:
        return jsonify({"success": False, "error": "NO_FILE", "message": "No file provided"}), 400

    file = request.files["file"]
    if not file or file.filename == "":
        return jsonify({"success": False, "error": "EMPTY_FILE", "message": "Empty file"}), 400

    ingestion_source = request.form.get("source", "mobile_upload").strip()
    if ingestion_source not in ("mobile_upload", "web_upload", "admin_upload"):
        ingestion_source = "mobile_upload"

    file_data = file.read()
    filename = (file.filename or "").lower()
    content_type = (file.content_type or "").lower()

    # Compute sha256 of raw file bytes
    file_sha256 = hashlib.sha256(file_data).hexdigest()

    # --- OCR ---
    try:
        if content_type == "application/pdf" or filename.endswith(".pdf"):
            raw_text, ocr_type = _extract_pdf(file_data)
        elif content_type.startswith("image/"):
            raw_text = _ocr_image_with_openai(file_data, content_type)
            ocr_type = "image"
        else:
            return jsonify({
                "success": False,
                "error": "UNSUPPORTED_TYPE",
                "message": f"Unsupported file type: {content_type}",
            }), 400
    except Exception as e:
        logger.error("[OCR] extraction error for uid=%s: %s", uid, e)
        return jsonify({"success": False, "error": "OCR_FAILED", "message": str(e)}), 500

    if not raw_text or not raw_text.strip():
        return jsonify({
            "success": False,
            "error": "EMPTY_EXTRACTION",
            "message": "No text could be extracted from the file",
        }), 422

    # --- Ingest pipeline ---
    try:
        from exams_module.db.database import get_db
        from exams_module.schemas.exam_schemas import DocumentCreate
        from exams_module.services.exam_service import create_document, process_document

        payload = DocumentCreate(
            patient_id=uid,
            sha256=file_sha256,
            raw_text=raw_text.strip(),
            ingestion_source=ingestion_source,
            ocr_model_version=OCR_MODEL_VERSION,
        )

        db = next(get_db())
        try:
            doc, is_duplicate = create_document(db, payload)

            if is_duplicate:
                logger.info(
                    "[OCR] Duplicate upload skipped: sha256=%s patient=%s existing_doc=%s",
                    file_sha256[:12], uid, doc.id,
                )
                return jsonify({
                    "success": True,
                    "duplicate": True,
                    "is_duplicate": True,
                    "document_id": doc.id,
                    "status": doc.status,
                    "message": "This file has already been uploaded and processed",
                }), 200

            db.flush()
            result = process_document(db, doc)
            db.commit()

            logger.info(
                "[OCR] Ingestion complete: doc=%s status=%s norm=%s patient=%s source=%s",
                doc.id, result.get("status"), result.get("normalization_status"),
                uid, ingestion_source,
            )

            return jsonify({
                "success": True,
                "duplicate": False,
                "is_duplicate": False,
                "document_id": doc.id,
                "status": result.get("status"),
                "normalization_status": result.get("normalization_status"),
                "report_count": result.get("report_count", 0),
                "needs_review": result.get("normalization_status") == "needs_review",
                "ocr_type": ocr_type,
                "ocr_model_version": OCR_MODEL_VERSION,
                "normalizer_version": NORMALIZER_VERSION,
            }), 201

        except Exception as e:
            db.rollback()
            logger.error("[OCR] ingest pipeline error for uid=%s: %s", uid, e)
            return jsonify({
                "success": False,
                "error": "INGESTION_FAILED",
                "message": str(e),
            }), 500
        finally:
            db.close()

    except ImportError as e:
        logger.error("[OCR] exams_module import error: %s", e)
        return jsonify({
            "success": False,
            "error": "SERVER_CONFIGURATION_ERROR",
            "message": "Exams module unavailable",
        }), 500


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_pdf(file_data: bytes) -> tuple[str, str]:
    """
    Extract text from a PDF.
    1. Try PyMuPDF text extraction (text-based PDFs).
    2. Fall back to OpenAI Vision OCR (scanned PDFs).
    Returns (raw_text, ocr_type).
    """
    try:
        import fitz
    except ImportError:
        raise RuntimeError("PyMuPDF not installed. Run: pip install pymupdf")

    doc = fitz.open(stream=file_data, filetype="pdf")

    # Attempt text extraction
    text_pages = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text").strip()
        if text:
            text_pages.append(text)

    if text_pages:
        return "\n\n".join(text_pages), "pdf_text"

    # Scanned PDF — OCR via OpenAI Vision (max 5 pages)
    ocr_parts = []
    max_pages = min(5, len(doc))
    for page_num in range(max_pages):
        page = doc[page_num]
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        img_bytes = pix.tobytes("png")
        ocr_text = _ocr_image_with_openai(img_bytes, "image/png")
        if ocr_text:
            ocr_parts.append(f"--- Σελίδα {page_num + 1} ---\n{ocr_text}")

    if ocr_parts:
        return "\n\n".join(ocr_parts), "pdf_scanned"

    return "", "pdf_empty"


def _ocr_image_with_openai(image_bytes: bytes, content_type: str) -> str:
    """
    OCR an image using OpenAI Vision.
    Returns extracted text string (empty string on failure).
    """
    try:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Εξάγε όλο το κείμενο από αυτή την εικόνα ιατρικής εξέτασης.\n"
                                "Περίλαβε:\n"
                                "- Όνομα εξέτασης\n"
                                "- Ημερομηνία\n"
                                "- Όλες τις τιμές και μετρήσεις\n"
                                "- Τυχόν σχόλια ή παρατηρήσεις\n\n"
                                "Επέστρεψε μόνο το εξαγμένο κείμενο, χωρίς επεξηγήσεις."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{content_type};base64,{b64}"},
                        },
                    ],
                }
            ],
            max_tokens=2000,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error("[OCR] OpenAI Vision error: %s", e)
        return ""
