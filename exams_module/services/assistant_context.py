"""PII-minimized context contract for downstream assistants."""

from typing import Any, Dict





_SENSITIVE_KEYS = {
    
    "amka", "afm", "tax_id", "identifier", "identity_number", "phone", "email",
    
    "address", "raw_ocr", "ocr_text", "original_text", "source_text", "extracted_text",
    
    "narrative_text", "patient", "patient_name", "patient_name_masked",
    
}





def _without_sensitive_values(value: Any) -> Any:
    
    if isinstance(value, dict):
        
        return {
            
            key: _without_sensitive_values(item)
            
            for key, item in value.items()
            
            if key.casefold() not in _SENSITIVE_KEYS
            
        }
        
    if isinstance(value, list):
        
        return [_without_sensitive_values(item) for item in value]
        
    return value
    




def build_assistant_document_context(document_id: str, parsed_report: Any) -> Dict:
    
    """Return only semantically structured, non-identifying document context."""
    
    payload = _without_sensitive_values(getattr(parsed_report, "structured_payload", None) or {})
    
    clinical = payload.get("clinical_summary") if isinstance(payload.get("clinical_summary"), dict) else {}
    
    review_reason = getattr(parsed_report, "review_reason", "") or getattr(parsed_report, "report_review_reason", "") or payload.get("review_reason", "")
    
    needs_review = bool(
        
        getattr(parsed_report, "needs_review", False)
        
        or getattr(parsed_report, "normalization_status", "") == "needs_review"
        
        or payload.get("needs_review", False)
        
    )
    
    allowed_mapping_keys = (
        
        "field", "original_value", "normalized_value", "semantic_type", "terminology_system",
        
        "terminology_systems", "code", "confidence", "needs_review", "terminology_version",
        
    )
    
    mappings = [
        
        {key: _without_sensitive_values(mapping.get(key)) for key in allowed_mapping_keys if key in mapping}
        
        for mapping in (getattr(parsed_report, "terminology_mappings", None) or payload.get("terminology_mappings") or [])
        
        if isinstance(mapping, dict)
        
    ]
    
    date_value = payload.get("issue_date") or getattr(parsed_report, "performed_at", None)
    
    if hasattr(date_value, "isoformat"):
        
        date_value = date_value.isoformat()
        
    context = {
        
        "source_document_id": document_id,
        
        "document_type": getattr(parsed_report, "document_type", None) or getattr(parsed_report, "exam_type", "generic_medical_document"),
        
        "document_subtype": getattr(parsed_report, "document_subtype", None) or payload.get("document_subtype"),
        
        "title": getattr(parsed_report, "display_title", None) or payload.get("display_title") or getattr(parsed_report, "display_name", None),
        
        "date": date_value,
        
        "clinical_summary": {key: clinical.get(key) for key in ("condition", "treatment_history", "recommended_treatment", "dose", "route_of_administration", "frequency", "purpose") if clinical.get(key)},
        
        "terminology_mappings": mappings,
        
        "confidence": float(getattr(parsed_report, "confidence_score", 0) or 0) if getattr(parsed_report, "confidence_score", None) is not None else None,
        
        "needs_review": needs_review,
        
        "review_reason": review_reason,
        
        "assistant_summary": payload.get("assistant_summary", ""),
        
        "assistant_instruction": (
            
            "Το έγγραφο είναι σημειωμένο για έλεγχο. Περιέγραψέ το ως μη επιβεβαιωμένο και μην το παρουσιάσεις ως διάγνωση ή ενεργή συνταγογράφηση."
            
            if needs_review else
            
            "Χρησιμοποίησε μόνο τα δομημένα πεδία ως περιγραφή προέλευσης και μην δημιουργείς 


















































