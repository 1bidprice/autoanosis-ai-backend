"""
Autoanosis Exams — Exam Service v3.0.0
=======================================
Updated to use the AI-powered universal normalizer (normalizer_ai.py).
Populates all report metadata fields: performed_at, lab_name, ordering_doctor.
Stores validation_warnings and ocr_snippet in source_lineage for traceability.
"""

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from sqlalchemy.orm import Session
from exams_module.models.exam_models import (
    ExamDocument, ExamReport, ExamResult, ExamImpression,
    ExamReviewQueue, ExamProcessingEvent,
)

# Import the AI normalizer as primary
from exams_module.services.normalizer_ai import (
    normalize_document,
    classify_document,
    detect_garbage_text,
)

logger = logging.getLogger("exams.service")


def _safe_decimal(val) -> Decimal | None:
    """Safely convert a value to Decimal for database storage."""
    if val is None:
        return None
    try:
        return Decimal(str(val))
    except (InvalidOperation, ValueError, TypeError):
        return None


def log_event(db: Session, document_id: str, event_type: str, payload=None):
    db.add(ExamProcessingEvent(
        document_id=document_id,
        event_type=event_type,
        event_payload=payload or {},
    ))


def create_document(db: Session, payload):
    classifier_label, classifier_confidence = classify_document(payload.raw_text)
    doc = ExamDocument(
        patient_id=payload.patient_id,
        source_type=payload.source_type,
        storage_url=payload.storage_url,
        original_filename=payload.original_filename,
        mime_type=payload.mime_type,
        sha256=payload.sha256,
        ocr_text=payload.raw_text,
        raw_extraction_json={"raw_text_preview": payload.raw_text[:500]},
        classifier_label=classifier_label,
        classifier_confidence=_safe_decimal(classifier_confidence),
    )
    db.add(doc)
    db.flush()
    log_event(db, doc.id, "received", {"classifier_label": classifier_label})
    return doc


def _review(db: Session, doc, code, reason):
    db.add(ExamReviewQueue(
        document_id=doc.id,
        patient_id=doc.patient_id,
        reason_code=code,
        reason_text=reason,
    ))


def _parse_date(date_str: str | None) -> datetime | None:
    """Parse a date string (YYYY-MM-DD or DD/MM/YYYY) into a datetime object."""
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


def process_document(db: Session, doc):
    """
    Process a document through the AI normalizer pipeline.
    Steps: garbage check → AI extraction → post-validation → store results.
    """
    text = doc.ocr_text or ""

    # Step 1: Garbage text detection
    garbage, reason = detect_garbage_text(text)
    if garbage:
        doc.status = "rejected"
        doc.review_reason = reason
        log_event(db, doc.id, "rejected", {"reason": reason})
        _review(db, doc, reason, "Document rejected before normalization")
        return {
            "document_id": doc.id,
            "status": doc.status,
            "normalization_status": "rejected",
            "review_required": True,
            "report_ids": [],
        }

    # Step 2: AI Normalization
    parsed = normalize_document(text)
    if not parsed:
        doc.status = "needs_review"
        doc.review_reason = "normalizer_no_valid_report"
        log_event(db, doc.id, "needs_review", {"reason": "normalizer_no_valid_report"})
        _review(db, doc, "normalizer_no_valid_report", "No valid structured report could be produced")
        return {
            "document_id": doc.id,
            "status": doc.status,
            "normalization_status": "needs_review",
            "review_required": True,
            "report_ids": [],
        }

    # Step 3: Create ExamReport with full metadata
    report = ExamReport(
        patient_id=doc.patient_id,
        document_id=doc.id,
        exam_type=parsed.exam_type,
        exam_category=parsed.exam_category,
        normalization_status=parsed.normalization_status,
        confidence_score=_safe_decimal(parsed.confidence_score),
        source_lineage=parsed.source_lineage,
        parser_version=parsed.source_lineage.get("parser", "unknown"),
        performed_at=_parse_date(getattr(parsed, "performed_at", None)),
        lab_name=getattr(parsed, "lab_name", None),
        ordering_doctor=getattr(parsed, "ordering_doctor", None),
        status="active",
    )
    db.add(report)
    db.flush()

    # Step 4: Store all validated results
    for r in parsed.results:
        # Build per-result source lineage including OCR snippet and warnings
        result_meta = {}
        if hasattr(r, "ocr_snippet") and r.ocr_snippet:
            result_meta["ocr_snippet"] = r.ocr_snippet
        if hasattr(r, "validation_warnings") and r.validation_warnings:
            result_meta["validation_warnings"] = r.validation_warnings

        db.add(ExamResult(
            report_id=report.id,
            display_name=r.display_name,
            value_numeric=_safe_decimal(r.value_numeric),
            value_text=r.value_text,
            unit=r.unit,
            reference_low=_safe_decimal(r.reference_low),
            reference_high=_safe_decimal(r.reference_high),
            reference_text=r.reference_text,
            abnormal_flag=r.abnormal_flag,
            trendable=r.trendable,
            clinical_group=r.clinical_group,
            parser_confidence=_safe_decimal(r.parser_confidence),
        ))

    # Step 5: Store impressions
    for i in parsed.impressions:
        db.add(ExamImpression(
            report_id=report.id,
            section_type=i.section_type,
            text=i.text,
            severity_flag=i.severity_flag,
            review_required=i.review_required,
        ))

    # Step 6: Update document status
    doc.status = "normalized" if parsed.normalization_status == "auto_verified" else "needs_review"

    # Step 7: Log processing event with validation summary
    event_payload = {
        "report_id": report.id,
        "normalization_status": parsed.normalization_status,
        "confidence_score": float(parsed.confidence_score),
        "results_count": len(parsed.results),
    }
    if hasattr(parsed, "validation_summary") and parsed.validation_summary:
        event_payload["validation_summary"] = parsed.validation_summary

    log_event(db, doc.id, "normalized", event_payload)

    # Step 8: Create review queue entry if needed
    if parsed.normalization_status != "auto_verified":
        review_reason_parts = []
        vs = getattr(parsed, "validation_summary", {})
        if vs.get("missing_units", 0) > 0:
            review_reason_parts.append(f"{vs['missing_units']} results missing units")
        if vs.get("missing_references", 0) > 0:
            review_reason_parts.append(f"{vs['missing_references']} results missing reference ranges")
        if vs.get("impossible_values", 0) > 0:
            review_reason_parts.append(f"{vs['impossible_values']} impossible values detected")
        if vs.get("flag_corrections", 0) > 0:
            review_reason_parts.append(f"{vs['flag_corrections']} abnormal flags corrected")

        reason_text = "; ".join(review_reason_parts) if review_reason_parts else "Report requires human review"
        _review(db, doc, "low_confidence_or_validation_issues", reason_text)

    return {
        "document_id": doc.id,
        "status": doc.status,
        "normalization_status": parsed.normalization_status,
        "confidence_score": float(parsed.confidence_score),
        "review_required": parsed.normalization_status != "auto_verified",
        "report_ids": [report.id],
        "results_count": len(parsed.results),
        "validation_summary": getattr(parsed, "validation_summary", {}),
    }
