import unittest

from grounding import build_grounding_manifest, manifest_contains_sensitive_values


class GroundingManifestTests(unittest.TestCase):
    def test_structural_sections_are_reported_without_values(self):
        context = {
            "user_name": "SECRET_PATIENT_NAME",
            "autoimmune_type": "SECRET_CONDITION",
            "medications": [
                {
                    "medication_name": "SECRET_MEDICATION",
                    "dosage": "SECRET_DOSAGE",
                }
            ],
            "structured_exam_results": [
                {
                    "display_name": "SECRET_EXAM",
                    "value": "SECRET_VALUE",
                }
            ],
            "recent_checkins": [
                {
                    "pain": "SECRET_PAIN",
                    "notes": "SECRET_NOTE",
                }
            ],
            "medical_documents": [
                {
                    "document_title": "SECRET_DOCUMENT_TITLE",
                    "extracted_text": "SECRET_DOCUMENT_TEXT",
                }
            ],
        }
        snapshot = (
            "1. ΠΡΟΦΙΛ:\nΧρήστης: SECRET_PATIENT_NAME\n"
            "2. ΦΑΡΜΑΚΑ:\n• SECRET_MEDICATION SECRET_DOSAGE\n"
            "3. ΕΞΕΤΑΣΕΙΣ & ΙΑΤΡΙΚΑ ΕΓΓΡΑΦΑ:\nSECRET_EXAM SECRET_VALUE\n"
            "5. RECENT CHECK-INS:\nSECRET_PAIN\n"
            "10. ΑΡΧΕΙΟ ΕΓΓΡΑΦΩΝ (1 έγγραφο):\nSECRET_DOCUMENT_TEXT"
        )

        manifest = build_grounding_manifest(
            context,
            snapshot,
            "wp_push_smart",
            "summary",
        )

        self.assertTrue(manifest["grounded"])
        self.assertEqual(manifest["context_source"], "wp_push_smart")
        self.assertEqual(manifest["intent"], "summary")
        self.assertEqual(
            [section["id"] for section in manifest["sections"]],
            ["profile", "medications", "exams", "checkins", "medical_documents"],
        )
        self.assertEqual(
            {section["id"]: section.get("count") for section in manifest["sections"]},
            {
                "profile": None,
                "medications": 1,
                "exams": 1,
                "checkins": 1,
                "medical_documents": 1,
            },
        )

        self.assertFalse(
            manifest_contains_sensitive_values(
                manifest,
                [
                    "SECRET_PATIENT_NAME",
                    "SECRET_CONDITION",
                    "SECRET_MEDICATION",
                    "SECRET_DOSAGE",
                    "SECRET_EXAM",
                    "SECRET_VALUE",
                    "SECRET_PAIN",
                    "SECRET_NOTE",
                    "SECRET_DOCUMENT_TITLE",
                    "SECRET_DOCUMENT_TEXT",
                ],
            )
        )

    def test_no_context_returns_explicit_ungrounded_manifest(self):
        manifest = build_grounding_manifest(None, "", "wp_push_smart", "education")
        self.assertFalse(manifest["grounded"])
        self.assertEqual(manifest["context_source"], "none")
        self.assertEqual(manifest["sections"], [])
        self.assertEqual(manifest["context_bytes"], 0)

    def test_only_sections_actually_present_in_formatted_prompt_are_reported(self):
        context = {
            "medications": [{"medication_name": "hidden"}],
            "best_history": [{"id": 1}],
        }
        manifest = build_grounding_manifest(
            context,
            "4. BEST HISTORY:\nΙστορικό BEST: 1 παλαιότερες καταχωρήσεις",
            "wp_push_smart",
            "doctor_report",
        )
        self.assertEqual([section["id"] for section in manifest["sections"]], ["best"])
        self.assertEqual(manifest["sections"][0]["count"], 1)


if __name__ == "__main__":
    unittest.main()
