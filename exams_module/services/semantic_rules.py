"""
Autoanosis Exams — Semantic Interpretation Layer v1.0.0
========================================================
Provides report-type-aware evaluation semantics.

Architecture:
  OCR → classify_document() → semantic_rules.evaluate_result()
                                        ↓
                            metric_kind + semantic_direction
                                        ↓
                            evaluation_status (normal/warning/abnormal/unknown/needs_review)

This module is the ONLY place that decides whether a value is "normal" or "abnormal".
It must never use generic numeric comparison alone — it must know the report type and
metric semantics before making any clinical judgment.

Report types supported:
  - blood_lab_report     : standard numeric lab values with reference ranges
  - cgm_report           : CGM/glucose sensor percentage and numeric metrics
  - urinalysis           : qualitative + semi-quantitative urine results
  - imaging_report       : narrative findings, no numeric normal/abnormal logic
  - microbiology_report  : organism, culture, antibiogram
  - pathology_report     : diagnosis text, high caution
  - cardiology_report    : ECG, echo, Holter findings
  - medication_plan      : drug, dose, frequency, route
  - generic_medical_document : unknown type, always needs_review

Safety rule:
  If report type or metric semantics are uncertain → needs_review, never confident normal/abnormal.
"""

from dataclasses import dataclass, field
from typing import Optional, Tuple


# ---------------------------------------------------------------------------
# Metric kinds
# ---------------------------------------------------------------------------

METRIC_KIND_NUMERIC_LAB = "numeric_lab"
METRIC_KIND_QUALITATIVE = "qualitative"
METRIC_KIND_PERCENTAGE_DISTRIBUTION = "percentage_distribution"
METRIC_KIND_COUNT = "count"
METRIC_KIND_NARRATIVE = "narrative"
METRIC_KIND_MEDICATION = "medication_instruction"
METRIC_KIND_MICROBIOLOGY = "microbiology_result"

# ---------------------------------------------------------------------------
# Semantic directions
# ---------------------------------------------------------------------------

DIR_HIGHER_IS_WORSE = "higher_is_worse"   # e.g. CRP, creatinine, TIR Υψηλό
DIR_LOWER_IS_WORSE  = "lower_is_worse"    # e.g. hemoglobin, TIR Φυσιολογικό
DIR_HIGHER_IS_BETTER = "higher_is_better" # alias for lower_is_worse (same logic)
DIR_LOWER_IS_BETTER  = "lower_is_better"  # alias for higher_is_worse (same logic)
DIR_BIDIRECTIONAL   = "bidirectional"     # normal range, both sides matter (most lab values)
DIR_QUALITATIVE_MAP = "qualitative_map"   # pass/fail/trace/+/++/+++ etc.
DIR_NARRATIVE_ONLY  = "narrative_only"    # no numeric evaluation at all

# ---------------------------------------------------------------------------
# Evaluation statuses
# ---------------------------------------------------------------------------

STATUS_NORMAL      = "normal"
STATUS_WARNING     = "warning"
STATUS_ABNORMAL    = "abnormal"
STATUS_UNKNOWN     = "unknown"
STATUS_NEEDS_REVIEW = "needs_review"

# ---------------------------------------------------------------------------
# CGM-specific semantic rules
# ---------------------------------------------------------------------------

# Each entry: (metric_kind, semantic_direction, warning_threshold, abnormal_threshold, better_direction_note)
# For percentage_distribution metrics, thresholds are on the percentage value itself.
#
# Clinical targets for adults with diabetes (ADA/EASD consensus 2019/2023):
#   TIR Φυσιολογικό (70-180 mg/dL): target ≥70%  → below 70% = warning, below 50% = abnormal
#   TIR Χαμηλό (<70 mg/dL):         target <4%   → 4-10% = warning, >10% = abnormal
#   TIR Υψηλό (>180 mg/dL):         target <25%  → 25-50% = warning, >50% = abnormal
#   eHbA1c:                          target <7%   → 7-8% = warning, >8% = abnormal (for most adults)
#   MBG:                             target 70-180 mg/dL → outside = warning
#   Χρόνος κάλυψης CGM:             target ≥70%  → below 70% = warning
#   LBGI:                            target <1.1  → 1.1-2.5 = warning, >2.5 = abnormal (hypoglycemia risk)
#   HBGI:                            target <4.5  → 4.5-9.0 = warning, >9.0 = abnormal (hyperglycemia risk)

CGM_METRIC_RULES = {
    # (display_name_lower): (metric_kind, semantic_direction, warn_fn, abnormal_fn, review_reason_if_abnormal)
    "tir φυσιολογικό": (
        METRIC_KIND_PERCENTAGE_DISTRIBUTION,
        DIR_LOWER_IS_WORSE,
        lambda v: v < 70,    # warning if below 70%
        lambda v: v < 50,    # abnormal if below 50%
        "Χρόνος εντός φυσιολογικού εύρους κάτω από στόχο (≥70%)",
    ),
    "tir χαμηλό": (
        METRIC_KIND_PERCENTAGE_DISTRIBUTION,
        DIR_HIGHER_IS_WORSE,
        lambda v: v >= 4,    # warning if ≥4% (above target <4%)
        lambda v: v >= 10,   # abnormal if ≥10%
        "Αυξημένος χρόνος υπογλυκαιμίας (<70 mg/dL) — πιθανό hypoglycemia risk",
    ),
    "tir υψηλό": (
        METRIC_KIND_PERCENTAGE_DISTRIBUTION,
        DIR_HIGHER_IS_WORSE,
        lambda v: v >= 25,   # warning if ≥25%
        lambda v: v >= 50,   # abnormal if ≥50%
        "Αυξημένος χρόνος υπεργλυκαιμίας (>180 mg/dL)",
    ),
    "ehba1c": (
        METRIC_KIND_NUMERIC_LAB,
        DIR_HIGHER_IS_WORSE,
        lambda v: v >= 7.0,  # warning if ≥7%
        lambda v: v >= 8.0,  # abnormal if ≥8%
        "Εκτιμώμενη HbA1c πάνω από στόχο",
    ),
    "mbg": (
        METRIC_KIND_NUMERIC_LAB,
        DIR_BIDIRECTIONAL,
        lambda v: v < 70 or v > 180,   # warning outside 70-180
        lambda v: v < 54 or v > 250,   # abnormal outside 54-250
        "Μέση γλυκόζη εκτός φυσιολογικού εύρους",
    ),
    "χρόνος κάλυψης cgm": (
        METRIC_KIND_PERCENTAGE_DISTRIBUTION,
        DIR_LOWER_IS_WORSE,
        lambda v: v < 70,    # warning if below 70%
        lambda v: v < 50,    # abnormal if below 50%
        "Ανεπαρκής χρόνος κάλυψης αισθητήρα — τα δεδομένα ενδέχεται να μην είναι αντιπροσωπευτικά",
    ),
    "lbgi": (
        METRIC_KIND_NUMERIC_LAB,
        DIR_HIGHER_IS_WORSE,
        lambda v: v >= 1.1,  # warning if ≥1.1 (moderate hypoglycemia risk)
        lambda v: v >= 2.5,  # abnormal if ≥2.5 (high hypoglycemia risk)
        "Αυξημένος δείκτης κινδύνου υπογλυκαιμίας (LBGI)",
    ),
    "hbgi": (
        METRIC_KIND_NUMERIC_LAB,
        DIR_HIGHER_IS_WORSE,
        lambda v: v >= 4.5,  # warning
        lambda v: v >= 9.0,  # abnormal
        "Αυξημένος δείκτης κινδύνου υπεργλυκαιμίας (HBGI)",
    ),
    "αριθμός αποτελεσμάτων αισθητήρα": (
        METRIC_KIND_COUNT,
        DIR_NARRATIVE_ONLY,
        lambda v: False,
        lambda v: False,
        "",
    ),
}

# Aliases for CGM metric lookup
_CGM_ALIASES = {
    "tir φυσιολογικο": "tir φυσιολογικό",
    "time in range φυσιολογικό": "tir φυσιολογικό",
    "time in range φυσιολογικο": "tir φυσιολογικό",
    "time in range (tir) φυσιολογικό": "tir φυσιολογικό",
    "time in range (tir) φυσιολογικο": "tir φυσιολογικό",
    "tir χαμηλο": "tir χαμηλό",
    "time in range χαμηλό": "tir χαμηλό",
    "time in range χαμηλο": "tir χαμηλό",
    "time in range (tir) χαμηλό": "tir χαμηλό",
    "time in range (tir) χαμηλο": "tir χαμηλό",
    "χαμηλό": "tir χαμηλό",   # bare "Χαμηλό" in CGM context
    "χαμηλο": "tir χαμηλό",
    "tir υψηλο": "tir υψηλό",
    "time in range υψηλό": "tir υψηλό",
    "time in range υψηλο": "tir υψηλό",
    "time in range (tir) υψηλό": "tir υψηλό",
    "time in range (tir) υψηλο": "tir υψηλό",
    "υψηλό": "tir υψηλό",     # bare "Υψηλό" in CGM context
    "υψηλο": "tir υψηλό",
    "ehba": "ehba1c",
    "ehba1c": "ehba1c",
    "χρόνος κάλυψης": "χρόνος κάλυψης cgm",
    "χρονος καλυψης": "χρόνος κάλυψης cgm",
    "χρονος καλυψης cgm": "χρόνος κάλυψης cgm",
    # LBGI / HBGI aliases
    "δείκτης χαμηλής γα (lbgi)": "lbgi",
    "δεικτης χαμηλης γα (lbgi)": "lbgi",
    "δείκτης χαμηλής γλυκαιμίας": "lbgi",
    "δείκτης υψηλής γα (hbgi)": "hbgi",
    "δεικτης υψηλης γα (hbgi)": "hbgi",
    "δείκτης υψηλής γλυκαιμίας": "hbgi",
    # Sensor count aliases
    "αποτελέσματα αισθητήρα": "αριθμός αποτελεσμάτων αισθητήρα",
    "αποτελεσματα αισθητηρα": "αριθμός αποτελεσμάτων αισθητήρα",
    "sensor readings": "αριθμός αποτελεσμάτων αισθητήρα",
    "sensor results": "αριθμός αποτελεσμάτων αισθητήρα",
}


def _lookup_cgm_rule(display_name: str):
    """Return the CGM semantic rule tuple for a display_name, or None if not found."""
    key = display_name.lower().strip()
    key = _CGM_ALIASES.get(key, key)
    return CGM_METRIC_RULES.get(key)


# ---------------------------------------------------------------------------
# Qualitative evaluation maps (urinalysis etc.)
# ---------------------------------------------------------------------------

# Urinalysis qualitative results that are always "normal"
URINALYSIS_NORMAL_QUALITATIVE = {
    "αρνητικό", "αρνητικο", "negative", "neg", "absent", "απόν", "απον",
    "φυσιολογικό", "φυσιολογικο", "normal", "clear", "καθαρό", "καθαρο",
    "ναι", "yes", "παρόν", "παρον",  # for things like "Χρώμα: Κίτρινο" → normal
}

URINALYSIS_ABNORMAL_QUALITATIVE = {
    "θετικό", "θετικο", "positive", "pos",
    "+", "++", "+++", "++++",
    "ίχνη", "ιχνη", "trace",
    "πολλά", "πολλα", "many", "numerous",
    "μέτρια", "μετρια", "moderate",
}

# ---------------------------------------------------------------------------
# Main evaluation function
# ---------------------------------------------------------------------------

@dataclass
class SemanticEvaluation:
    """Result of semantic evaluation for a single extracted result."""
    metric_kind: str = METRIC_KIND_NUMERIC_LAB
    semantic_direction: str = DIR_BIDIRECTIONAL
    evaluation_status: str = STATUS_UNKNOWN
    review_reason: str = ""
    disclaimer: str = ""
    # Overridden reference range (for CGM, these are clinical targets not lab ranges)
    clinical_target_low: Optional[float] = None
    clinical_target_high: Optional[float] = None


def evaluate_result(
    report_type: str,
    display_name: str,
    value_numeric: Optional[float],
    value_text: Optional[str],
    ref_low: Optional[float],
    ref_high: Optional[float],
    claimed_flag: str = "unknown",
) -> SemanticEvaluation:
    """
    Evaluate a single extracted result using report-type-aware semantics.

    This is the SINGLE SOURCE OF TRUTH for clinical evaluation.
    Never use generic numeric comparison outside this function.

    Args:
        report_type: one of the REPORT_TYPE_* constants
        display_name: standardized display name of the metric
        value_numeric: numeric value if available
        value_text: text value if non-numeric
        ref_low: reference range lower bound (from GPT extraction)
        ref_high: reference range upper bound (from GPT extraction)
        claimed_flag: abnormal flag claimed by GPT ("normal", "high", "low", "unknown")

    Returns:
        SemanticEvaluation with metric_kind, semantic_direction, evaluation_status, review_reason
    """

    # --- CGM reports ---
    if report_type == "cgm_report":
        return _evaluate_cgm(display_name, value_numeric, value_text)

    # --- Imaging reports ---
    if report_type == "imaging_report":
        return SemanticEvaluation(
            metric_kind=METRIC_KIND_NARRATIVE,
            semantic_direction=DIR_NARRATIVE_ONLY,
            evaluation_status=STATUS_NEEDS_REVIEW,
            review_reason="Απεικονιστική εξέταση — απαιτείται ιατρική ερμηνεία",
            disclaimer="Η αξιολόγηση απεικονιστικών ευρημάτων απαιτεί ιατρό.",
        )

    # --- Medication plans ---
    if report_type == "medication_plan":
        return SemanticEvaluation(
            metric_kind=METRIC_KIND_MEDICATION,
            semantic_direction=DIR_NARRATIVE_ONLY,
            evaluation_status=STATUS_NEEDS_REVIEW,
            review_reason="Σχέδιο φαρμακευτικής αγωγής — απαιτείται ιατρός",
            disclaimer="Μην αλλάζετε δοσολογία χωρίς συνεννόηση με γιατρό.",
        )

    # --- Pathology reports ---
    if report_type == "pathology_report":
        return SemanticEvaluation(
            metric_kind=METRIC_KIND_NARRATIVE,
            semantic_direction=DIR_NARRATIVE_ONLY,
            evaluation_status=STATUS_NEEDS_REVIEW,
            review_reason="Παθολογοανατομική εξέταση — απαιτείται ιατρός",
            disclaimer="Παθολογοανατομικά ευρήματα απαιτούν πάντα ιατρική αξιολόγηση.",
        )

    # --- Microbiology reports ---
    if report_type == "microbiology_report":
        return SemanticEvaluation(
            metric_kind=METRIC_KIND_MICROBIOLOGY,
            semantic_direction=DIR_NARRATIVE_ONLY,
            evaluation_status=STATUS_NEEDS_REVIEW,
            review_reason="Μικροβιολογική εξέταση — απαιτείται ιατρός",
            disclaimer="Αντιβιόγραμμα και αποτελέσματα καλλιέργειας απαιτούν ιατρική αξιολόγηση.",
        )

    # --- Urinalysis ---
    if report_type == "urinalysis":
        return _evaluate_urinalysis(display_name, value_numeric, value_text, ref_low, ref_high)

    # --- Generic / unknown ---
    if report_type == "generic_medical_document":
        return SemanticEvaluation(
            metric_kind=METRIC_KIND_NARRATIVE,
            semantic_direction=DIR_NARRATIVE_ONLY,
            evaluation_status=STATUS_NEEDS_REVIEW,
            review_reason="Άγνωστος τύπος εξέτασης — απαιτείται ιατρική επιβεβαίωση",
            disclaimer="Η αξιολόγηση βασίζεται σε γενικούς στόχους και χρειάζεται επιβεβαίωση από γιατρό.",
        )

    # --- Standard blood lab report (blood_lab_report, lab_panel) ---
    return _evaluate_lab(display_name, value_numeric, value_text, ref_low, ref_high, claimed_flag)


def _evaluate_cgm(
    display_name: str,
    value_numeric: Optional[float],
    value_text: Optional[str],
) -> SemanticEvaluation:
    """CGM-specific semantic evaluation."""
    rule = _lookup_cgm_rule(display_name)

    if rule is None:
        # Unknown CGM metric — don't guess
        return SemanticEvaluation(
            metric_kind=METRIC_KIND_NUMERIC_LAB,
            semantic_direction=DIR_NARRATIVE_ONLY,
            evaluation_status=STATUS_NEEDS_REVIEW,
            review_reason="Άγνωστη CGM μέτρηση — απαιτείται επιβεβαίωση",
            disclaimer="Η αξιολόγηση βασίζεται σε γενικούς στόχους CGM και χρειάζεται επιβεβαίωση από γιατρό.",
        )

    metric_kind, semantic_direction, warn_fn, abnormal_fn, review_reason = rule

    # Count/narrative metrics — no evaluation
    if semantic_direction == DIR_NARRATIVE_ONLY:
        return SemanticEvaluation(
            metric_kind=metric_kind,
            semantic_direction=semantic_direction,
            evaluation_status=STATUS_UNKNOWN,
            review_reason="",
            disclaimer="",
        )

    if value_numeric is None:
        return SemanticEvaluation(
            metric_kind=metric_kind,
            semantic_direction=semantic_direction,
            evaluation_status=STATUS_NEEDS_REVIEW,
            review_reason="Δεν βρέθηκε αριθμητική τιμή",
            disclaimer="Η αξιολόγηση βασίζεται σε γενικούς στόχους CGM και χρειάζεται επιβεβαίωση από γιατρό.",
        )

    try:
        is_abnormal = abnormal_fn(value_numeric)
        is_warning = warn_fn(value_numeric) and not is_abnormal
    except Exception:
        return SemanticEvaluation(
            metric_kind=metric_kind,
            semantic_direction=semantic_direction,
            evaluation_status=STATUS_NEEDS_REVIEW,
            review_reason="Σφάλμα αξιολόγησης",
            disclaimer="Η αξιολόγηση βασίζεται σε γενικούς στόχους CGM και χρειάζεται επιβεβαίωση από γιατρό.",
        )

    if is_abnormal:
        status = STATUS_ABNORMAL
    elif is_warning:
        status = STATUS_WARNING
    else:
        status = STATUS_NORMAL

    return SemanticEvaluation(
        metric_kind=metric_kind,
        semantic_direction=semantic_direction,
        evaluation_status=status,
        review_reason=review_reason if status != STATUS_NORMAL else "",
        disclaimer="Η αξιολόγηση βασίζεται σε γενικούς στόχους CGM και χρειάζεται επιβεβαίωση από γιατρό.",
    )


def _evaluate_urinalysis(
    display_name: str,
    value_numeric: Optional[float],
    value_text: Optional[str],
    ref_low: Optional[float],
    ref_high: Optional[float],
) -> SemanticEvaluation:
    """Urinalysis-specific evaluation: qualitative + semi-quantitative."""
    if value_text:
        vt = value_text.lower().strip()
        if vt in URINALYSIS_NORMAL_QUALITATIVE:
            return SemanticEvaluation(
                metric_kind=METRIC_KIND_QUALITATIVE,
                semantic_direction=DIR_QUALITATIVE_MAP,
                evaluation_status=STATUS_NORMAL,
            )
        if vt in URINALYSIS_ABNORMAL_QUALITATIVE:
            return SemanticEvaluation(
                metric_kind=METRIC_KIND_QUALITATIVE,
                semantic_direction=DIR_QUALITATIVE_MAP,
                evaluation_status=STATUS_ABNORMAL,
                review_reason=f"Ποιοτικό αποτέλεσμα: {value_text}",
            )
        # Unknown qualitative value
        return SemanticEvaluation(
            metric_kind=METRIC_KIND_QUALITATIVE,
            semantic_direction=DIR_QUALITATIVE_MAP,
            evaluation_status=STATUS_NEEDS_REVIEW,
            review_reason=f"Ποιοτικό αποτέλεσμα χρειάζεται ερμηνεία: {value_text}",
        )

    # Numeric urinalysis (pH, specific gravity, RBC/WBC per HPF, etc.)
    if value_numeric is not None and ref_low is not None and ref_high is not None:
        if value_numeric < ref_low:
            return SemanticEvaluation(
                metric_kind=METRIC_KIND_NUMERIC_LAB,
                semantic_direction=DIR_BIDIRECTIONAL,
                evaluation_status=STATUS_ABNORMAL,
                review_reason="Τιμή κάτω από φυσιολογικά όρια",
            )
        if value_numeric > ref_high:
            return SemanticEvaluation(
                metric_kind=METRIC_KIND_NUMERIC_LAB,
                semantic_direction=DIR_BIDIRECTIONAL,
                evaluation_status=STATUS_ABNORMAL,
                review_reason="Τιμή πάνω από φυσιολογικά όρια",
            )
        return SemanticEvaluation(
            metric_kind=METRIC_KIND_NUMERIC_LAB,
            semantic_direction=DIR_BIDIRECTIONAL,
            evaluation_status=STATUS_NORMAL,
        )

    return SemanticEvaluation(
        metric_kind=METRIC_KIND_QUALITATIVE,
        semantic_direction=DIR_QUALITATIVE_MAP,
        evaluation_status=STATUS_NEEDS_REVIEW,
        review_reason="Ανεπαρκή δεδομένα για αξιολόγηση",
    )


def _evaluate_lab(
    display_name: str,
    value_numeric: Optional[float],
    value_text: Optional[str],
    ref_low: Optional[float],
    ref_high: Optional[float],
    claimed_flag: str = "unknown",
) -> SemanticEvaluation:
    """Standard blood lab evaluation using reference ranges."""
    # Qualitative result (text only, no numeric)
    if value_numeric is None and value_text:
        vt = value_text.lower().strip()
        if any(k in vt for k in ("αρνητικ", "negative", "neg", "absent")):
            return SemanticEvaluation(
                metric_kind=METRIC_KIND_QUALITATIVE,
                semantic_direction=DIR_QUALITATIVE_MAP,
                evaluation_status=STATUS_NORMAL,
            )
        if any(k in vt for k in ("θετικ", "positive", "pos", "ίχνη", "ιχνη", "trace", "+", "detected")):
            return SemanticEvaluation(
                metric_kind=METRIC_KIND_QUALITATIVE,
                semantic_direction=DIR_QUALITATIVE_MAP,
                evaluation_status=STATUS_ABNORMAL,
                review_reason=f"Ποιοτικό αποτέλεσμα: {value_text}",
            )
        return SemanticEvaluation(
            metric_kind=METRIC_KIND_QUALITATIVE,
            semantic_direction=DIR_QUALITATIVE_MAP,
            evaluation_status=STATUS_NEEDS_REVIEW,
            review_reason=f"Ποιοτικό αποτέλεσμα χρειάζεται ερμηνεία: {value_text}",
        )

    # No numeric value and no text
    if value_numeric is None:
        return SemanticEvaluation(
            metric_kind=METRIC_KIND_NUMERIC_LAB,
            semantic_direction=DIR_BIDIRECTIONAL,
            evaluation_status=STATUS_NEEDS_REVIEW,
            review_reason="Δεν βρέθηκε τιμή",
        )

    # No reference range → cannot evaluate
    if ref_low is None and ref_high is None:
        # Trust GPT's claimed flag if it said normal/high/low
        _flag_map = {
            "normal": STATUS_NORMAL, "n": STATUS_NORMAL,
            "high": STATUS_ABNORMAL, "h": STATUS_ABNORMAL, "hh": STATUS_ABNORMAL,
            "low": STATUS_ABNORMAL, "l": STATUS_ABNORMAL, "ll": STATUS_ABNORMAL,
        }
        status = _flag_map.get((claimed_flag or "").lower(), STATUS_UNKNOWN)
        return SemanticEvaluation(
            metric_kind=METRIC_KIND_NUMERIC_LAB,
            semantic_direction=DIR_BIDIRECTIONAL,
            evaluation_status=status,
            review_reason="Δεν υπάρχουν τιμές αναφοράς" if status == STATUS_UNKNOWN else "",
        )

    # Standard bidirectional comparison
    if ref_low is not None and value_numeric < ref_low:
        return SemanticEvaluation(
            metric_kind=METRIC_KIND_NUMERIC_LAB,
            semantic_direction=DIR_BIDIRECTIONAL,
            evaluation_status=STATUS_ABNORMAL,
            review_reason="Τιμή κάτω από φυσιολογικά όρια",
        )
    if ref_high is not None and value_numeric > ref_high:
        return SemanticEvaluation(
            metric_kind=METRIC_KIND_NUMERIC_LAB,
            semantic_direction=DIR_BIDIRECTIONAL,
            evaluation_status=STATUS_ABNORMAL,
            review_reason="Τιμή πάνω από φυσιολογικά όρια",
        )
    return SemanticEvaluation(
        metric_kind=METRIC_KIND_NUMERIC_LAB,
        semantic_direction=DIR_BIDIRECTIONAL,
        evaluation_status=STATUS_NORMAL,
    )


# ---------------------------------------------------------------------------
# Map document_type strings to canonical report_type
# ---------------------------------------------------------------------------

DOCUMENT_TYPE_TO_REPORT_TYPE = {
    "lab_results": "blood_lab_report",
    "lab_panel": "blood_lab_report",
    "blood_lab_report": "blood_lab_report",
    "cgm_report": "cgm_report",
    "glucose_sensor_report": "cgm_report",
    "imaging_report": "imaging_report",
    "mixed_panel": "blood_lab_report",   # treat mixed as lab, evaluate per metric
    "urinalysis": "urinalysis",
    "urine_report": "urinalysis",
    "urine_test": "urinalysis",
    "microbiology_report": "microbiology_report",
    "pathology_report": "pathology_report",
    "cardiology_report": "imaging_report",  # narrative-based
    "medication_plan": "medication_plan",
    "prescription": "medication_plan",
    "prescription_or_treatment_plan": "medication_plan",
    "medical_certificate": "generic_medical_document",
    "medical_opinion": "generic_medical_document",
    "hospital_discharge": "generic_medical_document",
    "graph_or_chart_only": "generic_medical_document",
    "administrative_health_document": "generic_medical_document",
    "unknown_needs_review": "generic_medical_document",
    "generic_medical_document": "generic_medical_document",
}


def resolve_report_type(document_type: str) -> str:
    """Convert a raw document_type string to a canonical report_type."""
    return DOCUMENT_TYPE_TO_REPORT_TYPE.get(
        (document_type or "").lower().strip(),
        "generic_medical_document"
    )
