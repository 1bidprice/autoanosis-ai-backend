"""
Autoanosis Exams Normalizer — v2.1.0
Fixes:
  - v2.0.0: Expanded LAB_PATTERNS to cover Greek lab report formats
  - v2.0.0: Expanded classify_document to detect Greek-only lab reports
  - v2.0.0: Imaging reports with parsed impressions now get auto_verified (not needs_review)
  - v2.0.0: normalize_document now returns a needs_review ParsedReport for unknown docs
    instead of None, so they are still stored and visible after manual review
  - v2.1.0: Urinalysis Recognition Layer
    * classify_document now returns 'urine' for Γενική Ούρων / urinalysis documents
    * URINALYSIS_PATTERNS: regex patterns for qualitative urinalysis values
      (ΟΧΙ, ΑΡΝΗΤΙΚΟ, ΘΕΤΙΚΟ, ΔΙΑΥΓΗΣ, ΚΙΤΡΙΝΗ, 0-1/ΟΠ, numeric pH/SG)
    * QUALITATIVE_STATUS_MAP: maps qualitative strings to abnormal_flag
    * parse_urine_document: dedicated parser for urinalysis reports
    * _group: added 'urinalysis' group for all urinalysis analytes
    * Confidence scoring: qualitative results do not penalise confidence
      (absence of numeric value / units is expected for urinalysis)
"""
import re
from dataclasses import dataclass
from typing import List, Dict, Tuple

TRENDABLE = {
    "CRP", "ESR", "TSH", "Vitamin D", "Ferritin",
    "WBC", "RBC", "HGB", "PLT",
    "ΤΚΕ",
}

# ---------------------------------------------------------------------------
# Qualitative value normalisation for urinalysis
# ---------------------------------------------------------------------------
# Maps raw OCR/text strings → abnormal_flag
# "normal" = expected negative / within normal range
# "high"   = unexpected positive / abnormal finding
# "unknown" = cannot determine
QUALITATIVE_STATUS_MAP: Dict[str, str] = {
    # Negative / absent — normal
    "οχι": "normal",
    "αρνητικο": "normal",
    "αρνητικά": "normal",
    "αρνητικα": "normal",
    "negative": "normal",
    "neg": "normal",
    "absent": "normal",
    "-": "normal",
    # Positive / present — abnormal
    "ναι": "high",
    "θετικο": "high",
    "θετικά": "high",
    "θετικα": "high",
    "positive": "high",
    "pos": "high",
    "present": "high",
    "+": "high",
    "++": "high",
    "+++": "high",
    # Appearance — normal values
    "διαυγης": "normal",
    "διαυγής": "normal",
    "clear": "normal",
    "κιτρινη": "normal",
    "κιτρινή": "normal",
    "yellow": "normal",
    "ανοιχτοκιτρινη": "normal",
    "ανοιχτοκίτρινη": "normal",
    "pale yellow": "normal",
    # Appearance — potentially abnormal
    "θολη": "high",
    "θολή": "high",
    "turbid": "high",
    "cloudy": "high",
    "κοκκινη": "high",
    "κόκκινη": "high",
    "red": "high",
    "ροζ": "high",
    "πορτοκαλι": "high",
    # Semi-quantitative (cells per high-power field)
    "0-1/οπ": "normal",
    "0-2/οπ": "normal",
    "1-2/οπ": "normal",
    "2-3/οπ": "high",
    "3-5/οπ": "high",
    "5-10/οπ": "high",
    ">10/οπ": "high",
    "0-1/hpf": "normal",
    "0-2/hpf": "normal",
    "1-2/hpf": "normal",
    "2-3/hpf": "high",
    "3-5/hpf": "high",
}


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
    parser_confidence: float = 0.95


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


def detect_garbage_text(text: str) -> Tuple[bool, str]:
    t = (text or "").strip()
    if len(t) < 20:
        return True, "text_too_short"
    markers = ["cookie", "accept all", "privacy policy", "menu", "subscribe", "login", "home page"]
    if sum(m in t.lower() for m in markers) >= 2:
        return True, "webpage_or_screenshot_noise"
    return False, ""


def classify_document(text: str) -> tuple[str, float]:
    """
    Classify a document as 'urine', 'lab', 'imaging', or 'unknown'.
    Urinalysis is checked FIRST to prevent misclassification as lab_panel.
    """
    l = text.lower()

    # -----------------------------------------------------------------------
    # 1. Urinalysis / Γενική Ούρων — must be checked BEFORE generic lab
    # -----------------------------------------------------------------------
    urine_keywords = [
        "γενική ούρων", "γενικη ουρων",
        "γεν. ούρων", "γεν. ουρων",
        "γεν ούρων", "γεν ουρων",
        "εξέταση ούρων", "εξεταση ουρων",
        "urinalysis", "urine analysis", "urine test",
        "general urine", "routine urine",
        # Specific urinalysis analytes that do not appear in blood panels
        "ειδικό βάρος", "ειδικο βαρος", "specific gravity",
        "ουροχολινογόνο", "ουροχολινογονο", "urobilinogen",
        "πυοσφαίρια", "πυοσφαιρια", "leukocyte esterase",
        "κύλινδροι", "κυλινδροι", "casts",
        "άμορφα άλατα", "αμορφα αλατα",
        "κρύσταλλοι", "κρυσταλλοι", "crystals",
    ]
    if any(k in l for k in urine_keywords):
        return "urine", 0.95

    # -----------------------------------------------------------------------
    # 2. Blood / biochemistry lab panel
    # -----------------------------------------------------------------------
    english_lab = [
        "crp", "esr", "tsh", "vitamin d", "ferritin",
        "wbc", "rbc", "hgb", "plt", "hemoglobin", "hematocrit",
        "leukocytes", "platelets", "cholesterol", "triglycerides",
        "glucose", "urea", "creatinine", "uric acid",
        "albumin", "bilirubin", "alt", "ast", "ggt",
    ]
    greek_lab = [
        "αιματολογ", "γενική αίματος", "γενικη αιματος",
        "λευκά αιμοσφαίρια", "λευκα αιμοσφαιρια",
        "ερυθρά αιμοσφαίρια", "ερυθρα αιμοσφαιρια",
        "αιμοσφαιρίνη", "αιμοσφαιρινη",
        "αιμοπετάλια", "αιμοπεταλια",
        "ουρία", "ουρια", "κρεατινίνη", "κρεατινινη",
        "χοληστερόλη", "χοληστερολη", "τριγλυκερίδια", "τριγλυκεριδια",
        "γλυκόζη", "γλυκοζη", "ουρικό οξύ", "ουρικο οξυ",
        "τκε", "ταχύτητα καθίζησης", "ταχυτητα καθιζησης",
        "βιταμίνη d", "βιταμινη d", "φερριτίνη", "φερριτινη",
        "θυρεοτρόπος", "θυρεοτροπος", "ft4", "ft3",
        "αλβουμίνη", "αλβουμινη", "χολερυθρίνη", "χολερυθρινη",
        "μικροβιολογ",
    ]
    if any(k in l for k in english_lab) or any(k in l for k in greek_lab):
        return "lab", 0.95

    # -----------------------------------------------------------------------
    # 3. Imaging / narrative
    # -----------------------------------------------------------------------
    imaging = [
        "findings", "impression", "conclusion", "recommendation",
        "μαγνητικ", "υπερηχογραφ", "ακτινογραφ", "αξονικ",
        "εντύπωση", "εντυπωση", "ευρήματα", "ευρηματα",
        "πόρισμα", "ποριμα", "συμπέρασμα", "συμπερασμα",
        "απεικονιστ", "mri", "ct scan", "x-ray", "ultrasound",
        "echo", "ecg", "ekg",
    ]
    if any(k in l for k in imaging):
        return "imaging", 0.88

    # -----------------------------------------------------------------------
    # 4. Fallback: numeric lab-style pattern
    # -----------------------------------------------------------------------
    numeric_lab_pattern = re.compile(
        r"[\w\s\u0370-\u03FF\u1F00-\u1FFF]{2,30}\s*[:\-]\s*\d+(?:\.\d+)?\s*[\w/μ]*\s*\(?\s*\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?\s*\)?",
        re.UNICODE
    )
    if len(numeric_lab_pattern.findall(text)) >= 3:
        return "lab", 0.80

    return "unknown", 0.40


def _group(name: str) -> str:
    n = name.lower()
    # Urinalysis analytes — checked first
    urinalysis_names = [
        "βλέννη", "βλεννη", "επιθήλια", "επιθηλια", "κύλινδροι", "κυλινδροι",
        "άμορφα", "αμορφα", "κρύσταλλοι", "κρυσταλλοι",
        "ερυθρά αιμοσφαίρια", "πυοσφαίρια", "πυοσφαιρια",
        "αιμοσφαιρίνη ούρων", "αιμοσφαιρινη ουρων",
        "χολοχρωστικές", "χολοχρωστικες",
        "ουροχολινογόνο", "ουροχολινογονο",
        "κετόνες", "κετονες",
        "λεύκωμα", "λευκωμα",
        "σάκχαρο ούρων", "σακχαρο ουρων",
        "νιτρικά", "νιτρικα",
        "ph", "ειδικό βάρος", "ειδικο βαρος",
        "όψη", "οψη", "χροιά", "χροια",
        "μικροοργανισμοί", "μικροοργανισμοι",
        "urinalysis", "urine",
    ]
    if any(k in n for k in urinalysis_names):
        return "urinalysis"
    if "crp" in n or "esr" in n or "τκε" in n:
        return "inflammation"
    if "tsh" in n or "vitamin d" in n or "βιταμίνη" in n or "θυρεοτρόπος" in n:
        return "endocrine"
    if name in {"WBC", "RBC", "HGB", "PLT"} or any(k in n for k in ["λευκ", "ερυθρ", "αιμοσφαιρίνη", "αιμοπετάλια"]):
        return "hematology"
    if "ferritin" in n or "φερριτίνη" in n:
        return "iron"
    if any(k in n for k in ["cholesterol", "χοληστερόλη", "triglyceride", "τριγλυκερίδια"]):
        return "lipids"
    if any(k in n for k in ["glucose", "γλυκόζη", "σάκχαρο"]):
        return "metabolic"
    if any(k in n for k in ["creatinine", "κρεατινίνη", "urea", "ουρία"]):
        return "renal"
    return "general"


def _flag(value: float | None, low: float | None, high: float | None) -> str:
    if value is None:
        return "unknown"
    if low is not None and value < low:
        return "low"
    if high is not None and value > high:
        return "high"
    if low is not None or high is not None:
        return "normal"
    return "unknown"


def _qualitative_flag(raw: str) -> str:
    """Map a qualitative urinalysis string to an abnormal_flag."""
    key = raw.strip().lower()
    return QUALITATIVE_STATUS_MAP.get(key, "unknown")


# ---------------------------------------------------------------------------
# English lab patterns
# ---------------------------------------------------------------------------
LAB_PATTERNS = [
    re.compile(r"(?P<name>CRP)\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mg/?L)?(?:\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?)?", re.I),
    re.compile(r"(?P<name>ESR)\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mm/?h)?(?:\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?)?", re.I),
    re.compile(r"(?P<name>TSH)\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>μ?IU/?mL|mIU/?L)?(?:\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?)?", re.I),
    re.compile(r"(?P<name>Vitamin D)\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>ng/?mL)?(?:\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?)?", re.I),
    re.compile(r"(?P<name>Ferritin)\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>ng/?mL)?(?:\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?)?", re.I),
    re.compile(r"(?P<name>WBC|RBC|HGB|PLT)\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[A-Za-z0-9/%\*\^\-\.]+)?(?:\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?)?", re.I),
    re.compile(r"(?P<name>Cholesterol|Triglycerides|Glucose|Urea|Creatinine|Albumin|Bilirubin|ALT|AST|GGT)\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[A-Za-z0-9/%\*\^\-\.μ]+)?(?:\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?)?", re.I),
]

# ---------------------------------------------------------------------------
# Greek blood/biochemistry lab patterns
# ---------------------------------------------------------------------------
GREEK_LAB_PATTERNS = [
    re.compile(r"(?P<name>ΤΚΕ|Τ\.Κ\.Ε\.)\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mm/?h)?(?:\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?)?", re.I | re.UNICODE),
    re.compile(r"(?P<name>Λευκ[άα]\s*αιμοσφαίρια|Λευκοκύτταρα)\s*(?:\([^)]*\))?\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[A-Za-z0-9/%μ/μL\^\-\.]+)?(?:\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?)?", re.I | re.UNICODE),
    re.compile(r"(?P<name>Ερυθρ[άα]\s*αιμοσφαίρια|Ερυθροκύτταρα)\s*(?:\([^)]*\))?\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[A-Za-z0-9/%μ/μL\^\-\.]+)?(?:\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?)?", re.I | re.UNICODE),
    re.compile(r"(?P<name>Αιμοσφαιρίνη)\s*(?:\([^)]*\))?\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>g/?dL|g/L)?(?:\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?)?", re.I | re.UNICODE),
    re.compile(r"(?P<name>Αιμοπετάλια)\s*(?:\([^)]*\))?\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[A-Za-z0-9/%μ/μL\^\-\.]+)?(?:\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?)?", re.I | re.UNICODE),
    re.compile(r"(?P<name>Χοληστερόλη|Ολική\s*Χοληστερόλη)\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mg/?dL|mmol/?L)?(?:\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?)?", re.I | re.UNICODE),
    re.compile(r"(?P<name>Τριγλυκερίδια)\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mg/?dL|mmol/?L)?(?:\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?)?", re.I | re.UNICODE),
    re.compile(r"(?P<name>Γλυκόζη|Σάκχαρο)\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mg/?dL|mmol/?L)?(?:\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?)?", re.I | re.UNICODE),
    re.compile(r"(?P<name>Κρεατινίνη)\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mg/?dL|μmol/?L)?(?:\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?)?", re.I | re.UNICODE),
    re.compile(r"(?P<name>Ουρία|Ουρ[έε]α)\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mg/?dL|mmol/?L)?(?:\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?)?", re.I | re.UNICODE),
    re.compile(r"(?P<name>Βιταμίνη\s*D|Vit\.?\s*D)\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>ng/?mL|nmol/?L)?(?:\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?)?", re.I | re.UNICODE),
    re.compile(r"(?P<name>Φερριτίνη)\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>ng/?mL|μg/?L)?(?:\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?)?", re.I | re.UNICODE),
    # Generic Greek numeric pattern: catches anything missed above
    re.compile(
        r"(?P<name>[^\n\r:\-]{3,30})\s*[:\-]\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[A-Za-z0-9/%\*\^\-\.μ/μL]{1,10})?\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?",
        re.UNICODE
    ),
]

# ---------------------------------------------------------------------------
# Urinalysis patterns (qualitative + semi-quantitative + numeric pH/SG)
# ---------------------------------------------------------------------------
# Pattern: "AnalyteName  VALUE" where VALUE may be:
#   - qualitative string: ΟΧΙ, ΑΡΝΗΤΙΚΟ, ΘΕΤΙΚΟ, ΔΙΑΥΓΗΣ, ΚΙΤΡΙΝΗ, etc.
#   - semi-quantitative: 0-1/ΟΠ, 2-3/ΟΠ, 0-1/HPF
#   - numeric (pH, specific gravity): 6, 1020, 5.5
URINALYSIS_PATTERNS = [
    # Numeric analytes: pH and specific gravity
    re.compile(
        r"(?P<name>pH|Ειδικό\s*βάρος|Specific\s*Gravity)\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)",
        re.I | re.UNICODE
    ),
    # Semi-quantitative cell counts: "0-1/ΟΠ", "2-3/HPF"
    re.compile(
        r"(?P<name>[^\n\r:\-]{3,40})\s*[:\-]?\s*(?P<value>\d+\s*[-–]\s*\d+\s*/\s*(?:ΟΠ|HPF|hpf|οπ))",
        re.I | re.UNICODE
    ),
    # Qualitative analytes: "AnalyteName  ΟΧΙ" or "AnalyteName: ΑΡΝΗΤΙΚΟ"
    re.compile(
        r"(?P<name>[^\n\r:\-]{3,40})\s*[:\-]?\s*(?P<value>ΟΧΙ|ΑΡΝΗΤΙΚΟ|ΑΡΝΗΤΙΚΆ|ΘΕΤΙΚΟ|ΘΕΤΙΚΆ|ΝΑΡΝΗΤΙΚΟ|"
        r"ΔΙΑΥΓΗΣ|ΔΙΑΥΓΉΣ|ΘΟΛΗ|ΘΟΛΉ|ΚΙΤΡΙΝΗ|ΚΙΤΡΙΝΉ|ΑΝΟΙΧΤΟΚΙΤΡΙΝΗ|ΑΝΟΙΧΤΟΚΊΤΡΙΝΗ|"
        r"ΚΟΚΚΙΝΗ|ΚΌΚΚΙΝΗ|ΡΟΖ|ΠΟΡΤΟΚΑΛΙ|"
        r"negative|positive|absent|present|clear|turbid|yellow|pale yellow|red|"
        r"NEG|POS)",
        re.I | re.UNICODE
    ),
]


def _parse_results_from_patterns(text: str, patterns: list) -> list:
    """Parse lab results from a list of regex patterns, deduplicating by name."""
    results = []
    seen_names = set()
    for pattern in patterns:
        for m in pattern.finditer(text):
            gd = m.groupdict()
            name = (gd.get("name") or "").strip()
            if not name or name.lower() in seen_names:
                continue
            seen_names.add(name.lower())
            try:
                value = float(gd["value"]) if gd.get("value") else None
            except (ValueError, TypeError):
                continue
            low = float(gd["low"]) if gd.get("low") else None
            high = float(gd["high"]) if gd.get("high") else None
            results.append(ParsedResult(
                display_name=name,
                value_numeric=value,
                unit=(gd.get("unit") or "").strip() or None,
                reference_low=low,
                reference_high=high,
                abnormal_flag=_flag(value, low, high),
                trendable=name in TRENDABLE,
                clinical_group=_group(name),
            ))
    return results


def _parse_urinalysis_results(text: str) -> list:
    """
    Parse urinalysis results, handling both qualitative and numeric values.
    Qualitative values (ΟΧΙ, ΑΡΝΗΤΙΚΟ, ΔΙΑΥΓΗΣ, etc.) are stored in value_text.
    Numeric values (pH, specific gravity) are stored in value_numeric.
    """
    results = []
    seen_names = set()

    for pattern in URINALYSIS_PATTERNS:
        for m in pattern.finditer(text):
            gd = m.groupdict()
            name = (gd.get("name") or "").strip()
            raw_value = (gd.get("value") or "").strip()

            if not name or not raw_value:
                continue
            # Skip names that are too long (likely false positives from generic patterns)
            if len(name) > 50:
                continue
            name_key = name.lower()
            if name_key in seen_names:
                continue
            seen_names.add(name_key)

            # Try to parse as numeric first
            try:
                numeric_val = float(raw_value.replace(",", "."))
                value_numeric = numeric_val
                value_text = None
                # pH reference range: 5.0 - 8.0
                if "ph" in name_key:
                    flag = _flag(numeric_val, 5.0, 8.0)
                # Specific gravity reference: 1.005 - 1.030
                elif "βάρος" in name_key or "gravity" in name_key:
                    flag = _flag(numeric_val, 1.005, 1.030)
                else:
                    flag = "unknown"
            except (ValueError, TypeError):
                # Qualitative value
                value_numeric = None
                value_text = raw_value
                flag = _qualitative_flag(raw_value)

            results.append(ParsedResult(
                display_name=name,
                value_numeric=value_numeric,
                value_text=value_text,
                unit=None,
                reference_low=None,
                reference_high=None,
                abnormal_flag=flag,
                trendable=False,
                clinical_group="urinalysis",
                parser_confidence=0.90,
            ))

    return results


def parse_lab_document(text: str) -> ParsedReport:
    """Parse a blood/biochemistry lab document using both English and Greek patterns."""
    results = _parse_results_from_patterns(text, LAB_PATTERNS + GREEK_LAB_PATTERNS)

    return ParsedReport(
        exam_type="lab_panel",
        exam_category="lab",
        confidence_score=0.93 if results else 0.55,
        normalization_status="auto_verified" if results else "needs_review",
        source_lineage={"parser": "deterministic_lab_parser_v2"},
        results=results,
        impressions=[],
    )


def parse_urine_document(text: str) -> ParsedReport:
    """
    Parse a urinalysis (Γενική Ούρων) document.
    Handles qualitative values (ΟΧΙ, ΑΡΝΗΤΙΚΟ, ΔΙΑΥΓΗΣ, etc.) and semi-quantitative
    cell counts (0-1/ΟΠ, 2-3/ΟΠ) as well as numeric pH and specific gravity.

    Confidence scoring:
    - Qualitative results do NOT penalise confidence (absence of numeric value
      and units is expected and correct for urinalysis analytes).
    - A report with ≥5 parsed analytes gets auto_verified at 0.90.
    - A report with 1-4 analytes gets needs_review at 0.70.
    - A report with 0 analytes gets needs_review at 0.50.
    """
    results = _parse_urinalysis_results(text)

    n = len(results)
    if n >= 5:
        confidence = 0.90
        status = "auto_verified"
    elif n >= 1:
        confidence = 0.70
        status = "needs_review"
    else:
        confidence = 0.50
        status = "needs_review"

    return ParsedReport(
        exam_type="urine",
        exam_category="urine",
        confidence_score=confidence,
        normalization_status=status,
        source_lineage={"parser": "urinalysis_parser_v1"},
        results=results,
        impressions=[],
    )


def parse_imaging_document(text: str) -> ParsedReport:
    """
    Parse an imaging/narrative document.
    FIX: Reports with parsed structured sections now get auto_verified.
    """
    impressions = []
    section_keywords = [
        "Findings", "Impression", "Conclusion", "Recommendation",
        "Ευρήματα", "Εντύπωση", "Πόρισμα", "Συμπέρασμα", "Σύσταση",
    ]
    for section in section_keywords:
        m = re.search(
            section + r"\s*[:\-]\s*(.+?)(?=(" + "|".join(section_keywords) + r")\s*[:\-]|$)",
            text, re.I | re.S | re.UNICODE
        )
        if m:
            impressions.append(ParsedImpression(
                section_type=section.lower(),
                text=m.group(1).strip(),
                review_required=False,
            ))

    if not impressions and text.strip():
        impressions.append(ParsedImpression(
            section_type="narrative",
            text=text.strip(),
            review_required=True,
        ))

    has_structured = any(not i.review_required for i in impressions)
    norm_status = "auto_verified" if has_structured else "needs_review"

    return ParsedReport(
        exam_type="imaging_report",
        exam_category="imaging",
        confidence_score=0.86 if has_structured else 0.50,
        normalization_status=norm_status,
        source_lineage={"parser": "imaging_narrative_parser_v2"},
        results=[],
        impressions=impressions,
    )


def normalize_document(text: str):
    """
    Normalize a document into a ParsedReport.
    FIX v2.0.0: Returns a needs_review ParsedReport for unknown docs instead of None.
    FIX v2.1.0: Routes urinalysis documents to parse_urine_document.
    """
    garbage, reason = detect_garbage_text(text)
    if garbage:
        return None

    label, _ = classify_document(text)

    if label == "urine":
        return parse_urine_document(text)

    if label == "lab":
        return parse_lab_document(text)

    if label == "imaging":
        return parse_imaging_document(text)

    # Unknown documents — store as needs_review instead of discarding
    return ParsedReport(
        exam_type="unknown",
        exam_category="unknown",
        confidence_score=0.30,
        normalization_status="needs_review",
        source_lineage={"parser": "fallback_unknown_v2"},
        results=[],
        impressions=[ParsedImpression(
            section_type="narrative",
            text=text.strip(),
            review_required=True,
        )],
    )
