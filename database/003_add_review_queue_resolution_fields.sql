-- Autoanosis Exams — Migration 003
-- Adds resolved_by (admin uid) and resolution_note to aa_exam_review_queue.
-- Required by PATCH /exams/review-queue/<id>/resolve endpoint.
-- Safe to run on live database: uses ADD COLUMN IF NOT EXISTS (PostgreSQL 9.6+).

BEGIN;

ALTER TABLE aa_exam_review_queue
    ADD COLUMN IF NOT EXISTS resolved_by BIGINT,
    ADD COLUMN IF NOT EXISTS resolution_note TEXT;

COMMIT;
