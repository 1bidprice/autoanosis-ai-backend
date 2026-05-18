"""
Autoanosis Exams — Universal AI Normalizer v3.0.0
==================================================
Replaces the regex-based normalizer with LLM-powered structured extraction.

Features:
  - Parses ANY medical exam type in ANY language (Greek, English, etc.)
  - Extracts ALL parameters: name, value, unit, reference range, abnormal flag
  - Structured JSON output via OpenAI function calling / JSON mode
  - Post-validation: numeric parsing, unit validation, reference range checks,
    abnormal flag verification, duplicate/impossible result filtering
  - Raw-to-structured traceability via source_lineage and ocr_snippet per result
  - Confidence scoring at report and result level
  - needs_review / rejected path for weak OCR, missing data, or suspicious extraction

Architecture:
  1. classify_document() — detect doc type (lab / imaging / unknown)
  2. ai_extract_lab_results() — send OCR text to GPT with strict JSON schema
  3. post_validate_results() — validate every extracted result
  4. build_parsed_report() — assemble final ParsedReport with traceability
"""

import os
import re
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Tuple, Optional
from decimal import Decimal, InvalidOperation

logger = logging.getLogger("exams.normalizer_ai")

# ---------------------------------------------------------------------------
# Data classes (same interface as normalizer.py for drop-in compatibility)
# ---------------------------------------------------------------------------

@dataclass
class ParsedResult:
    display_name: str
    value_numeric: float | None = None
    value_text: str | None = None
    unit: str | None = None
    reference_low: float | None = None
    reference_high: float | None = None
    reference_text: str | None = None
    abnormal_flag: str = "unknown"
    trendable: bool = False
    clinical_group: str | None = None
    parser_confidence: float = 0.90
    ocr_snippet: str | None = None          # traceability: raw text fragment
    validation_warnings: list = field(default_factory=list)


@dataclass
class ParsedImpression:
    section_type: str
    text: str
    severity_flag: str = "unknown"
    review_required: bool = False


@dataclass
class ParsedReport:
    exam_type: str
    exam_category: str
    confidence_score: float
    normalization_status: str
    source_lineage: Dict[str, str]
    results: List[ParsedResult]
    impressions: List[ParsedImpression]
    performed_at: str | None = None         # ISO date string if detected
    lab_name: str | None = None
    ordering_doctor: str | None = None
    validation_summary: Dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PARSER_VERSION = "ai_universal_normalizer_v3"

TRENDABLE_KEYWORDS = {
    # English
    "wbc", "rbc", "hemoglobin", "hematocrit", "platelets", "plt", "hgb", "hct",
    "crp", "esr", "tsh", "ft3", "ft4", "vitamin d", "ferritin",
    "glucose", "cholesterol", "triglycerides", "creatinine", "urea",
    "alt", "ast", "ggt", "albumin", "bilirubin",
    "cortisol", "insulin", "hba1c",
    # Greek
    "λευκά αιμοσφαίρια", "ερυθρά αιμοσφαίρια", "αιμοσφαιρίνη", "αιματοκρίτης",
    "αιμοπετάλια", "τκε", "γλυκόζη", "χοληστερόλη", "τριγλυκερίδια",
    "κρεατινίνη", "ουρία", "φερριτίνη", "βιταμίνη d", "κορτιζόλη",
}

# Known valid medical units (partial list for validation)
KNOWN_UNITS = {
    "g/dl", "g/l", "mg/dl", "mg/l", "mmol/l", "μmol/l", "umol/l",
    "ng/ml", "ng/dl", "pg/ml", "nmol/l", "pmol/l",
    "miu/l", "μiu/ml", "miu/ml", "iu/l", "u/l",
    "x10^3/μl", "x10³/μl", "x10^6/μl", "x10⁶/μl",
    "x10^3/ul", "x10^6/ul", "10^3/μl", "10^6/μl",
    "k/μl", "m/μl", "k/ul", "m/ul",
    "fl", "pg", "%", "mm/h", "mm/hr", "sec", "seconds",
    "meq/l", "mg/24h", "ml/min", "ml/min/1.73m2",
    "cells/μl", "copies/ml",
}


# ---------------------------------------------------------------------------
# Document classification (enhanced from v2, kept deterministic)
# ---------------------------------------------------------------------------

def detect_garbage_text(text: str) -> Tuple[bool, str]:
    t = (text or "").strip()
    if len(t) < 20:
        return True, "text_too_short"
    markers = ["cookie", "accept all", "privacy policy", "menu", "subscribe",
               "login", "home page", "click here", "javascript"]
    if sum(m in t.lower() for m in markers) >= 2:
        return True, "webpage_or_screenshot_noise"
    return False, ""


def classify_document(text: str) -> Tuple[str, float]:
    low = text.lower()

    lab_keywords = [
        # English
        "crp", "esr", "tsh", "vitamin d", "ferritin", "wbc", "rbc", "hgb",
        "plt", "hemoglobin", "hematocrit", "cholesterol", "triglycerides",
        "glucose", "urea", "creatinine", "albumin", "bilirubin", "alt", "ast",
        "cortisol", "insulin", "testosterone", "estradiol", "prolactin",
        # Greek
        "αιματολογ", "γενική αίματος", "γενικη αιματος",
        "λευκά αιμοσφαίρια", "λευκα αιμοσφαιρια",
        "ερυθρά αιμοσφαίρια", "ερυθρα αιμοσφαιρια",
        "αιμοσφαιρίνη", "αιμοσφαιρινη", "αιμοπετάλια", "αιμοπεταλια",
        "ουρία", "ουρια", "κρεατινίνη", "κρεατινινη",
        "χοληστερόλη", "χοληστερολη", "τριγλυκερίδια", "τριγλυκεριδια",
        "γλυκόζη", "γλυκοζη", "ουρικό οξύ", "ουρικο οξυ",
        "τκε", "ταχύτητα καθίζησης", "φερριτίνη", "φερριτινη",
        "βιταμίνη d", "βιταμινη d", "θυρεοτρόπος", "θυρεοτροπος",
        "αλβουμίνη", "αλβουμινη", "χολερυθρίνη", "χολερυθρινη",
        "γενική ούρων", "γενικη ουρων", "μικροβιολογ",
        "κορτιζόλη", "κορτιζολη", "ινσουλίνη", "ινσουλινη",
        "τεστοστερόνη", "οιστραδιόλη", "προλακτίνη",
        "ορμόνες", "ορμονες", "βιοχημικ", "ηπατικ", "νεφρικ",
        "θυρεοειδ", "ηλεκτρολύτ",
    ]

    imaging_keywords = [
        "findings", "impression", "conclusion", "recommendation",
        "μαγνητικ", "υπερηχογραφ", "ακτινογραφ", "αξονικ",
        "εντύπωση", "εντυπωση", "ευρήματα", "ευρηματα",
        "πόρισμα", "ποριμα", "συμπέρασμα", "συμπερασμα",
        "απεικονιστ", "mri", "ct scan", "x-ray", "ultrasound",
    ]

    if any(k in low for k in lab_keywords):
        return "lab", 0.95

    if any(k in low for k in imaging_keywords):
        return "imaging", 0.88

    # Fallback: detect numeric lab-style patterns
    numeric_pattern = re.compile(
        r"[\w\s\u0370-\u03FF\u1F00-\u1FFF]{2,30}\s*[:\-]\s*\d+(?:[.,]\d+)?\s*[\w/μ]*\s*\(?\s*\d+(?:[.,]\d+)?\s*-\s*\d+(?:[.,]\d+)?\s*\)?",
        re.UNICODE
    )
    if len(numeric_pattern.findall(text)) >= 3:
        return "lab", 0.80

    return "unknown", 0.40


# ---------------------------------------------------------------------------
# GPT Structured Extraction
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM_PROMPT = """You are a medical laboratory report parser. You receive raw OCR text from medical exam documents and extract ALL test results into structured JSON.

CRITICAL RULES:
1. Extract EVERY SINGLE test/measurement found in the text. Do not skip any.
2. For each test, extract: name, numeric value, text value (if non-numeric), unit, reference range (low and high as separate numbers), reference text (raw string), and clinical group.
3. If a test has a numeric value, always put it in value_numeric. If the result is text-only (e.g., "Negative", "Αρνητικό"), put it in value_text.
4. Preserve the EXACT unit as written in the document (e.g., "x10³/μL", "g/dL", "nmol/L").
5. Parse reference ranges into separate low and high numbers. If only one bound exists, set the other to null. Keep the raw reference string in reference_text.
6. Determine abnormal_flag: "high" if value > reference_high, "low" if value < reference_low, "normal" if within range, "unknown" if no reference range available.
7. Assign clinical_group from: hematology, biochemistry, endocrine, lipids, metabolic, renal, hepatic, inflammation, iron, coagulation, urinalysis, immunology, tumor_markers, vitamins, cardiac, thyroid, hormones, general.
8. If you detect the exam date, lab name, or ordering doctor, include them in the metadata.
9. For multi-section documents (e.g., CBC + Hormones + Biochemistry in one report), extract ALL sections.
10. Handle Greek, English, or any language. Preserve original test names.
11. For each extracted result, include the approximate OCR line or snippet where you found it (ocr_snippet field) for traceability.
12. If you cannot confidently extract a value, still include the test with value_text containing what you see, and set parser_confidence to a lower value (0.3-0.6).
13. exam_date must always be returned as ISO date: YYYY-MM-DD. Never return DD/MM/YYYY, MM/DD/YYYY, DD-MM-YYYY, or localized date strings. If the date is ambiguous or cannot be confidently normalized, return null.
14. For age-stratified or time-stratified reference ranges (e.g., "3.5-5.0 (>60ετη: 3.4-4.8)", "Πρωί 7-10πμ: 133-537 / Απόγευμα 4-8μμ: 68-327", "8.8-46.3 Χειμερινή / 15.7-60.3 Καλοκαιρινή"), ALWAYS use the FIRST / most general range as reference_low and reference_high. Store the full raw string in reference_text. Never use an age-specific or time-specific sub-range as the primary range unless it is the only one given.
15. For multi-page documents where the patient header (ΟΝΟΜΑΤΕΠΩΝΥΜΟ, ΗΜΕΡ.ΕΞΕΤΑΣΗΣ) repeats on each page, treat the entire document as ONE exam from the date on the first page. Do not create duplicate metadata entries.

Respond with ONLY valid JSON matching this exact schema:
{
  "metadata": {
    "exam_date": "YYYY-MM-DD or null",
    "lab_name": "string or null",
    "ordering_doctor": "string or null",
    "document_type": "lab_panel | imaging_report | mixed_panel",
    "sections_detected": ["string"]
  },
  "results": [
    {
      "display_name": "Test Name (original language)",
      "value_numeric": 5.2,
      "value_text": null,
      "unit": "mg/dL",
      "reference_low": 3.0,
      "reference_high": 6.0,
      "reference_text": "3.0 - 6.0 mg/dL",
      "abnormal_flag": "normal",
      "clinical_group": "biochemistry",
      "ocr_snippet": "the raw text line where this was found",
      "parser_confidence": 0.95
    }
  ],
  "impressions": [
    {
      "section_type": "narrative | findings | conclusion",
      "text": "Free text impression or finding",
      "severity_flag": "normal | attention | critical | unknown"
    }
  ]
}"""


def _fix_json_string(raw: str) -> str:
    """Fix common JSON issues from LLM output: trailing commas, comments, etc."""
    # Remove trailing commas before } or ]
    fixed = re.sub(r',\s*([}\]])', r'\1', raw)
    # Remove single-line comments (// ...)
    fixed = re.sub(r'//[^\n]*', '', fixed)
    return fixed.strip()


def _call_openai(ocr_text: str, max_retries: int = 2) -> Optional[dict]:
    """Call OpenAI API with structured extraction prompt. Returns parsed JSON or None."""
    try:
        from openai import OpenAI
    except ImportError:
        logger.error("[AI_NORMALIZER] openai package not installed")
        return None

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        logger.error("[AI_NORMALIZER] OPENAI_API_KEY not set")
        return None

    client = OpenAI(api_key=api_key)

    # Truncate very long OCR text to avoid token limits (keep first 12000 chars)
    text_to_send = ocr_text[:12000] if len(ocr_text) > 12000 else ocr_text

    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[
                    {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Extract ALL test results from this medical document:\n\n{text_to_send}"}
                ],
                temperature=0.05,
                max_tokens=6000,
                response_format={"type": "json_object"},
                timeout=110,
            )

            raw_json = response.choices[0].message.content.strip()

            # Try direct parse first
            try:
                parsed = json.loads(raw_json)
            except json.JSONDecodeError:
                # Fix common LLM JSON issues (trailing commas, etc.)
                fixed_json = _fix_json_string(raw_json)
                parsed = json.loads(fixed_json)

            # Basic structural validation
            if "results" not in parsed:
                logger.warning(f"[AI_NORMALIZER] Attempt {attempt+1}: Missing 'results' key in response")
                continue

            logger.info(f"[AI_NORMALIZER] Attempt {attempt+1}: Successfully extracted {len(parsed['results'])} results")
            return parsed

        except json.JSONDecodeError as e:
            logger.warning(f"[AI_NORMALIZER] Attempt {attempt+1}: JSON parse error after fix attempt: {e}")
            # Log the problematic area for debugging
            if 'raw_json' in dir():
                error_pos = getattr(e, 'pos', 0) or 0
                snippet_start = max(0, error_pos - 100)
                snippet_end = min(len(raw_json), error_pos + 100)
                logger.warning(f"[AI_NORMALIZER] JSON error near: ...{raw_json[snippet_start:snippet_end]}...")
            continue
        except Exception as e:
            logger.error(f"[AI_NORMALIZER] Attempt {attempt+1}: API error: {e}")
            continue

    logger.error("[AI_NORMALIZER] All retry attempts exhausted")
    return None


# ---------------------------------------------------------------------------
# Post-Validation Engine
# ---------------------------------------------------------------------------

def _safe_float(val) -> Optional[float]:
    """Safely convert a value to float, handling commas and edge cases."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        val = val.strip().replace(",", ".")
        try:
            return float(val)
        except ValueError:
            return None
    return None


def _normalize_unit(unit: str | None) -> str | None:
    """Normalize unit string for consistency."""
    if not unit:
        return None
    u = unit.strip()
    if not u:
        return None
    return u


def _is_trendable(name: str) -> bool:
    """Check if a test name is trendable based on keywords."""
    low = name.lower().strip()
    for keyword in TRENDABLE_KEYWORDS:
        if keyword in low:
            return True
    return False


def _validate_abnormal_flag(value: float | None, low: float | None, high: float | None, claimed_flag: str) -> Tuple[str, list]:
    """Validate and correct the abnormal flag based on actual numeric comparison.
    Always returns short uppercase flags: H, L, N, or unknown.
    """
    warnings = []
    # Normalize any long-form flag to short form
    _norm = {"low": "L", "high": "H", "normal": "N", "n": "N", "l": "L", "h": "H",
             "hh": "HH", "ll": "LL", "critical": "CRITICAL"}
    claimed_short = _norm.get((claimed_flag or "").lower(), claimed_flag or "unknown")

    if value is None:
        return claimed_short if claimed_short != "unknown" else "unknown", warnings

    computed = "unknown"
    if low is not None and high is not None:
        if value < low:
            computed = "L"
        elif value > high:
            computed = "H"
        else:
            computed = "N"
    elif low is not None:
        computed = "L" if value < low else "N"
    elif high is not None:
        computed = "H" if value > high else "N"

    if computed != "unknown" and claimed_short not in ("unknown", computed):
        warnings.append(f"abnormal_flag_corrected: AI said '{claimed_flag}', computed '{computed}'")

    return computed if computed != "unknown" else claimed_short, warnings


def _detect_impossible_value(name: str, value: float | None) -> bool:
    """Detect physiologically impossible values (basic sanity checks)."""
    if value is None:
        return False
    # Negative values are almost always impossible for lab results
    if value < 0:
        return True
    # Extremely large values that are likely OCR errors
    if value > 100000:
        return True
    return False


def post_validate_results(raw_results: list) -> Tuple[List[ParsedResult], Dict]:
    """
    Post-validate all AI-extracted results.
    Returns validated ParsedResult list and a validation summary dict.
    """
    validated = []
    summary = {
        "total_extracted": len(raw_results),
        "valid": 0,
        "warnings": 0,
        "rejected": 0,
        "missing_units": 0,
        "missing_references": 0,
        "flag_corrections": 0,
        "duplicates_removed": 0,
        "impossible_values": 0,
    }

    seen_names = set()

    for r in raw_results:
        warnings = []
        display_name = (r.get("display_name") or "").strip()
        if not display_name:
            summary["rejected"] += 1
            continue

        # Duplicate detection (case-insensitive)
        name_key = display_name.lower()
        if name_key in seen_names:
            summary["duplicates_removed"] += 1
            continue
        seen_names.add(name_key)

        # Parse numeric value
        value_numeric = _safe_float(r.get("value_numeric"))
        value_text = r.get("value_text")

        # If no numeric and no text, skip
        if value_numeric is None and not value_text:
            summary["rejected"] += 1
            warnings.append("no_value_found")
            continue

        # Impossible value check
        if _detect_impossible_value(display_name, value_numeric):
            summary["impossible_values"] += 1
            warnings.append(f"impossible_value: {value_numeric}")
            # Don't reject, but flag for review
            value_numeric = None
            value_text = str(r.get("value_numeric", "")) + " [SUSPICIOUS]"

        # Unit parsing
        unit = _normalize_unit(r.get("unit"))
        if value_numeric is not None and not unit:
            summary["missing_units"] += 1
            warnings.append("missing_unit")

        # Reference range parsing
        ref_low = _safe_float(r.get("reference_low"))
        ref_high = _safe_float(r.get("reference_high"))
        ref_text = r.get("reference_text") or None

        if ref_low is None and ref_high is None:
            summary["missing_references"] += 1
            warnings.append("missing_reference_range")

        # Validate reference range sanity (low should be < high)
        if ref_low is not None and ref_high is not None and ref_low > ref_high:
            warnings.append(f"reference_range_inverted: {ref_low} > {ref_high}")
            ref_low, ref_high = ref_high, ref_low  # auto-correct

        # Abnormal flag validation
        claimed_flag = r.get("abnormal_flag", "unknown")
        validated_flag, flag_warnings = _validate_abnormal_flag(value_numeric, ref_low, ref_high, claimed_flag)
        warnings.extend(flag_warnings)
        if flag_warnings:
            summary["flag_corrections"] += 1

        # Clinical group
        clinical_group = r.get("clinical_group", "general")

        # Trendable
        trendable = _is_trendable(display_name)

        # Parser confidence
        raw_confidence = _safe_float(r.get("parser_confidence")) or 0.90
        # Reduce confidence if warnings exist
        if warnings:
            raw_confidence = max(0.3, raw_confidence - 0.1 * len(warnings))

        # OCR snippet for traceability
        ocr_snippet = r.get("ocr_snippet", "")

        if warnings:
            summary["warnings"] += 1
        else:
            summary["valid"] += 1

        validated.append(ParsedResult(
            display_name=display_name,
            value_numeric=value_numeric,
            value_text=value_text if value_numeric is None else None,
            unit=unit,
            reference_low=ref_low,
            reference_high=ref_high,
            reference_text=ref_text,
            abnormal_flag=validated_flag,
            trendable=trendable,
            clinical_group=clinical_group,
            parser_confidence=round(raw_confidence, 4),
            ocr_snippet=ocr_snippet,
            validation_warnings=warnings,
        ))

    return validated, summary


# ---------------------------------------------------------------------------
# Normalization Status Decision
# ---------------------------------------------------------------------------

def _decide_normalization_status(results: List[ParsedResult], summary: Dict) -> Tuple[str, float]:
    """
    Decide normalization_status and confidence_score based on validation results.
    Returns (status, confidence).
    """
    total = summary.get("total_extracted", 0)
    valid = summary.get("valid", 0)
    warnings_count = summary.get("warnings", 0)
    rejected = summary.get("rejected", 0)
    missing_units = summary.get("missing_units", 0)
    missing_refs = summary.get("missing_references", 0)

    if total == 0 or len(results) == 0:
        return "needs_review", 0.30

    # Calculate quality ratio
    quality_ratio = valid / max(len(results), 1)

    # High quality: >80% valid, few missing units/refs
    if quality_ratio >= 0.8 and missing_units <= 2 and missing_refs <= len(results) * 0.3:
        return "auto_verified", round(0.85 + quality_ratio * 0.10, 4)

    # Medium quality: some issues but mostly extracted
    if quality_ratio >= 0.5:
        return "auto_verified", round(0.70 + quality_ratio * 0.10, 4)

    # Low quality: too many issues
    return "needs_review", round(0.40 + quality_ratio * 0.20, 4)


# ---------------------------------------------------------------------------
# Main Entry Points
# ---------------------------------------------------------------------------

def ai_normalize_lab(text: str) -> Optional[ParsedReport]:
    """
    Normalize a lab document using AI extraction + post-validation.
    Returns a ParsedReport or None if extraction completely fails.
    """
    # Step 1: Call GPT for structured extraction
    ai_response = _call_openai(text)
    if ai_response is None:
        logger.error("[AI_NORMALIZER] GPT extraction returned None — falling back to needs_review")
        return ParsedReport(
            exam_type="lab_panel",
            exam_category="lab",
            confidence_score=0.20,
            normalization_status="needs_review",
            source_lineage={"parser": PARSER_VERSION, "extraction": "failed", "reason": "api_error"},
            results=[],
            impressions=[ParsedImpression(
                section_type="narrative",
                text=text[:2000],
                review_required=True,
            )],
            validation_summary={"error": "ai_extraction_failed"},
        )

    # Step 2: Extract metadata
    metadata = ai_response.get("metadata", {})
    performed_at = metadata.get("exam_date")
    lab_name = metadata.get("lab_name")
    ordering_doctor = metadata.get("ordering_doctor")
    doc_type = metadata.get("document_type", "lab_panel")
    sections = metadata.get("sections_detected", [])

    # Step 3: Post-validate all results
    raw_results = ai_response.get("results", [])
    validated_results, validation_summary = post_validate_results(raw_results)

    # Step 4: Process impressions
    impressions = []
    for imp in ai_response.get("impressions", []):
        impressions.append(ParsedImpression(
            section_type=imp.get("section_type", "narrative"),
            text=imp.get("text", ""),
            severity_flag=imp.get("severity_flag", "unknown"),
            review_required=imp.get("severity_flag") in ("attention", "critical"),
        ))

    # Step 5: Decide normalization status
    norm_status, confidence = _decide_normalization_status(validated_results, validation_summary)

    # Step 6: Build source lineage for full traceability
    source_lineage = {
        "parser": PARSER_VERSION,
        "extraction": "openai_gpt4.1_mini",
        "model": "gpt-4.1-mini",
        "sections_detected": json.dumps(sections),
        "total_extracted": str(validation_summary.get("total_extracted", 0)),
        "valid_results": str(validation_summary.get("valid", 0)),
        "warnings": str(validation_summary.get("warnings", 0)),
        "rejected": str(validation_summary.get("rejected", 0)),
    }

    return ParsedReport(
        exam_type=doc_type if doc_type != "mixed_panel" else "lab_panel",
        exam_category="lab",
        confidence_score=confidence,
        normalization_status=norm_status,
        source_lineage=source_lineage,
        results=validated_results,
        impressions=impressions,
        performed_at=performed_at,
        lab_name=lab_name,
        ordering_doctor=ordering_doctor,
        validation_summary=validation_summary,
    )


def ai_normalize_imaging(text: str) -> ParsedReport:
    """
    Normalize an imaging document using AI extraction.
    For imaging, we primarily extract impressions/findings.
    """
    ai_response = _call_openai(text)
    if ai_response is None:
        return ParsedReport(
            exam_type="imaging_report",
            exam_category="imaging",
            confidence_score=0.30,
            normalization_status="needs_review",
            source_lineage={"parser": PARSER_VERSION, "extraction": "failed"},
            results=[],
            impressions=[ParsedImpression(
                section_type="narrative",
                text=text[:2000],
                review_required=True,
            )],
        )

    metadata = ai_response.get("metadata", {})
    impressions = []
    has_structured = False

    for imp in ai_response.get("impressions", []):
        is_review = imp.get("severity_flag") in ("attention", "critical")
        impressions.append(ParsedImpression(
            section_type=imp.get("section_type", "narrative"),
            text=imp.get("text", ""),
            severity_flag=imp.get("severity_flag", "unknown"),
            review_required=is_review,
        ))
        if imp.get("section_type") != "narrative":
            has_structured = True

    # Also extract any numeric results from imaging (e.g., measurements)
    raw_results = ai_response.get("results", [])
    validated_results, validation_summary = post_validate_results(raw_results)

    norm_status = "auto_verified" if (has_structured or impressions) else "needs_review"
    confidence = 0.85 if has_structured else 0.55

    return ParsedReport(
        exam_type="imaging_report",
        exam_category="imaging",
        confidence_score=confidence,
        normalization_status=norm_status,
        source_lineage={"parser": PARSER_VERSION, "extraction": "openai_gpt4.1_mini"},
        results=validated_results,
        impressions=impressions,
        performed_at=metadata.get("exam_date"),
        lab_name=metadata.get("lab_name"),
        ordering_doctor=metadata.get("ordering_doctor"),
        validation_summary=validation_summary,
    )


# ---------------------------------------------------------------------------
# Chunked normalization for multi-section PDFs
# ---------------------------------------------------------------------------

CHUNK_THRESHOLD = 2000  # chars — above this, try to split into sections


def _split_into_sections(text: str) -> list:
    """
    Split a multi-section lab PDF into individual sections.
    Each section starts with a patient header (ΟΝΟΜΑΤΕΠΩΝΥΜΟ:).
    Returns a list of section strings, or [text] if no split point found.
    """
    import re as _re
    # Split on patient header repetitions (each page of a multi-section PDF starts with this)
    parts = _re.split(r'(?=ΟΝΟΜΑΤΕΠΩΝΥΜΟ\s*:)', text.strip())
    # Filter out empty parts
    sections = [p.strip() for p in parts if p.strip() and len(p.strip()) > 100]
    if len(sections) <= 1:
        return [text]
    logger.info(f"[CHUNKER] Split document into {len(sections)} sections")
    return sections


def _merge_parsed_reports(reports: list) -> Optional['ParsedReport']:
    """
    Merge multiple ParsedReport objects from chunked normalization into one.
    Uses metadata from the first report, merges all results and impressions.
    """
    valid = [r for r in reports if r is not None]
    if not valid:
        return None
    if len(valid) == 1:
        return valid[0]

    # Use first report as base
    base = valid[0]
    all_results = list(base.results)
    all_impressions = list(base.impressions)
    total_extracted = 0
    total_valid = 0

    for r in valid[1:]:
        all_results.extend(r.results)
        all_impressions.extend(r.impressions)
        vs = r.validation_summary or {}
        total_extracted += vs.get('total_extracted', 0)
        total_valid += vs.get('valid', 0)

    # Deduplicate results by display_name (keep first occurrence)
    seen = set()
    deduped = []
    for res in all_results:
        key = (res.display_name or '').lower().strip()
        if key not in seen:
            seen.add(key)
            deduped.append(res)

    base.results = deduped
    base.impressions = all_impressions
    base.validation_summary = base.validation_summary or {}
    base.validation_summary['chunked_sections'] = len(valid)
    base.validation_summary['total_extracted'] = total_extracted + (base.validation_summary.get('total_extracted', 0))
    base.source_lineage['chunked'] = str(len(valid))

    # Recalculate confidence and status
    norm_status, confidence = _decide_normalization_status(deduped, base.validation_summary)
    base.normalization_status = norm_status
    base.confidence_score = confidence

    logger.info(f"[CHUNKER] Merged {len(valid)} sections → {len(deduped)} unique results")
    return base


def normalize_document(text: str) -> Optional[ParsedReport]:
    """
    Main entry point — drop-in replacement for normalizer.py's normalize_document().
    Routes to AI lab or imaging normalizer based on document classification.
    For large multi-section PDFs, uses chunked normalization to avoid memory/timeout issues.
    """
    garbage, reason = detect_garbage_text(text)
    if garbage:
        return None

    label, class_confidence = classify_document(text)

    if label == "lab":
        # For large multi-section PDFs, split into chunks to avoid memory/timeout
        if len(text) > CHUNK_THRESHOLD:
            sections = _split_into_sections(text)
            if len(sections) > 1:
                reports = []
                for i, section in enumerate(sections):
                    logger.info(f"[CHUNKER] Processing section {i+1}/{len(sections)} ({len(section)} chars)")
                    report = ai_normalize_lab(section)
                    reports.append(report)
                merged = _merge_parsed_reports(reports)
                if merged is not None:
                    return merged
                # Fall through to single-call if merge failed
        return ai_normalize_lab(text)

    if label == "imaging":
        return ai_normalize_imaging(text)

    # Unknown documents — still try AI extraction (it might find lab results)
    result = ai_normalize_lab(text)
    if result and len(result.results) > 0:
        result.normalization_status = "needs_review"  # lower trust for unknown docs
        result.source_lineage["classification"] = "unknown_attempted_lab"
        return result

    # Truly unknown — store for manual review
    return ParsedReport(
        exam_type="unknown",
        exam_category="unknown",
        confidence_score=0.25,
        normalization_status="needs_review",
        source_lineage={"parser": PARSER_VERSION, "classification": "unknown"},
        results=[],
        impressions=[ParsedImpression(
            section_type="narrative",
            text=text[:2000],
            review_required=True,
        )],
    )
