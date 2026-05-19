-- Migration 002: Medical Document Archive
-- Creates the aa_medical_documents table for storing arbitrary medical documents
-- without OCR processing (PDFs, images, articles, referrals, etc.)
-- Run once on the production PostgreSQL database.

CREATE TABLE IF NOT EXISTS aa_medical_documents (
    id                  VARCHAR(36) PRIMARY KEY,
    patient_id          BIGINT NOT NULL,
    original_filename   TEXT NOT NULL,
    mime_type           VARCHAR(128),
    file_size_bytes     INTEGER,
    sha256              VARCHAR(64) NOT NULL,
    file_data           TEXT,           -- base64-encoded file content
    document_title      TEXT,
    document_category   VARCHAR(64) DEFAULT 'general',
    document_date       TIMESTAMP,
    notes               TEXT,
    uploaded_at         TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_aa_medical_documents_patient_id ON aa_medical_documents(patient_id);
CREATE INDEX IF NOT EXISTS idx_aa_medical_documents_sha256 ON aa_medical_documents(sha256);
CREATE INDEX IF NOT EXISTS idx_aa_medical_documents_category ON aa_medical_documents(document_category);
