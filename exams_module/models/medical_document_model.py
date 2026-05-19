"""
Autoanosis — Medical Document Archive Model
Stores arbitrary medical documents (PDFs, images, articles, referrals, etc.)
WITHOUT OCR processing. Pure file storage with metadata.
"""
import uuid
from sqlalchemy import Column, String, Text, DateTime, BigInteger, Integer
from sqlalchemy.sql import func

from exams_module.db.base import Base


def _uuid():
    return str(uuid.uuid4())


class MedicalDocument(Base):
    """
    A raw medical document uploaded by the patient for archiving purposes.
    No OCR, no normalization — just storage + metadata.
    """
    __tablename__ = "aa_medical_documents"

    id = Column(String, primary_key=True, default=_uuid)
    patient_id = Column(BigInteger, nullable=False, index=True)

    # File metadata
    original_filename = Column(Text, nullable=False)
    mime_type = Column(String(128), nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    sha256 = Column(String(64), nullable=False, index=True)

    # Storage — base64 content stored in DB for simplicity (small files)
    # For large files this could be a storage URL
    file_data = Column(Text, nullable=True)  # base64-encoded file content

    # Extracted text content for AI context (from PDF text layer or OCR)
    extracted_text = Column(Text, nullable=True)

    # User-provided metadata
    document_title = Column(Text, nullable=True)
    document_category = Column(String(64), nullable=True, default="general")
    # Categories: general, lab_result, imaging, referral, prescription, article, other
    document_date = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)

    # System metadata
    uploaded_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
