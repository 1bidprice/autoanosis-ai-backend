"""Versioned, review-gated terminology candidates; never silent clinical coding."""
from __future__ import annotations
import unicodedata
from typing import Any, Dict, List, Optional

TERMINOLOGY_MAPPING_VERSION = "autoanosis-curated-candidates-2026-08"
MAPPING_METHOD = "deterministic_local_candidate_dictionary"
def _fold(value: Optional[str]) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", (value or "").lower()) if unicodedata.category(c) != "Mn")
def _span(text: str, value: str) -> Optional[str]:
    start = _fold(text).find(_fold(value))
    return " ".join(text[max(0, start - 40): start + len(value) + 80].split()) if start >= 0 else None
def _mapping(field: str, value: str, semantic_type: str, normalized: str, system: str, code: Optional[str], source: str) -> Dict[str, Any]:
    return {"field": field, "original_value": value, "normalized_value": normalized, "semantic_type": semantic_type, "terminology_system": system, "code": code, "display": normalized, "confidence": 0.90, "source_span": _span(source, value), "needs_review": True, "terminology_version": TERMINOLOGY_MAPPING_VERSION, "mapping_method": MAPPING_METHOD}
def map_document_terminology(payload: Dict[str, Any], source_text: str = "") -> List[Dict[str, Any]]:
    mappings = [m for m in payload.get("terminology_mappings", []) if isinstance(m, dict)]
    known = {(m.get("field"), _fold(m.get("original_value"))) for m in mappings}
    clinical = payload.get("clinical_summary") or {}
    condition, treatment = clinical.get("condition"), clinical.get("recommended_treatment")
    if condition and "ψωριασικη αρθριτιδα" in _fold(condition) and ("condition", _fold(condition)) not in known:
        mappings.append(_mapping("condition", condition, "diagnosis", "Psoriatic arthritis", "ICD-11/SNOMED_CT", None, source_text))
    if treatment and "cimzia" in _fold(treatment) and ("medication", _fold(treatment)) not in known:
        mappings.append(_mapping("medication", treatment, "medication", "Certolizumab pegol", "ATC/RxNorm-style", "L04AB05", source_text))
    return mappings
def map_result_terminology(results: List[Any]) -> List[Dict[str, Any]]:
    rows = []
    lookup = {"crp": ("C reactive protein [Mass/volume] in Serum or Plasma", "1988-5"), "γλυκοζη": ("Glucose [Mass/volume] in Serum or Plasma", "2345-7"), "glucose": ("Glucose [Mass/volume] in Serum or Plasma", "2345-7")}
    ucum = {"mg/dl": "mg/dL", "mg/l": "mg/L", "g/dl": "g/dL", "mmol/l": "mmol/L", "%": "%"}
    for result in results or []:
        name, folded = getattr(result, "display_name", ""), _fold(getattr(result, "display_name", ""))
        for key, (display, code) in lookup.items():
            if key in folded:
                rows.append({"field": "observation", "original_value": name, "normalized_value": display, "semantic_type": "observation", "terminology_system": "LOINC", "code": code, "display": display, "confidence": 0.78, "source_span": getattr(result, "ocr_snippet", None), "needs_review": True, "terminology_version": TERMINOLOGY_MAPPING_VERSION, "mapping_method": MAPPING_METHOD})
                break
        unit = getattr(result, "unit", None); normalized = ucum.get(_fold(unit))
        if normalized: rows.append({"field": "unit", "original_value": unit, "normalized_value": normalized, "semantic_type": "unit", "terminology_system": "UCUM", "code": normalized, "display": normalized, "confidence": 0.85, "source_span": getattr(result, "ocr_snippet", None), "needs_review": True, "terminology_version": TERMINOLOGY_MAPPING_VERSION, "mapping_method": MAPPING_METHOD})
    return rows
