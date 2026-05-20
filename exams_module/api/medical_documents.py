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
import io
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

# Max extracted text stored per document (chars) — keeps AI context manageable
MAX_EXTRACTED_TEXT_CHARS = 15000

ALLOWED_CATEGORIES = {
    "general", "lab_result", "imaging", "referral",
    "prescription", "article", "discharge_summary", "other"
}


# ---------------------------------------------------------------------------
# Auto-category detection from extracted text
# ---------------------------------------------------------------------------
def _detect_category_from_text(text: str, filename: str) -> str | None:
    """
    Heuristically detect document category from extracted text content.
    Returns a category string or None if undetermined (caller uses 'general').
    """
    if not text:
        return None
    t = text.lower()

    # Article / scientific publication markers
    article_markers = [
        "dear editor", "abstract", "introduction", "conclusion",
        "references", "doi:", "doi.org", "journal", "pubmed",
        "case report", "letter to the editor", "keywords:",
        "corresponding author", "department of", "university of",
        "golimumab", "adalimumab", "etanercept", "infliximab",
        "psoriatic arthritis", "rheumatoid arthritis", "inflammatory",
        "pseudotumour", "pseudotumor", "spleen", "splenic",
        "orcid", "issn", "volume", "issue", "pages",
    ]
    article_score = sum(1 for m in article_markers if m in t)
    if article_score >= 3:
        return "article"

    # Discharge summary / hospital letter
    discharge_markers = [
        "εξιτήριο", "εξιτηριο", "discharge summary", "discharge letter",
        "νοσηλεία", "νοσηλεια", "εισαγωγή", "εισαγωγη",
        "εξιτήριο", "ημερομηνία εισαγωγής", "ημερομηνια εισαγωγης",
    ]
    if any(m in t for m in discharge_markers):
        return "discharge_summary"

    # Imaging report
    imaging_markers = [
        "υπερηχογράφημα", "υπερηχογραφημα", "μαγνητική", "μαγνητικη",
        "αξονική", "αξονικη", "ακτινογραφία", "ακτινογραφια",
        "ultrasound", "mri", "ct scan", "x-ray", "echography",
        "απεικόνιση", "απεικονιση", "εύρημα", "ευρημα",
    ]
    if any(m in t for m in imaging_markers):
        return "imaging"

    # Lab result
    lab_markers = [
        "αιμοσφαιρίνη", "αιμοσφαιρινη", "λευκοκύτταρα", "λευκοκυτταρα",
        "αιματοκρίτης", "αιματοκριτης", "crp", "esr", "ferritin",
        "haemoglobin", "hemoglobin", "platelet", "wbc", "rbc",
    ]
    if any(m in t for m in lab_markers):
        return "lab_result"

    # Referral / prescription
    referral_markers = [
        "παραπεμπτικό", "παραπεμπτικο", "παραπομπή", "παραπομπη",
        "referral", "prescription", "συνταγή", "συνταγη",
    ]
    if any(m in t for m in referral_markers):
        return "referral"

    return None


# ---------------------------------------------------------------------------
# Text extraction helper
# ---------------------------------------------------------------------------
def _extract_text_from_bytes(file_bytes: bytes, mime_type: str, filename: str) -> str | None:
    """
    Extract text content from a file for AI context.
    Supports PDF (via PyMuPDF with OCR fallback for scanned PDFs) and plain text files.
    Returns extracted text (truncated) or None if extraction fails/unsupported.
    """
    text = None

    # PDF extraction via PyMuPDF (fitz)
    if mime_type in ("application/pdf",) or filename.lower().endswith(".pdf"):
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            pages_text = []
            for page in doc:
                page_text = page.get_text("text")
                if page_text.strip():
                    pages_text.append(page_text.strip())
            doc.close()
            if pages_text:
                text = "\n\n".join(pages_text)
                logger.info(f"[MEDICAL-DOCS] PyMuPDF extracted {len(text)} chars from {filename}")
        except Exception as e:
            logger.warning(f"[MEDICAL-DOCS] PDF text extraction failed: {e}")

        # OCR fallback for scanned/image-based PDFs
        if not text:
            logger.info(f"[MEDICAL-DOCS] No text layer found in {filename}, attempting OCR...")
            try:
                import pytesseract
                from pdf2image import convert_from_bytes
                from PIL import Image
                import io

                # Convert PDF pages to images (max 8 pages to limit processing time)
                images = convert_from_bytes(
                    file_bytes,
                    dpi=200,
                    first_page=1,
                    last_page=8,
                    fmt="jpeg"
                )
                ocr_pages = []
                for i, img in enumerate(images):
                    # OCR with Greek + English
                    page_text = pytesseract.image_to_string(
                        img,
                        lang="ell+eng",
                        config="--psm 1"
                    )
                    if page_text.strip():
                        ocr_pages.append(page_text.strip())
                    logger.info(f"[MEDICAL-DOCS] OCR page {i+1}: {len(page_text)} chars")

                if ocr_pages:
                    text = "\n\n".join(ocr_pages)
                    logger.info(f"[MEDICAL-DOCS] OCR extracted {len(text)} chars from {filename}")
                else:
                    logger.warning(f"[MEDICAL-DOCS] OCR produced no text from {filename}")
            except ImportError as e:
                logger.warning(f"[MEDICAL-DOCS] OCR libraries not available: {e}")
            except Exception as e:
                logger.warning(f"[MEDICAL-DOCS] OCR failed for {filename}: {e}")

    # Plain text files
    elif mime_type in ("text/plain",) or filename.lower().endswith(".txt"):
        try:
            text = file_bytes.decode("utf-8", errors="replace")
        except Exception as e:
            logger.warning(f"[MEDICAL-DOCS] Text file decode failed: {e}")

    # Truncate to max chars
    if text:
        text = text.strip()
        if len(text) > MAX_EXTRACTED_TEXT_CHARS:
            text = text[:MAX_EXTRACTED_TEXT_CHARS] + "\n\n[... κείμενο περικόπηκε ...]"

    return text if text else None


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
        "has_extracted_text": bool(doc.extracted_text),
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
    Text is automatically extracted from PDFs for AI context.
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

        # Extract text for AI context
        extracted_text = _extract_text_from_bytes(file_bytes, mime_type, f.filename)
        if extracted_text:
            logger.info(f"[MEDICAL-DOCS] Extracted {len(extracted_text)} chars from {f.filename}")
            # Auto-detect category from content if user left it as 'general' (default)
            if document_category == "general":
                detected_cat = _detect_category_from_text(extracted_text, f.filename)
                if detected_cat:
                    document_category = detected_cat
                    logger.info(f"[MEDICAL-DOCS] Auto-detected category: {detected_cat} for {f.filename}")
        else:
            logger.info(f"[MEDICAL-DOCS] No text extracted from {f.filename} (mime={mime_type})")

        doc = MedicalDocument(
            patient_id=patient_id,
            original_filename=f.filename,
            mime_type=mime_type,
            file_size_bytes=len(file_bytes),
            sha256=sha256,
            file_data=file_b64,
            extracted_text=extracted_text,
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
            "text_extracted": bool(extracted_text),
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


# ---------------------------------------------------------------------------
# POST /medical-documents/<doc_id>/reprocess
# ---------------------------------------------------------------------------
@medical_docs_bp.route("/<doc_id>/reprocess", methods=["POST"])
def reprocess_document(doc_id):
    """
    Re-run text extraction (OCR) on an existing document.
    Useful when a document was uploaded before OCR was available,
    or when OCR failed silently on the first upload.
    Requires X-Identity-Token (owner) OR X-Admin-Secret header.
    """
    import os as _os
    from exams_module.db.database import SessionLocal
    db = SessionLocal()
    try:
        # Auth: identity token (owner) OR admin secret
        patient_id = None
        admin_secret = request.headers.get("X-Admin-Secret", "").strip()
        expected_secret = _os.environ.get("AUTOA_AI_PROXY_SECRET", "")
        if admin_secret and expected_secret and admin_secret == expected_secret:
            # Admin access — no patient_id restriction
            pass
        else:
            patient_id, err = _require_identity()
            if err:
                return err

        doc = db.query(MedicalDocument).filter(MedicalDocument.id == doc_id).first()
        if not doc:
            return jsonify({"error": "document_not_found"}), 404

        # Enforce ownership for non-admin
        if patient_id is not None and doc.patient_id != patient_id:
            return jsonify({"error": "forbidden"}), 403

        # Decode stored file data
        if not doc.file_data:
            return jsonify({"error": "no_file_data_stored"}), 400

        try:
            import base64 as _b64
            file_bytes = _b64.b64decode(doc.file_data)
        except Exception as e:
            return jsonify({"error": f"file_decode_failed: {e}"}), 500

        # Re-run extraction
        logger.info(f"[MEDICAL-DOCS] Reprocessing doc={doc_id} file={doc.original_filename}")
        extracted_text = _extract_text_from_bytes(
            file_bytes,
            doc.mime_type or "application/pdf",
            doc.original_filename or ""
        )

        if extracted_text:
            doc.extracted_text = extracted_text
            # Auto-detect category if still 'general' or None
            if doc.document_category in (None, "general"):
                detected_cat = _detect_category_from_text(extracted_text, doc.original_filename or "")
                if detected_cat:
                    doc.document_category = detected_cat
                    logger.info(f"[MEDICAL-DOCS] Reprocess auto-detected category: {detected_cat}")
            db.commit()
            db.refresh(doc)
            logger.info(f"[MEDICAL-DOCS] Reprocess success: {len(extracted_text)} chars for doc={doc_id}")
            return jsonify({
                "success": True,
                "document_id": doc_id,
                "text_extracted": True,
                "chars_extracted": len(extracted_text),
                "document_category": doc.document_category,
                "preview": extracted_text[:300],
            }), 200
        else:
            logger.warning(f"[MEDICAL-DOCS] Reprocess produced no text for doc={doc_id}")
            return jsonify({
                "success": False,
                "document_id": doc_id,
                "text_extracted": False,
                "message": "OCR produced no text — file may be corrupted or unsupported format",
            }), 200

    except Exception as e:
        db.rollback()
        logger.error(f"[MEDICAL-DOCS] Reprocess error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()
