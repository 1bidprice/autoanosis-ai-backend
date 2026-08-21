"""Acceptance checks for narrative document routing and safe universal payload."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from exams_module.services import normalizer_ai
from exams_module.services.assistant_context import build_assistant_document_context
from exams_module.services.fhir_adapter import build_fhir_bundle

PDF_PATH = Path("/home/ubuntu/upload/γνωμάτευση.pdf")


def pdf_text() -> str:
    assert PDF_PATH.exists(), f"Missing fixture: {PDF_PATH}"
    return subprocess.run(["pdftotext", "-layout", str(PDF_PATH), "-"], capture_output=True, check=True, text=True).stdout


def main() -> None:
    text = pdf_text()
    # Deterministic fallback test: never needs live credentials to validate core safety.
    original_call = normalizer_ai._call_openai
    normalizer_ai._call_openai = lambda _text: None
    try:
        report = normalizer_ai.normalize_document(text)
    finally:
        normalizer_ai._call_openai = original_call

    assert report is not None
    assert report.document_type == "medical_certificate", report.document_type
    assert report.display_title == "Ιατρική Βεβαίωση / Γνωμάτευση"
    assert report.results == []
    assert report.normalization_status == "needs_review"
    assert report.needs_review is True
    clinical = report.structured_payload["clinical_summary"]
    assert clinical["condition"] == "ψωριασική αρθρίτιδα", clinical
    assert "Cimzia" in clinical["recommended_treatment"], clinical
    assert clinical["frequency"] == "κάθε δύο εβδομάδες", clinical
    assert report.structured_payload["validity"]["estimated_until"] == "2026-08-18"
    assert any(m.get("code") == "L04AB05" for m in report.terminology_mappings)

    assistant_context = build_assistant_document_context("fixture-certificate", report)
    assert assistant_context["needs_review"] is True
    assert "07068003370" not in json.dumps(assistant_context, ensure_ascii=False)

    bundle = build_fhir_bundle("fixture-certificate", 12345, report)
    types = {entry["resource"]["resourceType"] for entry in bundle["entry"]}
    assert {"DocumentReference", "Composition", "Condition", "MedicationStatement"}.issubset(types)
    condition = next(entry["resource"] for entry in bundle["entry"] if entry["resource"]["resourceType"] == "Condition")
    assert condition["verificationStatus"]["coding"][0]["code"] == "unconfirmed"
    assert "07068003370" not in json.dumps(bundle, ensure_ascii=False)

    cases = {
        "medical_certificate": "Ιατρική Βεβαίωση\nΤο παρόν χορηγείται για ΕΟΠΥΥ.",
        "medical_opinion": "Ιατρική Γνωμάτευση\nΚλινική εκτίμηση.",
        "hospital_discharge": "Εξιτήριο νοσηλείας\nΗμερομηνία εισαγωγής: 01/01/2026.",
        "prescription_or_treatment_plan": "Θεραπευτική αγωγή\nΔοσολογία: μία φορά ημερησίως.",
        "pathology_report": "Παθολογοανατομική εξέταση", "microbiology_report": "Καλλιέργεια και αντιβιόγραμμα",
        "cardiology_report": "Ηλεκτροκαρδιογράφημα Holter", "graph_or_chart_only": "Ιατρικό γράφημα τάσεων",
        "administrative_health_document": "Παραπεμπτικό ιατρικής εξέτασης",
    }
    for expected, sample in cases.items():
        detected, _ = normalizer_ai.classify_document(sample)
        assert detected == expected, (expected, detected)
    print("PASS: universal medical-certificate contract")


if __name__ == "__main__":
    main()
