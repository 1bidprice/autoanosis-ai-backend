-- Autoanosis Exams — Migration 002
-- Adds ingestion_source and ocr_model_version metadata columns to aa_exam_documents.
-- Safe to run on live database: uses ADD COLUMN IF NOT EXISTS (PostgreSQL 9.6+).
-- Legacy rows with status='received' remain valid; application code treats 'received' == 'uploaded'.

BEGIN;

ALTER TABLE aa_exam_documents
    ADD COLUMN IF NOT EXISTS ingestion_source VARCHAR(32) NOT NULL DEFAULT 'mobile_upload',
    ADD COLUMN IF NOT EXISTS ocr_model_version VARCHAR(64);

COMMIT;
