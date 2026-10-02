import unittest

from grounding import build_context_fact_index, build_grounding_manifest, manifest_contains_sensitive_values


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

    def test_fact_index_uses_authoritative_sources_without_values(self):
        context = {
            "medications": [
                {"id": 7, "medication_name": "SECRET_MED", "start_date": "2026-01-01"}
            ],
            "today_doses": {
                "timezone": "Europe/Athens",
                "doses": [
                    {
                        "dose_id": 42,
                        "scheduled_local_date": "2026-10-02",
                        "medication_name": "SECRET_MED",
                    }
                ],
            },
            "longitudinal_checkin_analytics": {
                "recent_records": [
                    {"date": "2026-09-30", "pain": 8, "notes": "SECRET_NOTE"},
                    {"date": "2026-10-02", "pain": 4},
                ]
            },
            "structured_exam_results": [
                {
                    "report_id": "abc",
                    "test_name": "SECRET_TEST",
                    "result_value": "999",
                    "test_date": "2026-09-15",
                }
            ],
            "narrative_exam_context": [
                {
                    "report_id": "img-1",
                    "performed_at": "2026-08-10",
                    "summary": "SECRET_SUMMARY",
                }
            ],
            "medical_document_context": [
                {
                    "source_document_id": "doc-1",
                    "date": "2026-07-01",
                    "title": "SECRET_DOC",
                }
            ],
        }

        index = build_context_fact_index(context)

        self.assertEqual(index["medications"]["source"], "ame")
        self.assertEqual(index["medications"]["resource"], "mm_medications")
        self.assertEqual(index["doses"]["resource"], "mm_doses")
        self.assertEqual(index["checkins"]["count"], 2)
        self.assertEqual(index["checkins"]["coverage"], {"from": "2026-09-30", "to": "2026-10-02"})
        self.assertEqual(index["exam_results"]["count"], 1)
        self.assertEqual(index["exam_reports"]["count"], 1)
        self.assertEqual(index["medical_documents"]["count"], 1)

        serialized = repr(index)
        for forbidden in (
            "SECRET_MED",
            "SECRET_NOTE",
            "SECRET_TEST",
            "999",
            "SECRET_SUMMARY",
            "SECRET_DOC",
        ):
            self.assertNotIn(forbidden, serialized)

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
