"""
Autoanosis OCR Endpoint v3.0.0
Hybrid OCR Safety Pipeline:
  Pass 1: Strict verbatim transcription with gpt-4o-mini (cheap, fast)
  Pass 2: Verification layer — detects high-risk medical OCR errors
  Pass 3: Escalation to gpt-4o ONLY if confidence is low or risk detected

Auth: X-Identity-Token required (same mechanism as /chat and /exams endpoints).
Dedup: sha256 + patient_id checked before any processing.
"""

import os
import io
import re
import base64
import hashlib
import logging
import threading

from flask import Blueprint, request, jsonify
from openai import OpenAI

logger = logging.getLogger(__name__)

OCR_MODEL_VERSION = "hybrid-v3.1"
NORMALIZER_VERSION = "v3"

ocr_bp = Blueprint("ocr", __name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ---------------------------------------------------------------------------
# High-risk medical terms — OCR errors in these are clinically dangerous
# ---------------------------------------------------------------------------
HIGH_RISK_TERMS = [
    "άνευ", "ανευ", "χωρίς", "χωρις",
    "λίθων", "λιθων", "λίθος", "λιθος",
    "φυσιολογικά", "φυσιολογικα", "φυσιολογικ",
    "παθολογικά", "παθολογικα",
    "σπληνεκτομή", "σπληνεκτομη",
    "χολοκυστεκτομή", "χολοκυστεκτομη",
    "νεφρεκτομή", "νεφρεκτομη",
    "αρνητικό", "αρνητικο",
    "θετικό", "θετικο",
    "κανονικού", "κανονικου",
    "χοληδόχος", "χοληδοχος",
    "σπλήνας", "σπληνας",
    "ήπαρ", "ηπαρ",
    "πάγκρεας", "παγκρεας",
    "νεφροί", "νεφροι",
]

# Suspicious substitutions that indicate OCR hallucination
SUSPICIOUS_PATTERNS = [
    # "Ανευ λίθων" should NEVER become "Απειλούνται" or similar
    (r"απειλ", "χοληδόχος|χολ|κύστ|gallbladder"),
    # "Σπληνεκτομή" should NEVER become "Σπληνική" or "Σπλήνας φυσιολογικός"
    (r"σπληνικ[ήη]", None),
]


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _require_identity_token():
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

    file_sha256 = hashlib.sha256(file_data).hexdigest()

    # --- OCR (Hybrid Safety Pipeline) ---
    try:
        if content_type == "application/pdf" or filename.endswith(".pdf"):
            raw_text, ocr_type, ocr_confidence = _extract_pdf(file_data)
        elif content_type.startswith("image/"):
            raw_text, ocr_confidence = _ocr_image_hybrid(file_data, content_type, filename=filename)
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

    # --- Deterministic Medical Lexicon Correction ---
    try:
        from medical_lexicon import apply_lexicon_corrections
        lex_result = apply_lexicon_corrections(raw_text.strip())
        corrected_text = lex_result.corrected
        if lex_result.correction_count > 0:
            logger.info(
                "[LEXICON] Applied %d corrections for uid=%s: %s",
                lex_result.correction_count, uid,
                [(c["original"], c["replacement"]) for c in lex_result.corrections],
            )
        if lex_result.needs_review:
            logger.warning("[LEXICON] Suspicious patterns remain after correction for uid=%s", uid)
            ocr_confidence = "low"
    except Exception as lex_err:
        logger.warning("[LEXICON] Correction layer failed (using raw OCR text): %s", lex_err)
        corrected_text = raw_text.strip()

    # --- Ingest pipeline ---
    try:
        from exams_module.db.database import get_db
        from exams_module.schemas.exam_schemas import DocumentCreate
        from exams_module.services.exam_service import create_document, process_document

        payload = DocumentCreate(
            patient_id=uid,
            sha256=file_sha256,
            raw_text=corrected_text,
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
            doc_id = doc.id
            db.commit()

            # ---------------------------------------------------------------
            # Async background normalization — return 200 + extracted_text
            # immediately (WordPress needs extracted_text to save to health_info
            # and fire the autoanosis_ocr_complete hook).
            # GPT normalization runs in a background daemon thread.
            # ---------------------------------------------------------------
            def _background_normalize(document_id, patient_id, source, confidence):
                try:
                    from exams_module.db.database import get_db as _get_db
                    from exams_module.services.exam_service import process_document as _process
                    _db = next(_get_db())
                    try:
                        from exams_module.models.exam_models import ExamDocument as _Doc
                        _doc = _db.query(_Doc).filter(_Doc.id == document_id).first()
                        if _doc:
                            _result = _process(_db, _doc)
                            _db.commit()
                            logger.info(
                                "[OCR-BG] Normalization complete: doc=%s status=%s norm=%s patient=%s source=%s confidence=%s",
                                document_id, _result.get("status"), _result.get("normalization_status"),
                                patient_id, source, confidence,
                            )
                        else:
                            logger.error("[OCR-BG] Document %s not found in background thread", document_id)
                    except Exception as _e:
                        _db.rollback()
                        logger.error("[OCR-BG] Normalization failed for doc=%s: %s", document_id, _e)
                    finally:
                        _db.close()
                except Exception as _outer:
                    logger.error("[OCR-BG] Fatal error in background thread for doc=%s: %s", document_id, _outer)

            t = threading.Thread(
                target=_background_normalize,
                args=(doc_id, uid, ingestion_source, ocr_confidence),
                daemon=True,
            )
            t.start()

            logger.info(
                "[OCR] Accepted: doc=%s patient=%s source=%s — normalization running in background",
                doc_id, uid, ingestion_source,
            )

            # Return 200 with extracted_text so WordPress can save to health_info
            # and fire autoanosis_ocr_complete hook without waiting for GPT normalization
            return jsonify({
                "success": True,
                "duplicate": False,
                "is_duplicate": False,
                "document_id": doc_id,
                "extracted_text": corrected_text,
                "status": "processing",
                "normalization_status": "processing",
                "report_count": 0,
                "needs_review": False,
                "ocr_type": ocr_type,
                "ocr_confidence": ocr_confidence,
                "ocr_model_version": OCR_MODEL_VERSION,
                "normalizer_version": NORMALIZER_VERSION,
                "async": True,
            }), 200

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
# Hybrid OCR Safety Pipeline
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Image quality thresholds
# ---------------------------------------------------------------------------

# Minimum resolution: images below this are too small for gpt-4o-mini
# Phone photos are typically 3000x4000+ so this mainly catches thumbnails
MIN_PIXELS_FOR_MINI = 1200 * 1600   # 1,920,000 px (~1200x1600 = typical scan quality)

# Edge variance threshold: below this = blurry/phone-photo quality
# Sharp digital scan: >500. Phone photo of paper: 80-300. Blurry: <80
# We set this high (300) so phone photos of paper documents go to gpt-4o
BLUR_THRESHOLD = 300.0


def _assess_image_quality(image_bytes: bytes) -> tuple:
    """
    Assess image quality using Pillow (zero AI cost).
    Returns (quality: 'good' | 'poor', metrics: dict)

    Checks:
    1. Resolution - images below MIN_PIXELS_FOR_MINI are too small
    2. Blur (edge variance) - low variance = blurry
    """
    try:
        from PIL import Image, ImageFilter

        img = Image.open(io.BytesIO(image_bytes))
        width, height = img.size
        total_pixels = width * height

        # Convert to grayscale for blur detection
        gray = img.convert("L")

        # Approximate Laplacian variance using PIL FIND_EDGES filter
        edges = gray.filter(ImageFilter.FIND_EDGES)
        pixels = list(edges.getdata())
        n = len(pixels)
        if n > 0:
            mean = sum(pixels) / n
            variance = sum((p - mean) ** 2 for p in pixels) / n
        else:
            variance = 0.0

        metrics = {
            "width": width,
            "height": height,
            "total_pixels": total_pixels,
            "blur_variance": round(variance, 2),
        }

        if total_pixels < MIN_PIXELS_FOR_MINI:
            logger.info("[OCR] Quality: POOR (low-res %dx%d = %d px)", width, height, total_pixels)
            return "poor", {**metrics, "reason": "low_resolution"}

        if variance < BLUR_THRESHOLD:
            logger.info("[OCR] Quality: POOR (blurry, variance=%.1f < %.1f)", variance, BLUR_THRESHOLD)
            return "poor", {**metrics, "reason": "blurry"}

        logger.info("[OCR] Quality: GOOD (%dx%d, blur_var=%.1f)", width, height, variance)
        return "good", {**metrics, "reason": "ok"}

    except Exception as e:
        logger.warning("[OCR] Quality assessment failed: %s - assuming good quality", e)
        return "good", {"reason": "assessment_failed", "error": str(e)}


# CGM/Glucose sensor report keywords — detect from filename or image content
CGM_FILENAME_KEYWORDS = [
    "libreview", "libre", "freestylelibre", "freestyle", "cgm", "sensor",
    "glucos", "glucose", "tir", "ehba1c", "agp", "τάσεις", "taseis",
    "αισθητήρας", "αισθητηρας", "ζαχάρου", "zacharou", "διαβήτης", "diabitis",
]


def _is_cgm_image(filename: str) -> bool:
    """Heuristic: check if filename suggests a CGM/glucose sensor report screenshot."""
    fn = (filename or "").lower()
    return any(k in fn for k in CGM_FILENAME_KEYWORDS)


def _ocr_cgm_chart(image_bytes: bytes, content_type: str, model: str = "gpt-4o") -> str:
    """
    Specialized extraction for CGM/glucose sensor report screenshots.
    Instead of verbatim text copy, asks GPT to describe and extract all numeric data.
    """
    try:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Είσαι ένα σύστημα εξαγωγής δεδομένων από αναφορές αισθητήρα γλυκόζης (CGM). "
                        "Εξάγεις ΟΛΕΣ τις τιμές και μετρήσεις που εμφανίζονται στην εικόνα. "
                        "Επιστρέφεις δομημένο κείμενο με όλες τις αριθμητικές τιμές."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Αυτή είναι μια εικόνα από αναφορά αισθητήρα γλυκόζης (CGM/LibreView/FreeStyle Libre).\n\n"
                                "Εξάγαγε ΟΛΑ τα δεδομένα που βλέπεις, συμπεριλαμβανομένων:\n"
                                "- Χρονική περίοδος (από - έως)\n"
                                "- Χρόνος κάλυψης CGM (%)\n"
                                "- Αριθμός αποτελεσμάτων αισθητήρα\n"
                                "- eHbA1c (%)\n"
                                "- MBG / Μέση γλυκόζη (mg/dL)\n"
                                "- Time in Range (TIR): Φυσιολογικό (70-180 mg/dL) %, Υψηλό (>180) %, Χαμηλό (<70) %\n"
                                "- LBGI (Δείκτης Χαμηλής ΓΑ)\n"
                                "- HBGI (Δείκτης Υψηλής ΓΑ)\n"
                                "- Οποιεσδήποτε άλλες τιμές ή στατιστικά που εμφανίζονται\n\n"
                                "Μορφοποίησε την απάντηση ως λίστα: 'Παράμετρος: Τιμή Μονάδα'\n"
                                "Παράδειγμα:\n"
                                "Χρόνος κάλυψης CGM: 96%\n"
                                "eHbA1c: 4.8%\n"
                                "MBG: 92 mg/dL\n"
                                "TIR Φυσιολογικό: 93.1%\n"
                                "TIR Χαμηλό: 6.7%\n"
                                "TIR Υψηλό: 0.2%\n"
                                "LBGI: 3\n"
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{content_type};base64,{b64}"},
                        },
                    ],
                }
            ],
            max_tokens=1500,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error("[OCR] CGM Vision error: %s", e)
        return ""


def _ocr_image_hybrid(image_bytes: bytes, content_type: str, filename: str = "") -> tuple:
    """
    Hybrid OCR pipeline:
    0. Pass 0: Image quality assessment (Pillow, zero AI cost)
               -> Poor quality images go directly to gpt-4o (skip gpt-4o-mini)
    1. Pass 1: Strict verbatim transcription with gpt-4o-mini (good quality only)
    2. Pass 2: Verification - detect high-risk medical OCR errors
    3. Pass 3: Escalate to gpt-4o ONLY if risk detected or confidence low

    Returns (text, confidence) where confidence is "high" | "medium" | "low"
    """
    # Pass 0a: CGM/Glucose sensor detection — use specialized chart extraction prompt
    if _is_cgm_image(filename):
        logger.info("[OCR] Detected CGM/sensor image from filename — using specialized CGM prompt")
        cgm_text = _ocr_cgm_chart(image_bytes, content_type, model="gpt-4o")
        if cgm_text and len(cgm_text.strip()) > 20:
            return cgm_text, "high"
        logger.warning("[OCR] CGM extraction returned empty — falling back to standard OCR")

    # Pass 0b: Image quality assessment (zero cost)
    quality, quality_metrics = _assess_image_quality(image_bytes)

    if quality == "poor":
        reason = quality_metrics.get("reason", "unknown")
        logger.info("[OCR] Pass 0: Poor quality (%s) - using gpt-4o directly", reason)
        text_4o = _ocr_strict_verbatim(image_bytes, content_type, model="gpt-4o")
        if text_4o:
            return text_4o, "medium"  # medium: image quality was poor
        return "", "low"

    # Pass 1: Strict verbatim transcription (cheap, good quality images only)
    text_mini = _ocr_strict_verbatim(image_bytes, content_type, model="gpt-4o-mini")

    if not text_mini:
        logger.warning("[OCR] gpt-4o-mini returned empty - escalating to gpt-4o")
        text_4o = _ocr_strict_verbatim(image_bytes, content_type, model="gpt-4o")
        return text_4o or "", "low"

    # Pass 2: Verification - check for high-risk OCR errors
    risk_detected, risk_reason = _verify_ocr_safety(text_mini)

    if risk_detected:
        logger.warning("[OCR] Pass 2: Risk detected (%s) - escalating to gpt-4o", risk_reason)
        text_4o = _ocr_strict_verbatim(image_bytes, content_type, model="gpt-4o")
        if text_4o:
            logger.info("[OCR] gpt-4o escalation successful")
            return text_4o, "medium"
        else:
            logger.warning("[OCR] gpt-4o escalation failed - using gpt-4o-mini result (low confidence)")
            return text_mini, "low"

    return text_mini, "high"
def _ocr_strict_verbatim(image_bytes: bytes, content_type: str, model: str) -> str:
    """
    OCR with strict verbatim transcription prompt.
    No interpretation, no correction, no medical inference.
    """
    try:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Είσαι ένα OCR σύστημα. Αντιγράφεις κείμενο από εικόνες ΑΚΡΙΒΩΣ όπως εμφανίζεται. "
                        "ΔΕΝ ερμηνεύεις. ΔΕΝ διορθώνεις. ΔΕΝ συμπεραίνεις. ΔΕΝ αλλάζεις ιατρικούς όρους. "
                        "Αν κάτι δεν διαβάζεται, γράφεις [ΑΔΥΝΑΤΗ ΑΝΑΓΝΩΣΗ]."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Αντέγραψε ΑΚΡΙΒΩΣ όλο το κείμενο από αυτή την εικόνα ιατρικής εξέτασης.\n\n"
                                "ΚΑΝΟΝΕΣ (ΑΥΣΤΗΡΩΣ ΥΠΟΧΡΕΩΤΙΚΟΙ):\n"
                                "1. Αντέγραψε κάθε λέξη ΑΚΡΙΒΩΣ όπως εμφανίζεται — χωρίς καμία αλλαγή\n"
                                "2. ΜΗΝ μεταφράζεις, ΜΗΝ ερμηνεύεις, ΜΗΝ αλλάζεις ιατρικές λέξεις\n"
                                "3. Διατήρησε την αρχική ορθογραφία ακόμα και αν φαίνεται λανθασμένη\n"
                                "4. Περίλαβε: ονόματα, ημερομηνίες, τιμές, μονάδες, σχόλια, υπογραφές\n"
                                "5. Αν κάτι δεν διαβάζεται καθαρά, γράψε [ΑΔΥΝΑΤΗ ΑΝΑΓΝΩΣΗ]\n"
                                "6. Επέστρεψε ΜΟΝΟ το κείμενο — χωρίς επεξηγήσεις ή σχόλια\n\n"
                                "ΠΑΡΑΔΕΙΓΜΑΤΑ ΣΩΣΤΗΣ ΑΝΤΙΓΡΑΦΗΣ:\n"
                                "- 'Ανευ λίθων' → 'Ανευ λίθων' (ΟΧΙ 'Απειλούνται' ή 'Άνευ λίθων')\n"
                                "- 'Σπληνεκτομή' → 'Σπληνεκτομή' (ΟΧΙ 'Σπληνική' ή 'Σπληνεκτομή')\n"
                                "- 'ΧΟΛΗΔΟΧΟΣ ΚΥΣΤΗ' → 'ΧΟΛΗΔΟΧΟΣ ΚΥΣΤΗ' (ΟΧΙ 'ΧΟΛΑΔΟΣΟΣ' ή 'ΧΟΛΑΔΟΣ')\n"
                                "- 'ηχοδομή' → 'ηχοδομή' (ΟΧΙ 'εκδόμη' ή 'ηχοδομή' ή 'παχέως')\n"
                                "- 'Χοληδόχος πόρος' → 'Χοληδόχος πόρος' (ΟΧΙ 'Χολήθος πόρος')\n"
                                "- 'υψή' → 'υψή' (ΟΧΙ 'υψι' ή 'ηπατικής')\n"
                                "- Αν γράφει 'Χωρίς παθολογικά ευρήματα' → γράψε ακριβώς αυτό\n\n"
                                "ΚΡΙΣΙΜΟ: Οι ιατρικές λέξεις που αρχίζουν με 'ΧΟΛΗΔ-', 'ηχοδ-', 'Σπληνεκτ-' \n"
                                "είναι ΠΟΛΥ ΣΥΓΚΕΚΡΙΜΕΝΕΣ. Αντέγραψέ τες γράμμα-γράμμα."
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
        logger.error("[OCR] %s Vision error: %s", model, e)
        return ""


def _verify_ocr_safety(text: str) -> tuple[bool, str]:
    """
    Verification pass: detect high-risk OCR errors in medical text.
    Returns (risk_detected: bool, reason: str)

    Checks for:
    1. Suspicious substitutions (e.g. "Απειλούνται" near gallbladder context)
    2. Missing high-risk terms that should appear in typical ultrasound reports
    3. Presence of [ΑΔΥΝΑΤΗ ΑΝΑΓΝΩΣΗ] markers (indicates low confidence)
    """
    text_lower = text.lower()

    # Check 1: Suspicious substitution patterns
    for suspicious_pattern, context_pattern in SUSPICIOUS_PATTERNS:
        if re.search(suspicious_pattern, text_lower):
            if context_pattern is None or re.search(context_pattern, text_lower):
                return True, f"suspicious_pattern:{suspicious_pattern}"

    # Check 2: Unreadable markers
    if "[αδυνατη αναγνωση]" in text_lower or "[αδύνατη αναγνωση]" in text_lower:
        return True, "unreadable_sections"

    # Check 3: Very short output for what appears to be a medical document
    # (less than 50 chars suggests OCR failure)
    if len(text.strip()) < 50:
        return True, "too_short"

    return False, ""


# ---------------------------------------------------------------------------
# PDF extraction (unchanged logic, now uses hybrid for scanned pages)
# ---------------------------------------------------------------------------

def _extract_pdf(file_data: bytes) -> tuple[str, str, str]:
    """
    Extract text from a PDF.
    1. Try PyMuPDF text extraction (text-based PDFs) → confidence "high"
    2. Fall back to hybrid OCR (scanned PDFs)
    Returns (raw_text, ocr_type, confidence)
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
        return "\n\n".join(text_pages), "pdf_text", "high"

    # Scanned PDF — hybrid OCR (max 5 pages)
    ocr_parts = []
    overall_confidence = "high"
    max_pages = min(5, len(doc))
    for page_num in range(max_pages):
        page = doc[page_num]
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        img_bytes = pix.tobytes("png")
        ocr_text, confidence = _ocr_image_hybrid(img_bytes, "image/png")
        if ocr_text:
            ocr_parts.append(f"--- Σελίδα {page_num + 1} ---\n{ocr_text}")
        if confidence == "low":
            overall_confidence = "low"
        elif confidence == "medium" and overall_confidence == "high":
            overall_confidence = "medium"

    if ocr_parts:
        return "\n\n".join(ocr_parts), "pdf_scanned", overall_confidence

    return "", "pdf_empty", "low"
