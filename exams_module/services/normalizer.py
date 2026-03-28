import re
from dataclasses import dataclass
from typing import List, Dict, Tuple

TRENDABLE = {"CRP", "ESR", "TSH", "Vitamin D", "Ferritin", "WBC", "RBC", "HGB", "PLT"}

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
    l = text.lower()
    if any(k in l for k in ["crp", "esr", "tsh", "vitamin d", "ferritin", "αιματολογ", "γενικη αιματος"]):
        return "lab", 0.95
    if any(k in l for k in ["findings", "impression", "conclusion", "μαγνητικ", "υπερηχογραφ"]):
        return "imaging", 0.88
    return "unknown", 0.40

def _group(name: str) -> str:
    n = name.lower()
    if "crp" in n or "esr" in n:
        return "inflammation"
    if "tsh" in n or "vitamin d" in n:
        return "endocrine"
    if name in {"WBC", "RBC", "HGB", "PLT"}:
        return "hematology"
    if "ferritin" in n:
        return "iron"
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

LAB_PATTERNS = [
    re.compile(r"(?P<name>CRP)\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mg/?L)?(?:\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?)?", re.I),
    re.compile(r"(?P<name>ESR)\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mm/?h)?(?:\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?)?", re.I),
    re.compile(r"(?P<name>TSH)\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>μ?IU/?mL|mIU/?L)?(?:\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?)?", re.I),
    re.compile(r"(?P<name>Vitamin D)\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>ng/?mL)?(?:\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?)?", re.I),
    re.compile(r"(?P<name>Ferritin)\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>ng/?mL)?(?:\s*\(?\s*(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\)?)?", re.I),
    re.compile(r"(?P<name>WBC|RBC|HGB|PLT)\s*[:\-]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[A-Za-z0-9/%\*\^\-\.]+)?", re.I),
]

def parse_lab_document(text: str) -> ParsedReport:
    results = []
    for pattern in LAB_PATTERNS:
        for m in pattern.finditer(text):
            gd = m.groupdict()
            name = gd.get("name")
            value = float(gd["value"]) if gd.get("value") else None
            low = float(gd["low"]) if gd.get("low") else None
            high = float(gd["high"]) if gd.get("high") else None
            results.append(ParsedResult(
                display_name=name,
                value_numeric=value,
                unit=gd.get("unit"),
                reference_low=low,
                reference_high=high,
                abnormal_flag=_flag(value, low, high),
                trendable=name in TRENDABLE,
                clinical_group=_group(name),
            ))
    return ParsedReport(
        exam_type="lab_panel",
        exam_category="lab",
        confidence_score=0.93 if results else 0.45,
        normalization_status="auto_verified" if results else "needs_review",
        source_lineage={"parser": "deterministic_lab_parser"},
        results=results,
        impressions=[],
    )

def parse_imaging_document(text: str) -> ParsedReport:
    impressions = []
    for section in ["Findings", "Impression", "Conclusion", "Recommendation"]:
        m = re.search(section + r"\s*[:\-]\s*(.+?)(?=(Findings|Impression|Conclusion|Recommendation)\s*[:\-]|$)", text, re.I | re.S)
        if m:
            impressions.append(ParsedImpression(section_type=section.lower(), text=m.group(1).strip()))
    if not impressions and text.strip():
        impressions.append(ParsedImpression(section_type="narrative", text=text.strip(), review_required=True))
    return ParsedReport(
        exam_type="imaging_report",
        exam_category="imaging",
        confidence_score=0.86 if impressions else 0.40,
        normalization_status="needs_review",
        source_lineage={"parser": "imaging_narrative_parser"},
        results=[],
        impressions=impressions,
    )

def normalize_document(text: str):
    garbage, _ = detect_garbage_text(text)
    if garbage:
        return None
    label, _ = classify_document(text)
    if label == "lab":
        return parse_lab_document(text)
    if label == "imaging":
        return parse_imaging_document(text)
    return None
