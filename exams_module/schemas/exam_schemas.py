from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

class DocumentCreate(BaseModel):
    patient_id: int
    source_type: str = "upload"
    storage_url: Optional[str] = None
    original_filename: Optional[str] = None
    mime_type: Optional[str] = None
    sha256: str
    raw_text: str = Field(default="", description="Extracted machine/OCR text")
    ingestion_source: str = Field(default="mobile_upload", description="Origin: mobile_upload | web_upload | admin_upload")
    ocr_model_version: Optional[str] = None

class ProcessResponse(BaseModel):
    document_id: str
    status: str
    normalization_status: str
    review_required: bool
    report_ids: List[str]

class DuplicateResponse(BaseModel):
    duplicate: bool
    existing_document_id: str
    message: str

class ResultOut(BaseModel):
    display_name: str
    value_numeric: Optional[float] = None
    value_text: Optional[str] = None
    unit: Optional[str] = None
    reference_low: Optional[float] = None
    reference_high: Optional[float] = None
    reference_text: Optional[str] = None
    abnormal_flag: str
    trendable: bool
    clinical_group: Optional[str] = None

class ImpressionOut(BaseModel):
    section_type: str
    text: str
    severity_flag: str
    review_required: bool

class ReportOut(BaseModel):
    id: str
    patient_id: int
    exam_type: str
    exam_category: str
    normalization_status: str
    confidence_score: Optional[float] = None
    performed_at: Optional[str] = None
    lab_name: Optional[str] = None
    source_lineage: Dict[str, Any]
    results: List[ResultOut] = []
    impressions: List[ImpressionOut] = []

class PatientReportsOut(BaseModel):
    patient_id: int
    reports: List[ReportOut]
