import uuid
from sqlalchemy import Column, String, Text, Boolean, DateTime, ForeignKey, Numeric, BigInteger
from sqlalchemy.sql import func
import os
from sqlalchemy.orm import relationship
from exams_module.db.base import Base

# Use JSONB on PostgreSQL, plain JSON on SQLite
_DB_URL = os.environ.get("DATABASE_URL", "sqlite://")
if _DB_URL.startswith("postgresql"):
    from sqlalchemy.dialects.postgresql import JSONB as JSON
else:
    from sqlalchemy import JSON

def _uuid():
    return str(uuid.uuid4())

class ExamDocument(Base):
    __tablename__ = "aa_exam_documents"
    id = Column(String, primary_key=True, default=_uuid)
    patient_id = Column(BigInteger, nullable=False, index=True)
    source_type = Column(String(32), nullable=False)
    storage_url = Column(Text)
    original_filename = Column(Text)
    mime_type = Column(String(128))
    sha256 = Column(String(64), nullable=False, index=True)
    uploaded_at = Column(DateTime, server_default=func.now(), nullable=False)
    status = Column(String(32), nullable=False, default="uploaded")
    ocr_text = Column(Text)
    raw_extraction_json = Column(JSON)
    parsing_errors = Column(JSON)
    ingestion_version = Column(String(32), nullable=False, default="exams-master-package")
    classifier_label = Column(String(64))
    classifier_confidence = Column(Numeric(5,4))
    document_type = Column(String(64))
    document_subtype = Column(String(64))
    display_title = Column(Text)
    semantic_status = Column(String(32))
    structured_payload = Column(JSON)
    assistant_summary = Column(Text)
    is_duplicate = Column(Boolean, nullable=False, default=False)
    review_reason = Column(Text)
    ingestion_source = Column(String(32), nullable=False, default="mobile_upload")
    ocr_model_version = Column(String(64))
    reports = relationship("ExamReport", back_populates="document", cascade="all, delete-orphan")
    events = relationship("ExamProcessingEvent", back_populates="document", cascade="all, delete-orphan")

class ExamReport(Base):
    __tablename__ = "aa_exam_reports"
    id = Column(String, primary_key=True, default=_uuid)
    patient_id = Column(BigInteger, nullable=False, index=True)
    document_id = Column(String, ForeignKey("aa_exam_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    exam_type = Column(String(64), nullable=False)
    exam_category = Column(String(32), nullable=False)
    # Human-readable display name (e.g. "Υπερηχογράφημα Ανω/Κάτω Κοιλίας")
    display_name = Column(Text)
    performed_at = Column(DateTime)
    reported_at = Column(DateTime)
    lab_name = Column(Text)
    ordering_doctor = Column(Text)
    status = Column(String(32), nullable=False, default="active")
    normalization_status = Column(String(32), nullable=False, default="needs_review")
    confidence_score = Column(Numeric(5,4))
    schema_version = Column(String(16), nullable=False, default="1.0")
    normalizer_version = Column(String(32), nullable=False, default="exams-master-package")
    parser_version = Column(String(32))
    source_lineage = Column(JSON, nullable=False, default=dict)
    # ── Universal narrative / imaging fields ──
    # Extracted narrative text from imaging/ultrasound/MRI/CT reports
    narrative_text = Column(Text)
    # AI-generated or manually edited summary
    summary = Column(Text)
    # Structured findings as JSON list [{"section": str, "text": str, "severity": str}]
    findings_json = Column(JSON)
    # ── Edit / correction audit trail ──
    # Stores field-level corrections: {"field_name": {"original": ..., "corrected": ..., "edited_at": ...}}
    corrected_fields = Column(JSON)
    edited_by = Column(BigInteger)   # uid of user/doctor/admin who last edited
    edited_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), nullable=False)
    # Report-level guidance message (e.g. AGP-only CGM, no extractable numeric values)
    report_review_reason = Column(Text, default='')
    structured_payload = Column(JSON)
    terminology_mappings = Column(JSON)
    document = relationship("ExamDocument", back_populates="reports")
    results = relationship("ExamResult", back_populates="report", cascade="all, delete-orphan")
    impressions = relationship("ExamImpression", back_populates="report", cascade="all, delete-orphan")

class ExamResult(Base):
    __tablename__ = "aa_exam_results"
    id = Column(String, primary_key=True, default=_uuid)
    report_id = Column(String, ForeignKey("aa_exam_reports.id", ondelete="CASCADE"), nullable=False, index=True)
    code_system = Column(String(32), nullable=False, default="local")
    code = Column(String(128))
    display_name = Column(Text, nullable=False)
    value_numeric = Column(Numeric)
    value_text = Column(Text)
    value_boolean = Column(Boolean)
    unit = Column(String(32))
    reference_low = Column(Numeric)
    reference_high = Column(Numeric)
    reference_text = Column(Text)
    abnormal_flag = Column(String(32), nullable=False, default="unknown")
    trendable = Column(Boolean, nullable=False, default=False)
    clinical_group = Column(String(64))
    measurement_at = Column(DateTime)
    parser_confidence = Column(Numeric(5,4))
    # Semantic interpretation fields (v3.1)
    metric_kind = Column(String(64), default='numeric_lab')
    semantic_direction = Column(String(64), default='bidirectional')
    evaluation_status = Column(String(32), default='unknown')
    review_reason = Column(Text, default='')
    disclaimer = Column(Text, default='')
    report = relationship("ExamReport", back_populates="results")

class ExamImpression(Base):
    __tablename__ = "aa_exam_impressions"
    id = Column(String, primary_key=True, default=_uuid)
    report_id = Column(String, ForeignKey("aa_exam_reports.id", ondelete="CASCADE"), nullable=False, index=True)
    section_type = Column(String(32), nullable=False)
    text = Column(Text, nullable=False)
    severity_flag = Column(String(32), nullable=False, default="unknown")
    review_required = Column(Boolean, nullable=False, default=False)
    report = relationship("ExamReport", back_populates="impressions")

class ExamReviewQueue(Base):
    __tablename__ = "aa_exam_review_queue"
    id = Column(String, primary_key=True, default=_uuid)
    document_id = Column(String, ForeignKey("aa_exam_documents.id", ondelete="CASCADE"), nullable=False)
    patient_id = Column(BigInteger, nullable=False)
    reason_code = Column(String(64), nullable=False)
    reason_text = Column(Text, nullable=False)
    resolution_status = Column(String(32), nullable=False, default="open")
    assigned_to = Column(Text)
    resolved_by = Column(BigInteger)          # uid of admin who resolved
    resolution_note = Column(Text)            # optional admin note on resolution
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    resolved_at = Column(DateTime)

class ExamProcessingEvent(Base):
    __tablename__ = "aa_exam_processing_events"
    id = Column(String, primary_key=True, default=_uuid)
    document_id = Column(String, ForeignKey("aa_exam_documents.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String(64), nullable=False)
    event_payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    document = relationship("ExamDocument", back_populates="events")
