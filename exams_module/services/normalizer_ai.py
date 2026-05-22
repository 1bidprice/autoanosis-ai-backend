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
    # Semantic interpretation fields (v3.1)
    metric_kind: str = "numeric_lab"        # numeric_lab | qualitative | percentage_distribution | count | narrative
    semantic_direction: str = "bidirectional"  # higher_is_worse | lower_is_worse | bidirectional | qualitative_map | narrative_only
    evaluation_status: str = "unknown"      # normal | warning | abnormal | unknown | needs_review
    review_reason: str = ""                 # human-readable reason if not normal
    disclaimer: str = ""                    # clinical disclaimer if applicable


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
    report_review_reason: str = ""          # report-level guidance message (e.g. AGP-only)


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

    # -----------------------------------------------------------------------
    # CGM keywords — checked FIRST, before imaging, because CGM app
    # screenshots often contain words like "ευρήματα" (findings) in their
    # UI chrome which would otherwise trigger the imaging classifier.
    # -----------------------------------------------------------------------
    cgm_keywords = [
        "ehba1c", "ehba", "mbg", "tir", "cgm", "libreview", "freestyle libre",
        "librelink", "libre link", "dexcom", "medtronic", "guardian",
        "time in range", "χρόνος κάλυψης", "χρονος καλυψης",
        "αισθητήρας γλυκόζης", "αισθητηρας γλυκοζης",
        "lbgi", "hbgi",
        "μέση γλυκόζη", "μεση γλυκοζη",
        # AGP chart indicators — present in CGM app screenshots
        "agp", "διακύμανσης γλυκόζης", "διακυμανσης γλυκοζης",
        "50% διάμεσος", "50% διαμεσος",
        "διάστημα 25%-75%", "διαστημα 25%-75%",
        "διάστημα 10%-90%", "διαστημα 10%-90%",
        "πολύημερες καμπύλες", "πολυημερες καμπυλες",
        "τάσεις γλυκόζης", "τασεις γλυκοζης",
        "αρχεία διακύμανσης", "αρχεια διακυμανσης",
        "προφίλ διακύμανσης", "προφιλ διακυμανσης",
        "glucose variability", "ambulatory glucose",
        # Structured OCR summary patterns (AI-generated OCR output format)
        # These appear when the OCR pipeline produces a step-by-step summary
        # of CGM app screenshots instead of raw text.
        "50% διάμεσος", "50% διαμεσος",
        "διάστημα 25%", "διαστημα 25%",
        "διάστημα 10%", "διαστημα 10%",
        "λεζάντες", "λεζαντες",
        "πολυήμερες καμπύλες", "πολυημερες καμπυλες",
        "καμπύλες γλυκόζης", "καμπυλες γλυκοζης",
        "γλυκόζης αίματος", "γλυκοζης αιματος",
        "επιλέξτε ημερομηνία", "επιλεξτε ημερομηνια",
        "επιλογή όλων", "επιλογη ολων",
        "ιστορικό", "ιστορικο",  # CGM app navigation tab
    ]

    # Additional heuristic: structured OCR output containing glucose chart
    # axis values (0, 90, 180, 270, 360 mg/dL) with date ranges
    import re as _re
    _cgm_axis = _re.search(
        r'(?:0[,\s]+90[,\s]+180|\b180\b.*\b270\b.*\b360\b|παράμετροι.*0.*90.*180|παραμετροι.*0.*90.*180)',
        low
    )
    _date_range = _re.search(
        r'\d{2}/\d{2}/\d{4}.*?[\u2014\u2013\-\u2015]{1,3}.*?\d{2}/\d{2}/\d{4}',
        low
    )
    if _cgm_axis and _date_range:
        return "cgm", 0.90

    # Heuristic: structured OCR summary with ΒΗΜΑ format + screenshot of app
    _vima_app = _re.search(r'βημα.*screenshot.*εφαρμογ|βημα.*γραφικ.*δεδομεν', low)
    _glucose_context = _re.search(r'(?:ημερομηνι|ωρα|γραφικ).*(?:01|02|03|04|05|06|07|08|09|10|11|12)/\d{2}/\d{4}', low)
    if _vima_app and _glucose_context:
        return "cgm", 0.85

    if any(k in low for k in cgm_keywords):
        return "cgm", 0.95

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

EXTRACTION_SYSTEM_PROMPT = """You are a medical document parser. You receive raw OCR text from ANY medical document (lab report, CGM/glucose sensor report, urinalysis, imaging report, prescription, etc.) and extract ALL findings into structured JSON.

CRITICAL RULES:
1. Extract EVERY SINGLE test/measurement found in the text. Do not skip any.
2. For each test, extract: name, numeric value, text value (if non-numeric), unit, reference range (low and high as separate numbers), reference text (raw string), clinical group, metric_kind, and semantic_direction.
3. If a test has a numeric value, always put it in value_numeric. If the result is text-only (e.g., "Negative", "Αρνητικό"), put it in value_text.
4. Preserve the EXACT unit as written in the document (e.g., "x10³/μL", "g/dL", "nmol/L").
5. Parse reference ranges into separate low and high numbers. If only one bound exists, set the other to null. Keep the raw reference string in reference_text.
6. For abnormal_flag: set to "unknown" for CGM metrics, urinalysis qualitative values, and any metric without a numeric reference range. For standard lab values with numeric ranges: "high" if value > reference_high, "low" if value < reference_low, "normal" if within range.
7. Assign clinical_group from: hematology, biochemistry, endocrine, lipids, metabolic, renal, hepatic, inflammation, iron, coagulation, urinalysis, immunology, tumor_markers, vitamins, cardiac, thyroid, hormones, cgm, general. Use "cgm" for all CGM/glucose sensor metrics (eHbA1c, MBG, TIR, LBGI, HBGI, AGP, Χρόνος κάλυψης CGM).
8. If you detect the exam date, lab name, or ordering doctor, include them in the metadata.
9. For multi-section documents (e.g., CBC + Hormones + Biochemistry in one report), extract ALL sections.
10. Handle Greek, English, or any language. Preserve original test names.
11. For each extracted result, include the approximate OCR line or snippet where you found it (ocr_snippet field) for traceability.
12. If you cannot confidently extract a value, still include the test with value_text containing what you see, and set parser_confidence to a lower value (0.3-0.6).
13. exam_date must always be returned as ISO date: YYYY-MM-DD. Never return DD/MM/YYYY, MM/DD/YYYY, DD-MM-YYYY, or localized date strings. If the date is ambiguous or cannot be confidently normalized, return null.
14. For age-stratified or time-stratified reference ranges (e.g., "3.5-5.0 (>60ετη: 3.4-4.8)", "Πρωί 7-10πμ: 133-537 / Απόγευμα 4-8μμ: 68-327", "8.8-46.3 Χειμερινή / 15.7-60.3 Καλοκαιρινή"), ALWAYS use the FIRST / most general range as reference_low and reference_high. Store the full raw string in reference_text. Never use an age-specific or time-specific sub-range as the primary range unless it is the only one given.
15. For multi-page documents where the patient header (ΟΝΟΜΑΤΕΠΩΝΥΜΟ, ΗΜΕΡ.ΕΞΕΤΑΣΗΣ) repeats on each page, treat the entire document as ONE exam from the date on the first page. Do not create duplicate metadata entries.
16. For CGM/glucose sensor reports (containing eHbA1c, MBG, TIR, LBGI, HBGI, LibreView, FreeStyle Libre, αισθητήρας γλυκόζης), set document_type to "cgm_report". CGM PERCENTAGE METRICS (TIR Φυσιολογικό, TIR Χαμηλό, TIR Υψηλό, Χρόνος κάλυψης CGM) do NOT use glucose thresholds (70 mg/dL, 180 mg/dL) as reference_low/reference_high for the PERCENTAGE value. Set reference_low=null, reference_high=null, abnormal_flag="unknown" for ALL CGM metrics. The glucose category description (e.g. "70-180 mg/dL") belongs ONLY in reference_text as a label, never as a numeric percentage boundary.
17. For CGM reports, use EXACTLY these standardized display_name values (do NOT translate or expand them):
    - "eHbA1c" (not "Εκτιμώμενη HbA1c" or any other variant)
    - "MBG" (not "Μέση Γλυκόζη" or "Mean Blood Glucose")
    - "Χρόνος κάλυψης CGM" (not "Χρόνος Κάλυψης" alone)
    - "TIR Φυσιολογικό" (not "Time in Range (TIR) (χρόνος εντός εύρους...)" or "Time in Range Φυσιολογικό")
    - "TIR Χαμηλό" (not "Χαμηλό" alone or "Time in Range Χαμηλό")
    - "TIR Υψηλό" (not "Υψηλό" alone or "Time in Range Υψηλό")
    - "LBGI" (Δείκτης Χαμηλής ΓΑ)
    - "HBGI" (Δείκτης Υψηλής ΓΑ)
18. For metric_kind, use one of: numeric_lab | qualitative | percentage_distribution | count | narrative | medication_instruction | microbiology_result
    - CGM TIR/coverage metrics → percentage_distribution
    - CGM eHbA1c/MBG/LBGI/HBGI → numeric_lab
    - Urinalysis qualitative (Αρνητικό, +, ++) → qualitative
    - Imaging/pathology findings → narrative
    - Standard lab values → numeric_lab
19. For semantic_direction, use one of: higher_is_worse | lower_is_worse | bidirectional | qualitative_map | narrative_only
    - TIR Φυσιολογικό, Χρόνος κάλυψης CGM → lower_is_worse (higher % is better)
    - TIR Χαμηλό, TIR Υψηλό, LBGI, HBGI → higher_is_worse (lower % is better)
    - MBG, eHbA1c → higher_is_worse
    - Standard lab values with reference ranges → bidirectional
    - Qualitative results → qualitative_map
    - Narrative findings → narrative_only

Respond with ONLY valid JSON matching this exact schema:
{
  "metadata": {
    "exam_date": "YYYY-MM-DD or null",
    "lab_name": "string or null",
    "ordering_doctor": "string or null",
    "document_type": "lab_panel | imaging_report | mixed_panel | cgm_report",
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
      "metric_kind": "numeric_lab",
      "semantic_direction": "bidirectional",
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


def post_validate_results(raw_results: list, report_type: str = "blood_lab_report") -> Tuple[List[ParsedResult], Dict]:
    """
    Post-validate all AI-extracted results using semantic evaluation.
    Returns validated ParsedResult list and a validation summary dict.
    
    Args:
        raw_results: list of raw result dicts from GPT extraction
        report_type: canonical report type from semantic_rules.resolve_report_type()
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

        # ---------------------------------------------------------------------------
        # CGM ARTIFACT FILTER — reject chart labels, AGP metadata, axis labels
        # These are visual/graphical elements from the CGM PDF, not clinical metrics.
        # ---------------------------------------------------------------------------
        if report_type == "cgm_report":
            _cgm_artifact_blacklist_exact = {
                # AGP chart descriptors
                "προφίλ διακύμανσης γλυκόζης (agp)",
                "προφιλ διακυμανσης γλυκοζης (agp)",
                "προφίλ διακύμανσης γλυκόζης",
                "προφιλ διακυμανσης γλυκοζης",
                "αρχεία διακύμανσης γλυκόζης (agp)",
                "αρχεια διακυμανσης γλυκοζης (agp)",
                "αρχεία διακύμανσης γλυκόζης",
                "αρχεια διακυμανσης γλυκοζης",
                # Percentile/band descriptors
                "50% διάμεσος", "50% διαμεσος",
                "διάστημα 25%-75%", "διαστημα 25%-75%",
                "διάστημα 10%-90%", "διαστημα 10%-90%",
                "25%-75% interquartile range",
                "10%-90% interdecile range",
                # Multi-day curve labels
                "πολύημερες καμπύλες γλυκόζης αίματος",
                "πολυημερες καμπυλες γλυκοζης αιματος",
                "πολύημερες καμπύλες γλυκόζης",
                "πολυημερες καμπυλες γλυκοζης",
                # Trend/date range labels
                "τάσεις", "τασεις",
                # Axis time labels (exact)
                "ώρες", "ωρες", "hours",
            }
            _cgm_artifact_blacklist_contains = [
                # AGP/chart pattern fragments
                "agp",
                "διακύμανσης", "διακυμανσης",
                "καμπύλες γλυκόζης", "καμπυλες γλυκοζης",
                "διάμεσος", "διαμεσος",
                "διάστημα", "διαστημα",
                "interquartile", "interdecile",
                # Time-axis label pattern: contains only times like "00:00, 04:00"
            ]
            _cgm_time_axis_pattern = __import__('re').compile(
                r'^[\d:,\s]+$'  # only digits, colons, commas, spaces → axis label
            )
            dn_check = display_name.lower().strip()
            # Exact blacklist match
            if dn_check in _cgm_artifact_blacklist_exact:
                summary["rejected"] += 1
                logger.debug("[CGM_FILTER] Rejected artifact (exact): %s", display_name)
                continue
            # Contains-fragment blacklist
            if any(frag in dn_check for frag in _cgm_artifact_blacklist_contains):
                summary["rejected"] += 1
                logger.debug("[CGM_FILTER] Rejected artifact (fragment): %s", display_name)
                continue
            # Time-axis label: value_text looks like "00:00, 04:00, 08:00..."
            vt = str(r.get("value_text") or "")
            if _cgm_time_axis_pattern.match(vt.replace(" ", "")):
                summary["rejected"] += 1
                logger.debug("[CGM_FILTER] Rejected time-axis artifact: %s = %s", display_name, vt)
                continue
            # Date-range value: value_text matches "DD/MM/YYYY – DD/MM/YYYY"
            _date_range_pattern = __import__('re').compile(
                r'^\d{2}/\d{2}/\d{4}\s*[–\-]\s*\d{2}/\d{2}/\d{4}$'
            )
            if _date_range_pattern.match(vt.strip()):
                summary["rejected"] += 1
                logger.debug("[CGM_FILTER] Rejected date-range artifact: %s = %s", display_name, vt)
                continue
            # Multi-value text artifact: value_text contains multiple comma-separated times
            if vt.count(":") >= 3 and vt.count(",") >= 2:
                summary["rejected"] += 1
                logger.debug("[CGM_FILTER] Rejected multi-time artifact: %s = %s", display_name, vt)
                continue

        # CGM display_name normalization — standardize names regardless of GPT output
        _cgm_name_map = {
            # eHbA1c variants
            "εκτιμώμενη hba1c": "eHbA1c", "εκτιμωμενη hba1c": "eHbA1c",
            "estimated hba1c": "eHbA1c", "ehba1c": "eHbA1c",
            # MBG variants
            "μέση γλυκόζη": "MBG", "μεση γλυκοζη": "MBG",
            "mean blood glucose": "MBG", "mean glucose": "MBG",
            "μέση τιμή γλυκόζης": "MBG", "μεση τιμη γλυκοζης": "MBG",
            # TIR Φυσιολογικό variants
            "time in range (tir) φυσιολογικό": "TIR Φυσιολογικό",
            "time in range (tir) (χρόνος εντός εύρους)": "TIR Φυσιολογικό",
            "time in range (tir) (χρονος εντος ευρους)": "TIR Φυσιολογικό",
            "time in range φυσιολογικό": "TIR Φυσιολογικό",
            "time in range φυσιολογικο": "TIR Φυσιολογικό",
            "tir φυσιολογικό": "TIR Φυσιολογικό",
            "tir φυσιολογικο": "TIR Φυσιολογικό",
            "tir (φυσιολογικό)": "TIR Φυσιολογικό",
            "φυσιολογικό (70-180 mg/dl)": "TIR Φυσιολογικό",
            "φυσιολογικο (70-180 mg/dl)": "TIR Φυσιολογικό",
            # TIR Χαμηλό variants
            "time in range (tir) χαμηλό": "TIR Χαμηλό",
            "time in range χαμηλό": "TIR Χαμηλό",
            "time in range χαμηλο": "TIR Χαμηλό",
            "tir χαμηλό": "TIR Χαμηλό",
            "tir χαμηλο": "TIR Χαμηλό",
            "tir (χαμηλό)": "TIR Χαμηλό",
            "χαμηλό (<70 mg/dl)": "TIR Χαμηλό",
            "χαμηλο (<70 mg/dl)": "TIR Χαμηλό",
            "χαμηλό": "TIR Χαμηλό",
            "χαμηλο": "TIR Χαμηλό",
            # TIR Υψηλό variants
            "time in range (tir) υψηλό": "TIR Υψηλό",
            "time in range υψηλό": "TIR Υψηλό",
            "time in range υψηλο": "TIR Υψηλό",
            "tir υψηλό": "TIR Υψηλό",
            "tir υψηλο": "TIR Υψηλό",
            "tir (υψηλό)": "TIR Υψηλό",
            "υψηλό (>180 mg/dl)": "TIR Υψηλό",
            "υψηλο (>180 mg/dl)": "TIR Υψηλό",
            "υψηλό": "TIR Υψηλό",
            "υψηλο": "TIR Υψηλό",
            # Χρόνος κάλυψης CGM variants
            "χρόνος κάλυψης": "Χρόνος κάλυψης CGM",
            "χρονος καλυψης": "Χρόνος κάλυψης CGM",
            "χρόνος κάλυψης cgm": "Χρόνος κάλυψης CGM",
            "cgm coverage": "Χρόνος κάλυψης CGM",
            "sensor coverage": "Χρόνος κάλυψης CGM",
            "αποτελέσματα αισθητήρα": "Αριθμός αποτελεσμάτων αισθητήρα",
            "αποτελεσματα αισθητηρα": "Αριθμός αποτελεσμάτων αισθητήρα",
        }
        dn_lower = display_name.lower().strip()
        # Exact match first, then prefix/contains match for TIR
        if dn_lower in _cgm_name_map:
            display_name = _cgm_name_map[dn_lower]
        elif dn_lower.startswith("time in range") and "φυσιολογικ" in dn_lower:
            display_name = "TIR Φυσιολογικό"
        elif dn_lower.startswith("time in range") and "χαμηλ" in dn_lower:
            display_name = "TIR Χαμηλό"
        elif dn_lower.startswith("time in range") and "υψηλ" in dn_lower:
            display_name = "TIR Υψηλό"
        elif dn_lower.startswith("time in range") and "tir" not in dn_lower:
            # Generic "Time in Range" without qualifier → TIR Φυσιολογικό
            display_name = "TIR Φυσιολογικό"

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

        # Clinical group — override to 'cgm' for known CGM metric names
        clinical_group = r.get("clinical_group", "general")
        _cgm_metric_keys = {
            "ehba1c", "ehba", "mbg", "tir", "cgm", "lbgi", "hbgi", "agp",
            "χρόνος κάλυψης", "χρονος καλυψης", "μέση γλυκόζη", "μεση γλυκοζη",
            "time in range", "αισθητήρας γλυκόζης",
        }
        if any(k in display_name.lower() for k in _cgm_metric_keys):
            clinical_group = "cgm"

        # Trendable
        trendable = _is_trendable(display_name)

        # Parser confidence
        raw_confidence = _safe_float(r.get("parser_confidence")) or 0.90
        # Reduce confidence if warnings exist
        if warnings:
            raw_confidence = max(0.3, raw_confidence - 0.1 * len(warnings))

        # OCR snippet for traceability
        ocr_snippet = r.get("ocr_snippet", "")

        # Semantic evaluation — use report-type-aware logic
        try:
            from exams_module.services.semantic_rules import evaluate_result as _sem_eval
            sem = _sem_eval(
                report_type=report_type,
                display_name=display_name,
                value_numeric=value_numeric,
                value_text=value_text,
                ref_low=ref_low,
                ref_high=ref_high,
                claimed_flag=validated_flag,
            )
            metric_kind = r.get("metric_kind") or sem.metric_kind
            semantic_direction = r.get("semantic_direction") or sem.semantic_direction
            evaluation_status = sem.evaluation_status
            review_reason = sem.review_reason
            disclaimer = sem.disclaimer
            # Override abnormal_flag with semantic evaluation for CGM and qualitative
            if report_type == "cgm_report" or metric_kind == "qualitative":
                if evaluation_status == "abnormal":
                    validated_flag = "H"  # use H as generic "out of target" for mobile display
                elif evaluation_status == "warning":
                    validated_flag = "H"  # show as warning in mobile
                elif evaluation_status == "normal":
                    validated_flag = "N"
        except Exception as _sem_err:
            logger.warning(f"[AI_NORMALIZER] Semantic evaluation failed for '{display_name}': {_sem_err}")
            metric_kind = r.get("metric_kind") or "numeric_lab"
            semantic_direction = r.get("semantic_direction") or "bidirectional"
            evaluation_status = "unknown"
            review_reason = ""
            disclaimer = ""

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
            metric_kind=metric_kind,
            semantic_direction=semantic_direction,
            evaluation_status=evaluation_status,
            review_reason=review_reason,
            disclaimer=disclaimer,
        ))

    return validated, summary


# ---------------------------------------------------------------------------
# Normalization Status Decision
# ---------------------------------------------------------------------------

# CGM metric names that naturally lack units/reference ranges — do not penalize
_CGM_METRIC_NAMES = {
    "tir", "time in range", "χρόνος κάλυψης", "χρονος καλυψης",
    "ehba1c", "ehba", "mbg", "μέση γλυκόζη", "μεση γλυκοζη",
    "lbgi", "hbgi", "agp", "χρόνος στόχος", "χρονος στοχος",
    "φυσιολογικό", "χαμηλό", "υψηλό",
    "αισθητήρας γλυκόζης", "αισθητηρας γλυκοζης",
}


def _is_cgm_text(text: str) -> bool:
    """Return True if the text looks like a CGM/glucose sensor report."""
    low = text.lower()
    cgm_signals = [
        "ehba1c", "ehba", "mbg", "tir", "cgm", "libreview", "freestyle libre",
        "time in range", "χρόνος κάλυψης", "χρονος καλυψης",
        "αισθητήρας γλυκόζης", "αισθητηρας γλυκοζης",
        "lbgi", "hbgi", "agp",
    ]
    return sum(1 for k in cgm_signals if k in low) >= 2


def _decide_normalization_status(results: List[ParsedResult], summary: Dict, is_cgm: bool = False, report_type: str = "blood_lab_report") -> Tuple[str, float]:
    """
    Decide normalization_status and confidence_score based on semantic evaluation results.
    Returns (status, confidence).
    
    Uses semantic evaluation_status from each result rather than generic valid/warning counts.
    CGM, imaging, and other non-lab report types get report-type-aware scoring.
    """
    total = summary.get("total_extracted", 0)
    rejected = summary.get("rejected", 0)
    missing_units = summary.get("missing_units", 0)

    if total == 0 or len(results) == 0:
        return "needs_review", 0.30

    # Count results by semantic evaluation_status
    sem_normal = sum(1 for r in results if r.evaluation_status == "normal")
    sem_warning = sum(1 for r in results if r.evaluation_status == "warning")
    sem_abnormal = sum(1 for r in results if r.evaluation_status == "abnormal")
    sem_unknown = sum(1 for r in results if r.evaluation_status in ("unknown", "needs_review"))
    sem_evaluated = sem_normal + sem_warning + sem_abnormal  # results with definitive evaluation

    n_results = len(results)

    # --- Imaging / narrative reports: no numeric evaluation possible ---
    if report_type in ("imaging_report", "pathology_report", "microbiology_report",
                       "medication_plan", "generic_medical_document"):
        # These always need human review regardless of extraction quality
        return "needs_review", 0.50

    # --- CGM reports: use semantic evaluation ratio ---
    if is_cgm or report_type == "cgm_report":
        # CGM metrics are well-defined; if we extracted them, we can evaluate them
        if n_results >= 3:
            # Good extraction: enough metrics to be representative
            evaluation_ratio = sem_evaluated / n_results
            if evaluation_ratio >= 0.6:
                return "auto_verified", round(min(0.92, 0.80 + evaluation_ratio * 0.15), 4)
            return "auto_verified", round(0.78, 4)
        elif n_results >= 1:
            return "auto_verified", round(0.75, 4)
        return "needs_review", 0.30

    # --- Standard lab reports: semantic-aware scoring ---
    # Base quality: ratio of results with definitive evaluation
    evaluation_ratio = sem_evaluated / max(n_results, 1)
    # Penalize for missing units (indicates poor OCR or extraction)
    unit_penalty = min(0.15, missing_units * 0.03)
    # Penalize for high unknown ratio
    unknown_penalty = min(0.10, (sem_unknown / max(n_results, 1)) * 0.15)

    base_score = evaluation_ratio - unit_penalty - unknown_penalty

    if base_score >= 0.75:
        return "auto_verified", round(min(0.95, 0.82 + base_score * 0.12), 4)
    if base_score >= 0.45:
        return "auto_verified", round(min(0.85, 0.68 + base_score * 0.15), 4)

    # Low quality
    return "needs_review", round(max(0.30, 0.40 + base_score * 0.20), 4)


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

    # Step 2b: Detect if this is a CGM report (by GPT-returned type OR text heuristic)
    # This ensures correct exam_type even if GPT didn't return "cgm_report"
    is_cgm = (doc_type == "cgm_report") or _is_cgm_text(
        " ".join(r.get("display_name", "") for r in ai_response.get("results", []))
    )
    if is_cgm and doc_type not in ("cgm_report",):
        logger.info("[AI_NORMALIZER] CGM text detected via heuristic — overriding doc_type to cgm_report")
        doc_type = "cgm_report"

    # Step 2c: Resolve canonical report_type for semantic evaluation
    try:
        from exams_module.services.semantic_rules import resolve_report_type
        report_type = resolve_report_type(doc_type)
    except Exception:
        report_type = "cgm_report" if is_cgm else "blood_lab_report"

    # Step 3: Post-validate all results using semantic evaluation
    raw_results = ai_response.get("results", [])
    validated_results, validation_summary = post_validate_results(raw_results, report_type=report_type)

    # Step 4: Process impressions
    impressions = []
    for imp in ai_response.get("impressions", []):
        impressions.append(ParsedImpression(
            section_type=imp.get("section_type", "narrative"),
            text=imp.get("text", ""),
            severity_flag=imp.get("severity_flag", "unknown"),
            review_required=imp.get("severity_flag") in ("attention", "critical"),
        ))

    # Step 5: Decide normalization status using semantic evaluation
    normalization_status, confidence_score = _decide_normalization_status(
        validated_results, validation_summary, is_cgm=is_cgm, report_type=report_type
    )

    # Step 5b: AGP-only detection — set report-level guidance when CGM has 0 results
    # but OCR contained AGP/chart artifacts (image was a chart, not a numeric summary)
    report_review_reason = ""
    if is_cgm and len(validated_results) == 0:
        _agp_indicators = [
            "agp", "\u03b4\u03b9\u03b1\u03ba\u03cd\u03bc\u03b1\u03bd\u03c3\u03b7\u03c2", "\u03b4\u03b9\u03b1\u03ba\u03c5\u03bc\u03b1\u03bd\u03c3\u03b7\u03c2",
            "\u03b4\u03b9\u03ac\u03bc\u03b5\u03c3\u03bf\u03c2", "\u03b4\u03b9\u03b1\u03bc\u03b5\u03c3\u03bf\u03c2", "\u03b4\u03b9\u03ac\u03c3\u03c4\u03b7\u03bc\u03b1", "\u03b4\u03b9\u03b1\u03c3\u03c4\u03b7\u03bc\u03b1",
            "\u03c0\u03bf\u03bb\u03cd\u03b7\u03bc\u03b5\u03c1\u03b5\u03c2", "\u03c0\u03bf\u03bb\u03c5\u03b7\u03bc\u03b5\u03c1\u03b5\u03c2", "\u03c4\u03ac\u03c3\u03b5\u03b9\u03c2", "\u03c4\u03b1\u03c3\u03b5\u03b9\u03c2",
            "interquartile", "interdecile",
        ]
        raw_text_lower = text.lower() if text else ""
        if any(ind in raw_text_lower for ind in _agp_indicators):
            report_review_reason = (
                "\u0397 \u03b5\u03b9\u03ba\u03cc\u03bd\u03b1 \u03c6\u03b1\u03af\u03bd\u03b5\u03c4\u03b1\u03b9 \u03bd\u03b1 \u03c0\u03b5\u03c1\u03b9\u03ad\u03c7\u03b5\u03b9 \u03ba\u03c5\u03c1\u03af\u03c9\u03c2 \u03b3\u03c1\u03ac\u03c6\u03b7\u03bc\u03b1 AGP/\u03c4\u03ac\u03c3\u03b5\u03c9\u03bd \u03ba\u03b1\u03b9 \u03cc\u03c7\u03b9 \u03b1\u03c1\u03b9\u03b8\u03bc\u03b7\u03c4\u03b9\u03ba\u03ad\u03c2 \u03bc\u03b5\u03c4\u03c1\u03ae\u03c3\u03b5\u03b9\u03c2. "
                "\u0393\u03b9\u03b1 \u03c0\u03bb\u03ae\u03c1\u03b7 \u03b1\u03bd\u03ac\u03bb\u03c5\u03c3\u03b7, \u03b1\u03bd\u03ad\u03b2\u03b1\u03c3\u03b5 \u03c4\u03b7\u03bd \u03bf\u03b8\u03cc\u03bd\u03b7 \u03ae \u03c4\u03bf PDF \u03c0\u03bf\u03c5 \u03c0\u03b5\u03c1\u03b9\u03ad\u03c7\u03b5\u03b9 \u03a7\u03c1\u03cc\u03bd\u03bf \u03ba\u03ac\u03bb\u03c5\u03c8\u03b7\u03c2 CGM, eHbA1c, MBG \u03ba\u03b1\u03b9 Time in Range."
            )
            logger.info("[AI_NORMALIZER] AGP-only CGM detected \u2014 set report_review_reason guidance")

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
        exam_type=doc_type if doc_type not in ("mixed_panel",) else "lab_panel",
        exam_category="lab",
        confidence_score=confidence_score,
        normalization_status=normalization_status,
        source_lineage=source_lineage,
        results=validated_results,
        impressions=impressions,
        performed_at=performed_at,
        lab_name=lab_name,
        ordering_doctor=ordering_doctor,
        validation_summary=validation_summary,
        report_review_reason=report_review_reason,
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

    # Recalculate confidence and status (detect CGM from merged exam_type)
    is_cgm_merged = getattr(base, 'exam_type', '') == 'cgm_report'
    norm_status, confidence = _decide_normalization_status(deduped, base.validation_summary, is_cgm=is_cgm_merged)
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

    if label in ("lab", "cgm"):
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
