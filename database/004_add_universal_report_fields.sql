-- Migration 004: Universal Report Fields
-- Adds narrative/imaging support and edit audit trail to aa_exam_reports.
-- Safe to run multiple times (IF NOT EXISTS guards).
-- Run on production Render PostgreSQL before deploying the updated app.py.

-- Human-readable display name (e.g. "Υπερηχογράφημα Άνω/Κάτω Κοιλίας")
ALTER TABLE aa_exam_reports
    ADD COLUMN IF NOT EXISTS display_name TEXT;

-- Narrative text extracted from imaging/ultrasound/MRI/CT reports
ALTER TABLE aa_exam_reports
    ADD COLUMN IF NOT EXISTS narrative_text TEXT;

-- AI-generated or manually edited summary (max ~500 chars)
ALTER TABLE aa_exam_reports
    ADD COLUMN IF NOT EXISTS summary TEXT;

-- Structured findings as JSONB list: [{"section": str, "text": str, "severity": str, "review_required": bool}]
ALTER TABLE aa_exam_reports
    ADD COLUMN IF NOT EXISTS findings_json JSONB;

-- Field-level correction audit trail: {"field_name": {"original": ..., "corrected": ..., "edited_at": ..., "edited_by": ...}}
ALTER TABLE aa_exam_reports
    ADD COLUMN IF NOT EXISTS corrected_fields JSONB;

-- UID of user/doctor/admin who last edited the report
ALTER TABLE aa_exam_reports
    ADD COLUMN IF NOT EXISTS edited_by BIGINT;

-- Timestamp of last edit
ALTER TABLE aa_exam_reports
    ADD COLUMN IF NOT EXISTS edited_at TIMESTAMP;

-- Index for narrative reports (imaging category queries)
CREATE INDEX IF NOT EXISTS idx_exam_reports_exam_category
    ON aa_exam_reports (exam_category);

-- Index for edited reports (admin review)
CREATE INDEX IF NOT EXISTS idx_exam_reports_edited_by
    ON aa_exam_reports (edited_by)
    WHERE edited_by IS NOT NULL;
