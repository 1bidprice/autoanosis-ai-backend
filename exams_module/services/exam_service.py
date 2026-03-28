from decimal import Decimal
from sqlalchemy.orm import Session
from exams_module.models.exam_models import ExamDocument, ExamReport, ExamResult, ExamImpression, ExamReviewQueue, ExamProcessingEvent
from exams_module.services.normalizer import normalize_document, classify_document, detect_garbage_text

def log_event(db: Session, document_id: str, event_type: str, payload=None):
    db.add(ExamProcessingEvent(document_id=document_id, event_type=event_type, event_payload=payload or {}))

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
        classifier_confidence=Decimal(str(classifier_confidence)),
    )
    db.add(doc)
    db.flush()
    log_event(db, doc.id, "received", {"classifier_label": classifier_label})
    return doc

def _review(db: Session, doc, code, reason):
    db.add(ExamReviewQueue(document_id=doc.id, patient_id=doc.patient_id, reason_code=code, reason_text=reason))

def process_document(db: Session, doc):
    text = doc.ocr_text or ""
    garbage, reason = detect_garbage_text(text)
    if garbage:
        doc.status = "rejected"
        doc.review_reason = reason
        log_event(db, doc.id, "rejected", {"reason": reason})
        _review(db, doc, reason, "Document rejected before normalization")
        return {"document_id": doc.id, "status": doc.status, "normalization_status": "rejected", "review_required": True, "report_ids": []}

    parsed = normalize_document(text)
    if not parsed:
        doc.status = "needs_review"
        doc.review_reason = "normalizer_no_valid_report"
        log_event(db, doc.id, "needs_review", {"reason": "normalizer_no_valid_report"})
        _review(db, doc, "normalizer_no_valid_report", "No valid structured report could be produced")
        return {"document_id": doc.id, "status": doc.status, "normalization_status": "needs_review", "review_required": True, "report_ids": []}

    report = ExamReport(
        patient_id=doc.patient_id,
        document_id=doc.id,
        exam_type=parsed.exam_type,
        exam_category=parsed.exam_category,
        normalization_status=parsed.normalization_status,
        confidence_score=Decimal(str(parsed.confidence_score)),
        source_lineage=parsed.source_lineage,
        parser_version=parsed.source_lineage.get("parser"),
        status="active",
    )
    db.add(report)
    db.flush()

    for r in parsed.results:
        db.add(ExamResult(
            report_id=report.id,
            display_name=r.display_name,
            value_numeric=Decimal(str(r.value_numeric)) if r.value_numeric is not None else None,
            value_text=r.value_text,
            unit=r.unit,
            reference_low=Decimal(str(r.reference_low)) if r.reference_low is not None else None,
            reference_high=Decimal(str(r.reference_high)) if r.reference_high is not None else None,
            reference_text=r.reference_text,
            abnormal_flag=r.abnormal_flag,
            trendable=r.trendable,
            clinical_group=r.clinical_group,
            parser_confidence=Decimal(str(r.parser_confidence)),
        ))

    for i in parsed.impressions:
        db.add(ExamImpression(
            report_id=report.id,
            section_type=i.section_type,
            text=i.text,
            severity_flag=i.severity_flag,
            review_required=i.review_required,
        ))

    doc.status = "normalized" if parsed.normalization_status == "auto_verified" else "needs_review"
    log_event(db, doc.id, "normalized", {"report_id": report.id, "normalization_status": parsed.normalization_status})
    if parsed.normalization_status != "auto_verified":
        _review(db, doc, "low_confidence_or_narrative", "Report requires human review before publishing")

    return {"document_id": doc.id, "status": doc.status, "normalization_status": parsed.normalization_status, "review_required": parsed.normalization_status != "auto_verified", "report_ids": [report.id]}
