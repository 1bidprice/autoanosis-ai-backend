-- Medical Document Intelligence Layer — additive PostgreSQL migration
-- Mirrors app.py startup migration. Safe to run once or repeatedly.
BEGIN;

ALTER TABLE aa_exam_documents
    ADD COLUMN IF NOT EXISTS document_type VARCHAR(64),
    ADD COLUMN IF NOT EXISTS document_subtype VARCHAR(64),
    ADD COLUMN IF NOT EXISTS display_title TEXT,
    ADD COLUMN IF NOT EXISTS semantic_status VARCHAR(32),
    ADD COLUMN IF NOT EXISTS structured_payload JSONB,
    ADD COLUMN IF NOT EXISTS assistant_summary TEXT;

ALTER TABLE aa_exam_reports
    ADD COLUMN IF NOT EXISTS structured_payload JSONB,
    ADD COLUMN IF NOT EXISTS terminology_mappings JSONB;

CREATE INDEX IF NOT EXISTS ix_aa_exam_documents_patient_document_type_uploaded
    ON aa_exam_documents (patient_id, document_type, uploaded_at DESC);
CREATE INDEX IF NOT EXISTS ix_aa_exam_documents_semantic_status
    ON aa_exam_documents (semantic_status);

COMMIT;
