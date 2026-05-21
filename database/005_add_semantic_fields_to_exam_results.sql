-- Migration 005: Add semantic interpretation fields to aa_exam_results
-- These fields support the semantic evaluation layer (v3.1) introduced in normalizer_ai.py
-- They are all nullable/have defaults so existing rows are unaffected.

ALTER TABLE aa_exam_results
    ADD COLUMN IF NOT EXISTS metric_kind VARCHAR(64) DEFAULT 'numeric_lab',
    ADD COLUMN IF NOT EXISTS semantic_direction VARCHAR(64) DEFAULT 'bidirectional',
    ADD COLUMN IF NOT EXISTS evaluation_status VARCHAR(32) DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS review_reason TEXT DEFAULT '',
    ADD COLUMN IF NOT EXISTS disclaimer TEXT DEFAULT '';

-- Index on evaluation_status for fast filtering (e.g. "show all abnormal results")
CREATE INDEX IF NOT EXISTS idx_exam_results_evaluation_status
    ON aa_exam_results (evaluation_status);

-- Index on metric_kind for grouping (e.g. "show only CGM metrics")
CREATE INDEX IF NOT EXISTS idx_exam_results_metric_kind
    ON aa_exam_results (metric_kind);
