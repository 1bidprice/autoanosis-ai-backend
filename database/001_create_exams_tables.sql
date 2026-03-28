BEGIN;
CREATE TABLE IF NOT EXISTS aa_exam_documents (
    id UUID PRIMARY KEY,
    patient_id BIGINT NOT NULL,
    source_type VARCHAR(32) NOT NULL,
    storage_url TEXT,
    original_filename TEXT,
    mime_type VARCHAR(128),
    sha256 VARCHAR(64) NOT NULL,
    uploaded_at TIMESTAMP NOT NULL DEFAULT NOW(),
    status VARCHAR(32) NOT NULL DEFAULT 'received',
    ocr_text TEXT,
    raw_extraction_json JSONB,
    parsing_errors JSONB,
    ingestion_version VARCHAR(32) NOT NULL DEFAULT 'exams-master-package',
    classifier_label VARCHAR(64),
    classifier_confidence NUMERIC(5,4),
    is_duplicate BOOLEAN NOT NULL DEFAULT FALSE,
    review_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_aa_exam_documents_patient_id ON aa_exam_documents(patient_id);
CREATE INDEX IF NOT EXISTS idx_aa_exam_documents_sha256 ON aa_exam_documents(sha256);

CREATE TABLE IF NOT EXISTS aa_exam_reports (
    id UUID PRIMARY KEY,
    patient_id BIGINT NOT NULL,
    document_id UUID NOT NULL REFERENCES aa_exam_documents(id) ON DELETE CASCADE,
    exam_type VARCHAR(64) NOT NULL,
    exam_category VARCHAR(32) NOT NULL,
    performed_at TIMESTAMP,
    reported_at TIMESTAMP,
    lab_name TEXT,
    ordering_doctor TEXT,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    normalization_status VARCHAR(32) NOT NULL DEFAULT 'needs_review',
    confidence_score NUMERIC(5,4),
    schema_version VARCHAR(16) NOT NULL DEFAULT '1.0',
    normalizer_version VARCHAR(32) NOT NULL DEFAULT 'exams-master-package',
    parser_version VARCHAR(32),
    source_lineage JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_aa_exam_reports_patient_id ON aa_exam_reports(patient_id);
CREATE INDEX IF NOT EXISTS idx_aa_exam_reports_document_id ON aa_exam_reports(document_id);

CREATE TABLE IF NOT EXISTS aa_exam_results (
    id UUID PRIMARY KEY,
    report_id UUID NOT NULL REFERENCES aa_exam_reports(id) ON DELETE CASCADE,
    code_system VARCHAR(32) NOT NULL DEFAULT 'local',
    code VARCHAR(128),
    display_name TEXT NOT NULL,
    value_numeric NUMERIC,
    value_text TEXT,
    value_boolean BOOLEAN,
    unit VARCHAR(32),
    reference_low NUMERIC,
    reference_high NUMERIC,
    reference_text TEXT,
    abnormal_flag VARCHAR(32) NOT NULL DEFAULT 'unknown',
    trendable BOOLEAN NOT NULL DEFAULT FALSE,
    clinical_group VARCHAR(64),
    measurement_at TIMESTAMP,
    parser_confidence NUMERIC(5,4)
);

CREATE TABLE IF NOT EXISTS aa_exam_impressions (
    id UUID PRIMARY KEY,
    report_id UUID NOT NULL REFERENCES aa_exam_reports(id) ON DELETE CASCADE,
    section_type VARCHAR(32) NOT NULL,
    text TEXT NOT NULL,
    severity_flag VARCHAR(32) NOT NULL DEFAULT 'unknown',
    review_required BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS aa_exam_review_queue (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES aa_exam_documents(id) ON DELETE CASCADE,
    patient_id BIGINT NOT NULL,
    reason_code VARCHAR(64) NOT NULL,
    reason_text TEXT NOT NULL,
    resolution_status VARCHAR(32) NOT NULL DEFAULT 'open',
    assigned_to TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS aa_exam_processing_events (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES aa_exam_documents(id) ON DELETE CASCADE,
    event_type VARCHAR(64) NOT NULL,
    event_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
COMMIT;
