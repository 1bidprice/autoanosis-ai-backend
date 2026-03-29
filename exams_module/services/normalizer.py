"""
Autoanosis Exams Normalizer — v2.0.0
Fixes:
  - Expanded LAB_PATTERNS to cover Greek lab report formats
  - Expanded classify_document to detect Greek-only lab reports
  - Imaging reports with parsed impressions now get auto_verified (not needs_review)
  - normalize_document now returns a needs_review ParsedReport for unknown docs
    instead of None, so they are still stored and visible after manual review
"""
import re
from dataclasses import dataclass
from typing import List, Dict, Tuple

TRENDABLE = {
    "CRP", "ESR", "TSH", "Vitamin D", "Ferritin",
    "WBC", "RBC", "HGB", "PLT",
    "ΤΚΕ",
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
    Classify a document as 'lab', 'imaging', or 'unknown'.
    Expanded to cover Greek-only lab reports.
    """
    l = text.lower()

    # English lab keywords
    english_lab = [
        "crp", "esr", "tsh", "vitamin d", "ferritin",
        "wbc", "rbc", "hgb", "plt", "hemoglobin", "hematocrit",
        "leukocytes", "platelets", "cholesterol", "triglycerides",
        "glucose", "urea", "creatinine", "uric acid",
        "albumin", "bilirubin", "alt", "ast", "ggt",
    ]

    # Greek lab keywords
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
        "γενική ούρων", "γενικη ουρων", "μικροβιολογ",
    ]

    # Imaging keywords
    imaging = [
        "findings", "impression", "conclusion", "recommendation",
        "μαγνητικ", "υπερηχογραφ", "ακτινογραφ", "αξονικ",
        "εντύπωση", "εντυπωση", "ευρήματα", "ευρηματα",
        "πόρισμα", "ποριμα", "συμπέρασμα", "συμπερασμα",
        "απεικονιστ", "mri", "ct scan", "x-ray", "ultrasound",
        "echo", "ecg", "ekg",
    ]

    if any(k in l for k in english_lab) or any(k in l for k in greek_lab):
        return "lab", 0.95

    if any(k in l for k in imaging):
        return "imaging", 0.88

    # Fallback: detect numeric lab-style patterns "Name: 5.2 (3.0-6.0)"
    numeric_lab_pattern = re.compile(
        r"[\w\s\u0370-\u03FF\u1F00-\u1FFF]{2,30}\s*[:\-]\s*\d+(?:\.\d+)?\s*[\w/μ]*\s*\(?\s*\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?\s*\)?",
        re.UNICODE
    )
    if len(numeric_lab_pattern.findall(text)) >= 3:
        return "lab", 0.80

    return "unknown", 0.40


def _group(name: str) -> str:
    n = name.lower()
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


# English lab patterns
LAB_PATTERNS = [
    re.compile(r"(?P<name>CRP)\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mg/?L)?(?:\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?)?", re.I),
    re.compile(r"(?P<name>ESR)\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mm/?h)?(?:\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?)?", re.I),
    re.compile(r"(?P<name>TSH)\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>μ?IU/?mL|mIU/?L)?(?:\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?)?", re.I),
    re.compile(r"(?P<name>Vitamin D)\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>ng/?mL)?(?:\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?)?", re.I),
    re.compile(r"(?P<name>Ferritin)\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>ng/?mL)?(?:\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?)?", re.I),
    re.compile(r"(?P<name>WBC|RBC|HGB|PLT)\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[A-Za-z0-9/%\*\^\-\.]+)?(?:\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?)?", re.I),
    re.compile(r"(?P<name>Cholesterol|Triglycerides|Glucose|Urea|Creatinine|Albumin|Bilirubin|ALT|AST|GGT)\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[A-Za-z0-9/%\*\^\-\.μ]+)?(?:\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?)?", re.I),
]

# Greek lab patterns
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
    # Uses [^\n\r:\-] to prevent multi-line false positives
    re.compile(
        r"(?P<name>[^\n\r:\-]{3,30})\s*[:\-]\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[A-Za-z0-9/%\*\^\-\.μ/μL]{1,10})?\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?",
        re.UNICODE
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


def parse_lab_document(text: str) -> ParsedReport:
    """Parse a lab document using both English and Greek patterns."""
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
    FIX: Returns a needs_review ParsedReport for unknown docs instead of None,
    so they are stored and visible in the review queue.
    """
    garbage, reason = detect_garbage_text(text)
    if garbage:
        return None

    label, _ = classify_document(text)

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
