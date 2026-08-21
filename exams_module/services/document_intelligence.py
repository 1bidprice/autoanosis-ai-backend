"""Conservative structured extraction helpers for narrative medical documents."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Any, Dict, List, Optional

DOCUMENT_CATEGORY = {
    "medical_certificate": "Γνωματεύσεις & Βεβαιώσεις", "medical_opinion": "Ιατρικές Γνωματεύσεις",
    "prescription_or_treatment_plan": "Αγωγές & Θεραπευτικά Πλάνα", "hospital_discharge": "Νοσηλεία & Εξιτήρια",
    "pathology_report": "Παθολογοανατομικές Αναφορές", "microbiology_report": "Μικροβιολογικές Αναφορές",
    "cardiology_report": "Καρδιολογικές Αναφορές", "graph_or_chart_only": "Γραφήματα & Διαγράμματα",
    "administrative_health_document": "Διοικητικά Ιατρικά Έγγραφα", "generic_medical_document": "Ιατρικά Έγγραφα",
    "unknown_needs_review": "Ιατρικά Έγγραφα προς Έλεγχο",
}
DOCUMENT_TITLE = {
    "medical_certificate": "Ιατρική Βεβαίωση / Γνωμάτευση", "medical_opinion": "Ιατρική Γνωμάτευση",
    "prescription_or_treatment_plan": "Θεραπευτικό Πλάνο / Αγωγή", "hospital_discharge": "Εξιτήριο Νοσηλείας",
    "pathology_report": "Παθολογοανατομική Αναφορά", "microbiology_report": "Μικροβιολογική Αναφορά",
    "cardiology_report": "Καρδιολογική Αναφορά", "graph_or_chart_only": "Ιατρικό Γράφημα / Διάγραμμα",
    "administrative_health_document": "Διοικητικό Ιατρικό Έγγραφο", "generic_medical_document": "Ιατρικό Έγγραφο",
    "unknown_needs_review": "Ιατρικό Έγγραφο προς Έλεγχο",
}

def _match(pattern: str, text: str) -> Optional[str]:
    found = re.search(pattern, text or "", re.IGNORECASE | re.DOTALL)
    return re.sub(r"\s+", " ", found.group(1)).strip(" .,:;\n\t") if found else None

def _iso(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try: return datetime.strptime(value.strip(), fmt).date().isoformat()
        except ValueError: pass
    return None

def _one_year(iso_date: Optional[str]) -> Optional[str]:
    try: return date.fromisoformat(iso_date).replace(year=date.fromisoformat(iso_date).year + 1).isoformat() if iso_date else None
    except ValueError: return None

def _fold(value: Optional[str]) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", (value or "").lower()) if unicodedata.category(c) != "Mn")

def _specialty(value: Optional[str]) -> Optional[str]:
    if not value: return None
    value = re.split(r"\s+(?:ημερομηνία|όνομα|επώνυμο|ταυτο)|\n", value, flags=re.IGNORECASE)[0].strip()
    return {"ρευματολογος": "Ρευματολόγος"}.get(_fold(value), value.title() if value else None)

def fallback_payload(text: str, document_type: str) -> Dict[str, Any]:
    """Extract only explicit high-signal source facts; no inference or diagnosis."""
    issue_date = _iso(_match(r"(?:ημ[/.]?νία|ημερομηνία)\s*έκδοσης\s*[:.]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})", text))
    validity = _match(r"(ισχύ(?:ει|ει)\s+για\s+[^.\n]+)", text)
    block = _match(r"στοιχεία\s+ιατρού(.+?)(?:ο\s+κάτωθι|το\s+παρόν|$)", text) or ""
    first = _match(r"όνομα\s*[:.]?\s*([A-Za-zΑ-ΩΆΈΉΊΌΎΏάέήίόύώϊϋΐΰ-]+)", block)
    last = _match(r"επώνυμο\s*[:.]?\s*([A-Za-zΑ-ΩΆΈΉΊΌΎΏάέήίόύώϊϋΐΰ-]+)", block)
    specialty = _specialty(_match(r"ειδικότητα\s*[:.]?\s*([^\n]+)", block) or _match(r"ειδικότητα\s*[:.]?\s*(.+?)(?:\s+(?:ημερομηνία|όνομα|επώνυμο|ταυτο)|\n)", text))
    provider = _match(r"μονάδα\s+υγείας\s*[:.]?\s*(.+?)(?:\s+(?:αρ\.|ταυτο)|\n)", text)
    dose = _match(r"σε\s+δόση\s+(.+?)(?:\.(?:\s|$)|\Z)", text)
    clinical = {
        "condition": _match(r"πάσχει\s+από\s+(.+?)(?:,|\.|\n)", text),
        "treatment_history": _match(r"(μη\s+ανταποκρι\S*(?:\s+[^.\n,]+){0,12})", text),
        "recommended_treatment": _match(r"χρήζει\s+αγωγής\s+με\s+(.+?)(?:,\s*σε\s+δόση|\.|\n)", text),
        "dose": dose,
        "route_of_administration": "Υποδόρια ένεση" if any(x in text.lower() for x in ("υποδόρια", "υποδορια")) else None,
        "frequency": _match(r"(κάθε\s+(?:μία|μια|δύο|δυο|\d+)\s+(?:ημέρ\S+|εβδομάδ\S+|μήν\S+))", dose or text),
        "purpose": "Χορήγηση για ΕΟΠΥΥ" if ("εοπυυ" in text.lower() or "eopyy" in text.lower()) else None,
    }
    review = document_type in {"medical_certificate", "medical_opinion", "prescription_or_treatment_plan", "hospital_discharge"}
    return {
        "category": DOCUMENT_CATEGORY.get(document_type, DOCUMENT_CATEGORY["generic_medical_document"]),
        "certificate_number": _match(r"αριθμ(?:ός|ος)\s+βεβαίωσης\s*[:.]?\s*([A-Za-z0-9-]+)", text),
        "issue_date": issue_date,
        "validity": {"text": validity, "estimated_until": _one_year(issue_date) if validity and "ένα έτος" in validity.lower() else None, "confidence": "medium" if validity and issue_date else "unknown"},
        "doctor": {"name": " ".join(x for x in (first, last) if x) or None, "specialty": specialty, "provider": provider},
        "patient": {"display_name_masked": None}, "clinical_summary": clinical, "sections": [],
        "confidence": 0.78 if any(clinical.values()) or issue_date else 0.45,
        "needs_review": review or document_type == "unknown_needs_review",
        "review_reason": "Ιατρική γνωμάτευση με θεραπευτική αγωγή και προσωπικά στοιχεία — απαιτείται έλεγχος πριν χρησιμοποιηθεί σε αναφορά ή κοινοποίηση." if review else "Απαιτείται έλεγχος του τύπου και του περιεχομένου του εγγράφου πριν από κλινική χρήση.",
        "assistant_summary": "", "terminology_mappings": [],
    }

def merge_payload(fallback: Dict[str, Any], extracted: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged, extracted = dict(fallback), extracted if isinstance(extracted, dict) else {}
    for key, value in extracted.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **{k: v for k, v in value.items() if v not in (None, "", [], {})}}
        elif value not in (None, "", [], {}): merged[key] = value
    clinical = merged.get("clinical_summary") or {}
    if any(clinical.get(k) for k in ("condition", "recommended_treatment", "dose")) or (merged.get("validity") or {}).get("text"):
        merged["needs_review"] = True
    return merged

def build_assistant_summary(title: str, payload: Dict[str, Any]) -> str:
    if str(payload.get("assistant_summary") or "").strip(): return str(payload["assistant_summary"]).strip()
    clinical, parts = payload.get("clinical_summary") or {}, [title]
    if payload.get("issue_date"): parts.append(f"Ημερομηνία: {payload['issue_date']}")
    if clinical.get("condition"): parts.append(f"Αναφερόμενη πάθηση: {clinical['condition']}")
    if clinical.get("recommended_treatment"): parts.append(f"Αναφερόμενη αγωγή: {clinical['recommended_treatment']}{(' — ' + clinical['frequency']) if clinical.get('frequency') else ''}")
    if payload.get("needs_review"): parts.append("Απαιτείται επιβεβαίωση πριν από κλινική χρήση ή κοινοποίηση")
    return ". ".join(parts) + "."

def narrative_impressions(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    clinical = payload.get("clinical_summary") or {}
    text = "\n".join(f"{label}: {value}" for label, value in (("Πάθηση", clinical.get("condition")), ("Ιστορικό θεραπείας", clinical.get("treatment_history")), ("Αγωγή", clinical.get("recommended_treatment")), ("Σκοπός", clinical.get("purpose"))) if value)
    return [{"section_type": "clinical_summary", "text": text, "severity_flag": "unknown", "review_required": bool(payload.get("needs_review"))}] if text else []
