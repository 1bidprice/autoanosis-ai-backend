import unittest
from datetime import datetime, timezone

from continuity_core.adapter import facts_from_autoanosis_context
from continuity_core.service import build_continuity_summary


NOW = datetime(2026, 9, 19, 19, 0, 0, tzinfo=timezone.utc)


class ContinuityCoreTests(unittest.TestCase):
    def test_detects_change_between_dated_facts(self):
        summary = build_continuity_summary(
            [
                {
                    "fact_type": "exam.result",
                    "fact_key": "exam.crp",
                    "value": {"value": 4.2},
                    "source": "uploaded_document",
                    "observed_at": "2026-08-01T08:00:00Z",
                    "status": "user_reported",
                },
                {
                    "fact_type": "exam.result",
                    "fact_key": "exam.crp",
                    "value": {"value": 2.1},
                    "source": "uploaded_document",
                    "observed_at": "2026-09-01T08:00:00Z",
                    "status": "user_reported",
                },
            ],
            now=NOW,
        )
        self.assertEqual(len(summary["changes"]), 1)
        self.assertEqual(summary["changes"][0]["from"]["value"], 4.2)
        self.assertEqual(summary["changes"][0]["to"]["value"], 2.1)

    def test_never_fabricates_staleness_without_explicit_rule(self):
        summary = build_continuity_summary(
            [
                {
                    "fact_type": "condition.profile",
                    "fact_key": "condition.primary",
                    "value": "example",
                    "source": "user_profile",
                    "observed_at": "2024-01-01T00:00:00Z",
                    "status": "user_reported",
                }
            ],
            now=NOW,
        )
        self.assertEqual(summary["stale"], [])
        self.assertEqual(summary["current"][0]["currentness"], "dated")

    def test_explicit_valid_until_marks_stale(self):
        summary = build_continuity_summary(
            [
                {
                    "fact_type": "profile.record",
                    "fact_key": "profile.example",
                    "value": "x",
                    "source": "user_profile",
                    "observed_at": "2026-01-01T00:00:00Z",
                    "valid_until": "2026-06-01T00:00:00Z",
                }
            ],
            now=NOW,
        )
        self.assertEqual(summary["stale"][0]["reason"], "validity_expired")
        self.assertEqual(summary["next_actions"][0]["type"], "confirm_or_update")

    def test_conflict_generates_process_action_only(self):
        summary = build_continuity_summary(
            [
                {
                    "fact_type": "medication.record",
                    "fact_key": "medication.example",
                    "value": {"name": "Example"},
                    "source": "medication",
                    "status": "conflicting",
                }
            ],
            now=NOW,
        )
        self.assertEqual(summary["conflicting"][0]["fact_key"], "medication.example")
        action = summary["next_actions"][0]
        self.assertEqual(action["type"], "review_conflict")
        self.assertNotIn("dose", action["message"].lower())
        self.assertFalse(summary["safety"]["clinical_decision_support"])

    def test_missing_domain_is_described_as_data_gap(self):
        summary = build_continuity_summary(
            [],
            required_domains=["medication", "exam"],
            now=NOW,
        )
        self.assertEqual(summary["coverage"]["missing_domains"], ["exam", "medication"])
        self.assertEqual({a["type"] for a in summary["next_actions"]}, {"add_missing_data"})

    def test_adapter_does_not_copy_identity_fields(self):
        facts = facts_from_autoanosis_context(
            {
                "user_name": "Secret Name",
                "email": "secret@example.com",
                "autoimmune_type": "Example condition",
                "medications": {
                    "current_medications": [
                        {
                            "id": 7,
                            "name": "Example medication",
                            "dosage": "10 mg",
                            "updated_at": "2026-09-10T10:00:00Z",
                        }
                    ]
                },
            }
        )
        serialized = repr(facts)
        self.assertNotIn("Secret Name", serialized)
        self.assertNotIn("secret@example.com", serialized)
        self.assertTrue(any(f["fact_key"] == "condition.primary" for f in facts))
        self.assertTrue(any(f["fact_key"] == "medication.7" for f in facts))

    def test_adapter_supports_current_mobile_envelopes(self):
        facts = facts_from_autoanosis_context(
            {
                "home_snapshot": {
                    "today_checkin": {
                        "date": "2026-09-19",
                        "pain_level": 3,
                        "fatigue_level": 4,
                        "energy_level": 6,
                        "mood_level": 7,
                        "stiffness_level": 2,
                        "inflammation_level": 3,
                    }
                },
                "today_doses": {
                    "date": "2026-09-19",
                    "count": 1,
                    "doses": [
                        {
                            "dose_id": 44,
                            "medication_id": 7,
                            "scheduled_date": "2026-09-19",
                            "scheduled_time": "09:00:00",
                            "status": "taken",
                        }
                    ],
                },
                "longitudinal_checkin_analytics": {
                    "recent_records": [
                        {
                            "date": "2026-09-18",
                            "pain": 5,
                            "fatigue": 6,
                            "energy": 4,
                            "mood": 5,
                            "stiffness": 4,
                            "inflammation": 5,
                        }
                    ]
                },
            }
        )
        keys = {fact["fact_key"] for fact in facts}
        self.assertIn("checkin.pain", keys)
        self.assertIn("checkin.fatigue", keys)
        self.assertIn("checkin.energy", keys)
        self.assertIn("checkin.mood", keys)
        self.assertIn("dose.44", keys)

        summary = build_continuity_summary(facts, now=NOW)
        pain_change = next(change for change in summary["changes"] if change["fact_key"] == "checkin.pain")
        self.assertEqual(pain_change["from"], 5)
        self.assertEqual(pain_change["to"], 3)

    def test_undated_medication_keeps_unknown_currentness(self):
        facts = facts_from_autoanosis_context(
            {
                "medications": {
                    "current_medications": [
                        {"id": 1, "name": "Example medication"}
                    ]
                }
            }
        )
        summary = build_continuity_summary(facts, now=NOW)
        medication = next(item for item in summary["current"] if item["fact_key"] == "medication.1")
        self.assertEqual(medication["currentness"], "unknown")
        self.assertEqual(summary["coverage"]["unknown_currentness_count"], 1)


if __name__ == "__main__":
    unittest.main()
