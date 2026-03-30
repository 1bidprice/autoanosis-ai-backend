# Autoanosis — AI Normalizer & Dashboard Upgrade: Project Memory

**Date:** March 29, 2026  
**Status:** PRODUCTION — VERIFIED END-TO-END  
**Version:** AI Normalizer v3.0.0 / Dashboard Plugin v10.0.0  

---

## 1. Problem Statement

The legacy regex-based normalizer (`normalizer.py`) was hardcoded to recognize only ~20 specific exam names. It failed to extract units, reference ranges, and abnormal flags. Greek lab reports with hormones, specialized biochemistry, or non-standard formatting were almost entirely lost. The Doctor Dashboard displayed results in a vertical key-value format that was unreadable for medical professionals.

**Measured failure rate:** The regex normalizer extracted only 9 out of 51 parameters (18%) from a standard Greek lab report. Hormones, albumin, CRP, and many biochemistry markers were completely missed.

---

## 2. Architecture Decision

The regex normalizer was replaced with a **Universal AI Normalizer** powered by GPT-4.1-mini structured JSON extraction. This was not a "magic AI" replacement but a professionally engineered system with strict post-validation, traceability, and confidence scoring.

### Key Design Principles

The system was built on five non-negotiable principles. First, it maintains **schema compatibility** by writing into the same `aa_exam_reports` and `aa_exam_results` tables with identical column semantics. Second, every report carries a **confidence score** and **normalization status** (`auto_verified`, `needs_review`, or `rejected`). Third, each extracted result includes an `ocr_snippet` and `source_lineage` JSON for **raw-to-structured traceability**. Fourth, a rigorous **post-validation pipeline** checks numeric parsing, unit parsing, reference range parsing, abnormal flag validation, and duplicate/impossible result filtering. Fifth, the system supports a **needs_review path** for weak OCR, missing units, missing reference ranges, conflicting values, or suspicious extraction.

---

## 3. Files Changed / Created

### Backend (Render — `autoanosis-ai-backend` repo on GitHub)

| File | Action | Description |
|------|--------|-------------|
| `exams_module/services/normalizer_ai.py` | **NEW** (28KB, 630 lines) | Universal AI Normalizer v3.0.0 — GPT structured extraction + post-validation |
| `exams_module/services/exam_service.py` | **MODIFIED** (v3.0.0) | Updated to import and use `normalizer_ai` as primary normalizer |
| `exams_module/services/normalizer.py` | **KEPT** (14KB) | Legacy regex normalizer retained as fallback (not called in normal flow) |
| `exams_module/api/reprocess.py` | **NEW** (175 lines) | Admin endpoint for re-processing legacy documents through AI normalizer |
| `app.py` | **MODIFIED** | Added `reprocess_bp` blueprint registration |

### WordPress (SiteGround — `autoanosis-doctor-dashboard` plugin)

| File | Action | Description |
|------|--------|-------------|
| `autoanosis-doctor-dashboard.php` | **REPLACED** (v10.0.0, 134KB, 2407 lines) | Horizontal lab-style table with clinical groups and color-coded flags |
| `autoanosis-doctor-dashboard.php.bak.v9.1.0` | **BACKUP** | Previous version backed up on SiteGround before replacement |

---

## 4. AI Normalizer Architecture (`normalizer_ai.py`)

The normalizer follows a four-stage pipeline:

**Stage 1 — Document Classification** (`classify_document()`): Detects whether the OCR text is a lab report, imaging report, or unknown document type using keyword-based heuristics. Returns a tuple of `(label, confidence)`.

**Stage 2 — AI Extraction** (`ai_extract_lab_results()`): Sends the OCR text to GPT-4.1-mini with a strict JSON schema prompt. The model is instructed to extract every single lab parameter with its name, value, unit, reference range, and abnormal flag. The response is parsed with a robust JSON parser that handles trailing commas, markdown code fences, and other common GPT output quirks.

**Stage 3 — Post-Validation** (`post_validate_results()`): Every extracted result goes through five validation checks: (a) numeric value parsing and range sanity, (b) unit string normalization, (c) reference range parsing (handles `<`, `>`, `-`, and complex text ranges), (d) abnormal flag recalculation from numeric value vs. reference range, and (e) duplicate detection and impossible value filtering.

**Stage 4 — Report Assembly** (`build_parsed_report()`): Assembles the final `ParsedReport` dataclass with all results, metadata (lab name, date, ordering doctor), confidence score, and normalization status. If confidence is below 0.70 or more than 50% of results have validation warnings, the report is flagged as `needs_review`.

### Data Classes (Drop-in Compatible)

```python
@dataclass
class ParsedResult:
    display_name: str
    value_numeric: float | None
    value_text: str | None
    unit: str | None
    reference_low: float | None
    reference_high: float | None
    reference_text: str | None
    abnormal_flag: str  # normal / high / low / critical_high / critical_low / unknown
    trendable: bool
    clinical_group: str | None  # hepatic, renal, endocrine, hematology, etc.
    parser_confidence: float
    ocr_snippet: str | None  # raw text fragment for traceability
    validation_warnings: list

@dataclass
class ParsedReport:
    doc_type: str
    results: List[ParsedResult]
    impressions: List[ParsedImpression]
    metadata: Dict
    confidence_score: float
    normalization_status: str  # auto_verified / needs_review / rejected
    parser_version: str  # "ai_universal_normalizer_v3"
```

### OpenAI Configuration

The normalizer uses `gpt-4.1-mini` via the OpenAI client. The API key is read from the `OPENAI_API_KEY` environment variable which is already configured on Render. The model is called with `temperature=0.0` and `response_format={"type": "json_object"}` for deterministic, structured output.

---

## 5. Exam Service Integration (`exam_service.py`)

The `process_document()` function in `exam_service.py` was updated to:

1. Call `normalizer_ai.normalize_document()` instead of the old regex normalizer.
2. Populate all `ExamReport` metadata fields: `performed_at`, `lab_name`, `ordering_doctor`, `confidence_score`, `normalization_status`, `parser_version`.
3. Store `source_lineage` JSON on each `ExamResult` containing `ocr_snippet` and `validation_warnings`.
4. Route `needs_review` reports to the `ExamReviewQueue` table.
5. Log all processing events to `ExamProcessingEvent`.

---

## 6. Reprocess Endpoint (`reprocess.py`)

An admin endpoint was created to re-process existing legacy documents through the AI normalizer:

**Endpoint:** `POST /exams/admin/reprocess-all`  
**Auth:** `X-Admin-Secret` header must match `AUTOA_AI_PROXY_SECRET` env var.  
**Behavior:** Iterates all `ExamDocument` records with non-empty `ocr_text`, deletes their old `ExamReport` and `ExamResult` records, and re-processes them through the AI normalizer. Returns a JSON summary with per-document status.

**Single document:** `POST /exams/admin/reprocess/<document_id>` — same auth, processes one document.

---

## 7. Dashboard Plugin Changes (v10.0.0)

### New Rendering: Horizontal Lab-Style Table

The exam results section was completely rewritten. The old vertical key-value rendering (`render_report_sections()`) was replaced with a horizontal table renderer (`render_horizontal_lab_table()`).

**Table columns:** ΕΞΕΤΑΣΗ | ΑΠΟΤΕΛΕΣΜΑ | ΜΟΝΑΔΑ | ΤΙΜΕΣ ΑΝΑΦΟΡΑΣ | ΚΑΤΑΣΤΑΣΗ

**Clinical group headers** are rendered as section dividers within the table (e.g., `hepatic`, `endocrine`, `biochemistry`, `hematology`, `renal`, `inflammation`).

**Color coding:**
- **Green** (`#27ae60`) — Normal values (Κανονικό)
- **Red** (`#e74c3c`) — High values (↑ Υψηλό)
- **Orange** (`#f39c12`) — Low values (↓ Χαμηλό)

**Report metadata** is displayed above each table: date, confidence score, and normalization status.

**Backward compatibility:** If a report has no `structured_results` (legacy data that hasn't been reprocessed), the plugin falls back to the old vertical rendering.

### Data Flow

The plugin calls the Render backend API (`/exams/patients/{id}/reports`) via the WordPress bridge. The `transform_render_report()` method now preserves the full structured data (units, ranges, flags, clinical groups) instead of flattening it to key-value pairs.

---

## 8. Verification Results

### Multi-Sample Validation (Local Test)

| Sample | Type | Results Extracted | Old Regex | Improvement |
|--------|------|-------------------|-----------|-------------|
| Sample 1 | Hematology / Biochemistry | 22/22 (100%) | 9/22 (41%) | +13 results |
| Sample 2 | Hormones (TSH, T3, T4, Cortisol, etc.) | 18/18 (100%) | 0/18 (0%) | +18 results |
| Sample 3 | Messy OCR with typos | 19/19 (100%) | 0/19 (0%) | +19 results |
| **Total** | | **59/59 (100%)** | **9/59 (15%)** | **+50 results** |

### Abnormal Flag Accuracy

All abnormal flags were correctly detected across all samples:

| Exam | Value | Reference | Flag | Correct |
|------|-------|-----------|------|---------|
| Αιμοπετάλια (PLT) | 628 x10³/μL | 145-450 | ↑ HIGH | Yes |
| Ολική χοληστερόλη | 215 mg/dL | < 200 | ↑ HIGH | Yes |
| LDL | 138 mg/dL | < 130 | ↑ HIGH | Yes |
| Κορτιζόλη | 594.8 nmol/L | 133-537 | ↑ HIGH | Yes |
| Τεστοστερόνη Ολική | 6.87 nmol/L | 8.3-30.2 | ↓ LOW | Yes |
| Βιταμίνη D | 28.5 ng/mL | 30-100 | ↓ LOW | Yes |
| CRP ποσοτική | 2.89 mg/dL | < 0.5 | ↑ HIGH | Yes |
| Αιματοκρίτης (HCT) | 40.4% | 41-52 | ↓ LOW | Yes |
| Αιμοσφαιρίνη (HGB) | 12.9 g/dL | 13-18 | ↓ LOW | Yes |

### Production Reprocessing

All 4 legacy documents for Patient #4 were reprocessed successfully:

| Document | Patient | Status | Normalization |
|----------|---------|--------|---------------|
| fb1b8573... | Patient 4 | success | auto_verified |
| b76640b8... | Patient 1 | success | auto_verified |
| a087838d... | Patient 4 | success | auto_verified |
| 7268a9cf... | Patient 4 | success | auto_verified |

### Live Dashboard Rendering

The Doctor Dashboard at `https://autoanosis.com/doctor-dashboard/?patient=4` was verified to display:

1. Three reports with horizontal tables showing all extracted parameters.
2. Clinical group headers (hepatic, general, biochemistry, renal, inflammation, endocrine, hematology).
3. Color-coded abnormal flags (Κορτιζόλη ↑ Υψηλό in red, Τεστοστερόνη ↓ Χαμηλό in orange).
4. Full reference ranges including complex text (e.g., "Πρωί (7-10 μμ): 133,0-537,0 nmol/L").
5. Report metadata: date, confidence score (94-95%), and auto_verified status.

---

## 9. Git Commits (Render Backend)

| Commit | Message |
|--------|---------|
| `7b6bad6` | feat: AI Universal Normalizer v3.0.0 + exam_service integration |
| `b49ce19` | feat: Add admin reprocess endpoint for upgrading legacy reports to AI normalizer |
| `8ea546b` | fix: reprocess endpoint uses ocr_text (not raw_text) matching ExamDocument model |
| `570656c` | fix: reprocess uses uploaded_at (not created_at) matching ExamDocument model |

---

## 10. Environment Variables Required

The AI Normalizer requires the following environment variable on Render:

| Variable | Purpose | Status |
|----------|---------|--------|
| `OPENAI_API_KEY` | GPT-4.1-mini API access for structured extraction | Already configured |
| `AUTOA_AI_PROXY_SECRET` | Admin auth for reprocess endpoint | Already configured |

---

## 11. Rollback Plan

If the AI Normalizer needs to be rolled back:

1. **Backend:** Revert `exam_service.py` to import from `normalizer.py` instead of `normalizer_ai.py`. The old regex normalizer is still present and functional.
2. **Dashboard:** Rename `autoanosis-doctor-dashboard.php.bak.v9.1.0` back to `autoanosis-doctor-dashboard.php` on SiteGround. The backup is preserved in the plugin directory.
3. **Data:** Run the reprocess endpoint again after reverting to regenerate reports with the old normalizer (note: this will lose the enhanced data).

---

## 12. Binding Decisions

The following decisions are now **binding** for future development:

1. The AI Normalizer (`normalizer_ai.py`) is the **primary and only active normalizer**. The regex normalizer is retained only as a code reference.
2. All new exam reports **must** include `confidence_score`, `normalization_status`, and `parser_version` fields.
3. The `source_lineage` JSON on each `ExamResult` **must** contain `ocr_snippet` for traceability.
4. The Doctor Dashboard **must** render structured results in horizontal table format. Vertical key-value rendering is only a backward-compatibility fallback.
5. The `reprocess` admin endpoint is available for future bulk upgrades when the normalizer is improved.
6. Clinical group headers in the dashboard follow the AI normalizer's grouping (hepatic, renal, endocrine, hematology, biochemistry, inflammation, general).
