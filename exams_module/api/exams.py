from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from exams_module.db.database import get_db
from exams_module.schemas.exam_schemas import DocumentCreate, ProcessResponse, PatientReportsOut, ReportOut, ResultOut, ImpressionOut
from exams_module.models.exam_models import ExamDocument, ExamReport, ExamReviewQueue
from exams_module.services.exam_service import create_document, process_document

router = APIRouter(prefix="/exams", tags=["exams"])

@router.post("/documents")
def create_exam_document(payload: DocumentCreate, db: Session = Depends(get_db)):
    doc = create_document(db, payload)
    db.commit()
    db.refresh(doc)
    return {"document_id": doc.id, "status": doc.status, "classifier_label": doc.classifier_label}

@router.post("/documents/{document_id}/process", response_model=ProcessResponse)
def process_exam_document(document_id: str, db: Session = Depends(get_db)):
    doc = db.query(ExamDocument).filter(ExamDocument.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    result = process_document(db, doc)
    db.commit()
    return result

@router.get("/patients/{patient_id}/reports", response_model=PatientReportsOut)
def get_patient_reports(patient_id: int, db: Session = Depends(get_db)):
    reports = db.query(ExamReport).options(joinedload(ExamReport.results), joinedload(ExamReport.impressions)).filter(
        ExamReport.patient_id == patient_id,
        ExamReport.status == "active",
        ExamReport.normalization_status.in_(["auto_verified", "manually_corrected", "published"])
    ).all()
    out = []
    for r in reports:
        out.append(ReportOut(
            id=r.id,
            patient_id=r.patient_id,
            exam_type=r.exam_type,
            exam_category=r.exam_category,
            normalization_status=r.normalization_status,
            confidence_score=float(r.confidence_score) if r.confidence_score is not None else None,
            performed_at=r.performed_at.isoformat() if r.performed_at else None,
            lab_name=r.lab_name,
            source_lineage=r.source_lineage or {},
            results=[ResultOut(
                display_name=x.display_name,
                value_numeric=float(x.value_numeric) if x.value_numeric is not None else None,
                value_text=x.value_text,
                unit=x.unit,
                reference_low=float(x.reference_low) if x.reference_low is not None else None,
                reference_high=float(x.reference_high) if x.reference_high is not None else None,
                reference_text=x.reference_text,
                abnormal_flag=x.abnormal_flag,
                trendable=x.trendable,
                clinical_group=x.clinical_group,
            ) for x in r.results],
            impressions=[ImpressionOut(
                section_type=i.section_type,
                text=i.text,
                severity_flag=i.severity_flag,
                review_required=i.review_required,
            ) for i in r.impressions],
        ))
    return PatientReportsOut(patient_id=patient_id, reports=out)

@router.get("/review-queue")
def get_review_queue(db: Session = Depends(get_db)):
    items = db.query(ExamReviewQueue).filter(ExamReviewQueue.resolution_status == "open").all()
    return [{"id": x.id, "document_id": x.document_id, "patient_id": x.patient_id, "reason_code": x.reason_code, "reason_text": x.reason_text} for x in items]
