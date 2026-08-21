"""FHIR R4-compatible, review-aware projection of parsed Autoanosis documents."""
from typing import Any, Dict, List
def _ref(kind, ident): return {"reference": f"{kind}/{ident}"} if ident not in (None, "") else None
def build_fhir_bundle(document_id: str, patient_id: int, parsed: Any) -> Dict:
    payload, doc_type = getattr(parsed, "structured_payload", None) or {}, getattr(parsed, "document_type", None) or getattr(parsed, "exam_type", "generic_medical_document")
    title = getattr(parsed, "display_title", None) or payload.get("display_title") or doc_type
    entries: List[Dict] = [{"resource": {"resourceType": "DocumentReference", "id": f"document-{document_id}", "status": "current", "subject": _ref("Patient", patient_id), "type": {"text": title}, "date": payload.get("issue_date") or getattr(parsed, "performed_at", None), "description": getattr(parsed, "assistant_summary", "") or None, "content": [{"attachment": {"contentType": "application/json", "title": title}}]}}]
    clinical = payload.get("clinical_summary") or {}
    if doc_type in {"medical_certificate", "medical_opinion", "prescription_or_treatment_plan", "hospital_discharge", "generic_medical_document"}:
        entries.append({"resource": {"resourceType": "Composition", "id": f"composition-{document_id}", "status": "preliminary" if getattr(parsed, "needs_review", False) else "final", "type": {"text": title}, "subject": _ref("Patient", patient_id), "date": payload.get("issue_date") or getattr(parsed, "performed_at", None) or "1900-01-01", "title": title}})
        if clinical.get("condition"): entries.append({"resource": {"resourceType": "Condition", "id": f"condition-{document_id}", "verificationStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-ver-status", "code": "unconfirmed" if getattr(parsed, "needs_review", False) else "confirmed"}]}, "code": {"text": clinical["condition"]}, "subject": _ref("Patient", patient_id), "note": [{"text": "Extracted from uploaded medical document; confirm against source."}]}})
        if clinical.get("recommended_treatment"): entries.append({"resource": {"resourceType": "MedicationStatement", "id": f"medication-{document_id}", "status": "unknown", "medicationCodeableConcept": {"text": clinical["recommended_treatment"]}, "subject": _ref("Patient", patient_id), "note": [{"text": "Extracted treatment mention; not a new prescription."}]}})
    return {"resourceType": "Bundle", "type": "collection", "identifier": {"system": "https://autoanosis.com/fhir/bundle", "value": f"document-{document_id}"}, "entry": entries}
