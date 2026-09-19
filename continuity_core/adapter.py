"""Adapters from current Autoanosis context shapes to Continuity Core facts.

The adapter is intentionally conservative. It does not fabricate dates,
confirmation state, diagnoses or treatment meaning.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any


def _safe_key(value: Any) -> str:
    raw = str(value or "unknown").strip().lower()
    raw = re.sub(r"[^a-z0-9α-ωάέήίόύώϊϋΐΰ_-]+", "_", raw, flags=re.IGNORECASE)
    return raw.strip("_") or "unknown"


def _first(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return []


def _add_fact(
    facts: list[dict[str, Any]],
    *,
    fact_type: str,
    fact_key: str,
    value: Any,
    source: str,
    source_reference_id: Any = None,
    observed_at: Any = None,
    updated_at: Any = None,
    status: str = "user_reported",
    confidence: str = "unknown",
    unit: Any = None,
    provenance: dict[str, Any] | None = None,
) -> None:
    facts.append(
        {
            "fact_type": fact_type,
            "fact_key": fact_key,
            "value": value,
            "unit": unit,
            "source": source,
            "source_reference_id": source_reference_id,
            "observed_at": observed_at,
            "updated_at": updated_at,
            "status": status,
            "confidence": confidence,
            "provenance": provenance or {},
        }
    )


def facts_from_autoanosis_context(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize currently known WP/mobile context shapes into canonical facts."""

    if not isinstance(context, dict):
        return []

    facts: list[dict[str, Any]] = []

    # --- Profile / condition ---
    profile = context.get("user_profile")
    if isinstance(profile, dict):
        condition = _first(profile, "condition", "autoimmune_type", "diagnosis")
        if condition:
            _add_fact(
                facts,
                fact_type="condition.profile",
                fact_key="condition.primary",
                value=str(condition),
                source="user_profile",
                observed_at=_first(profile, "observed_at", "updated_at"),
                updated_at=profile.get("updated_at"),
                status=str(profile.get("status") or "user_reported"),
                confidence=str(profile.get("confidence") or "unknown"),
            )

    direct_condition = _first(context, "autoimmune_type", "condition")
    if direct_condition:
        _add_fact(
            facts,
            fact_type="condition.profile",
            fact_key="condition.primary",
            value=str(direct_condition),
            source="wordpress_snapshot",
            observed_at=_first(context, "profile_updated_at", "updated_at"),
            status="user_reported",
        )

    # --- Medications ---
    medication_container = context.get("medications")
    if isinstance(medication_container, dict):
        medications = (
            medication_container.get("current_medications")
            or medication_container.get("items")
            or medication_container.get("medications")
            or []
        )
    else:
        medications = medication_container or []

    for item in _as_list(medications):
        if not isinstance(item, dict):
            continue
        name = _first(item, "name", "medication_name", "title")
        if not name:
            continue
        identifier = _first(item, "id", "medication_id", "slug", "name")
        value = {
            "name": name,
            "dosage": _first(item, "dosage", "dose"),
            "schedule": item.get("time_slots") or item.get("schedule"),
            "record_status": _first(item, "status", "state"),
        }
        _add_fact(
            facts,
            fact_type="medication.record",
            fact_key=f"medication.{_safe_key(identifier)}",
            value=value,
            source="medication",
            source_reference_id=_first(item, "id", "medication_id"),
            observed_at=_first(item, "updated_at", "start_date", "created_at"),
            updated_at=item.get("updated_at"),
            status=str(item.get("continuity_status") or "user_reported"),
            confidence=str(item.get("confidence") or "unknown"),
        )

    # --- Today's dose states (mobile context) ---
    today_doses_raw = context.get("today_doses")
    if isinstance(today_doses_raw, dict):
        today_dose_items = today_doses_raw.get("doses") or []
    else:
        today_dose_items = today_doses_raw or []

    for item in _as_list(today_dose_items):
        if not isinstance(item, dict):
            continue
        identifier = _first(item, "dose_id", "id", "medication_id")
        scheduled_date = _first(item, "scheduled_date", "date")
        scheduled_time = _first(item, "scheduled_time", "time")
        observed = None
        if scheduled_date and scheduled_time:
            observed = f"{scheduled_date}T{scheduled_time}"
        elif scheduled_date:
            observed = scheduled_date
        _add_fact(
            facts,
            fact_type="dose.state",
            fact_key=f"dose.{_safe_key(identifier)}",
            value={
                "medication_id": item.get("medication_id"),
                "status": _first(item, "status", "dose_status"),
                "scheduled_date": scheduled_date,
                "scheduled_time": scheduled_time,
            },
            source="medication",
            source_reference_id=identifier,
            observed_at=observed,
            updated_at=_first(item, "taken_at", "updated_at"),
            status="user_reported",
        )

    # --- Check-ins ---
    # Mobile home snapshot: today's canonical check-in.
    home_snapshot = context.get("home_snapshot")
    if isinstance(home_snapshot, dict):
        today_checkin = home_snapshot.get("today_checkin")
        if isinstance(today_checkin, dict):
            observed = _first(today_checkin, "date", "observed_at", "created_at")
            value = {
                "pain": _first(today_checkin, "pain", "pain_level"),
                "fatigue": _first(today_checkin, "fatigue", "fatigue_level"),
                "energy": _first(today_checkin, "energy", "energy_level"),
                "mood": _first(today_checkin, "mood", "mood_level"),
                "stiffness": _first(today_checkin, "stiffness", "stiffness_level"),
                "inflammation": _first(today_checkin, "inflammation", "inflammation_level"),
                "notes": today_checkin.get("notes"),
            }
            value = {key: val for key, val in value.items() if val is not None}
            _add_fact(
                facts,
                fact_type="checkin.event",
                fact_key=f"checkin.{_safe_key(observed or 'today')}",
                value=value,
                source="check_in",
                observed_at=observed,
                status="user_reported",
            )

    # Mobile longitudinal analytics carries recent_records from the canonical
    # check-in analytics endpoint. These are real records, not inferred trends.
    longitudinal = context.get("longitudinal_checkin_analytics")
    if isinstance(longitudinal, dict):
        for item in _as_list(longitudinal.get("recent_records")):
            if not isinstance(item, dict):
                continue
            observed = _first(item, "date", "observed_at", "created_at")
            if not observed:
                continue
            value = {
                key: item.get(key)
                for key in (
                    "pain",
                    "fatigue",
                    "energy",
                    "mood",
                    "stiffness",
                    "inflammation",
                    "notes",
                )
                if item.get(key) is not None
            }
            _add_fact(
                facts,
                fact_type="checkin.event",
                fact_key=f"checkin.{_safe_key(observed)}",
                value=value,
                source="check_in",
                observed_at=observed,
                status="user_reported",
            )

    checkins = context.get("recent_checkins")
    if isinstance(checkins, dict):
        checkin_items = (
            checkins.get("items")
            or checkins.get("checkins")
            or checkins.get("history")
            or []
        )
    else:
        checkin_items = checkins or []

    for index, item in enumerate(_as_list(checkin_items)):
        if not isinstance(item, dict):
            continue
        observed = _first(item, "observed_at", "created_at", "date", "checkin_date")
        identifier = _first(item, "id", "checkin_id", observed, index)
        value = {
            key: item.get(key)
            for key in (
                "pain",
                "fatigue",
                "energy",
                "mood",
                "stiffness",
                "inflammation",
                "notes",
            )
            if item.get(key) is not None
        }
        _add_fact(
            facts,
            fact_type="checkin.event",
            fact_key=f"checkin.{_safe_key(identifier)}",
            value=value,
            source="check_in",
            source_reference_id=_first(item, "id", "checkin_id"),
            observed_at=observed,
            updated_at=item.get("updated_at"),
            status="user_reported",
        )

    # --- Structured exams / labs ---
    exam_candidates = []
    for key in ("structured_exam_results", "test_results", "exam_results"):
        value = context.get(key)
        if isinstance(value, list):
            exam_candidates.extend(value)
        elif isinstance(value, dict):
            for nested_key in ("results", "items", "tests"):
                nested = value.get(nested_key)
                if isinstance(nested, list):
                    exam_candidates.extend(nested)

    for item in exam_candidates:
        if not isinstance(item, dict):
            continue
        name = _first(item, "display_name", "name", "marker", "test_name")
        if not name:
            continue
        value = _first(item, "value_numeric", "value", "value_text")
        code = _first(item, "code", "marker_code", "display_name", "name")
        observed = _first(
            item,
            "measurement_at",
            "performed_at",
            "observed_at",
            "date",
            "reported_at",
        )
        needs_review = bool(item.get("needs_review"))
        confidence_raw = item.get("confidence") or item.get("parser_confidence")
        try:
            confidence_num = float(confidence_raw) if confidence_raw is not None else None
        except (TypeError, ValueError):
            confidence_num = None
        confidence = "unknown"
        if confidence_num is not None:
            confidence = "high" if confidence_num >= 0.9 else ("medium" if confidence_num >= 0.7 else "low")

        _add_fact(
            facts,
            fact_type="exam.result",
            fact_key=f"exam.{_safe_key(code)}",
            value={"name": name, "value": value},
            unit=item.get("unit"),
            source="uploaded_document",
            source_reference_id=_first(item, "report_id", "document_id", "id"),
            observed_at=observed,
            updated_at=item.get("updated_at"),
            status="conflicting" if needs_review else "user_reported",
            confidence=confidence,
            provenance={
                "normalization_status": item.get("normalization_status"),
                "review_reason": item.get("review_reason"),
            },
        )

    # --- BEST latest snapshot presence/timestamp ---
    best = context.get("best_protocol") or context.get("best")
    if isinstance(best, dict) and best:
        saved_at = _first(best, "_saved_at", "saved_at", "updated_at", "created_at")
        _add_fact(
            facts,
            fact_type="best.snapshot",
            fact_key="best.latest",
            value={"present": True},
            source="best_protocol",
            source_reference_id=_first(best, "id", "snapshot_id"),
            observed_at=saved_at,
            updated_at=saved_at,
            status="user_reported",
        )

    # --- Medical document archive presence/timeline ---
    for item in _as_list(context.get("medical_documents")):
        if not isinstance(item, dict):
            continue
        identifier = _first(item, "id", "document_id", "sha256", "document_title")
        if not identifier:
            continue
        _add_fact(
            facts,
            fact_type="document.record",
            fact_key=f"document.{_safe_key(identifier)}",
            value={
                "title": _first(item, "document_title", "display_title", "original_filename"),
                "category": _first(item, "document_category", "document_type"),
            },
            source="uploaded_document",
            source_reference_id=_first(item, "id", "document_id"),
            observed_at=_first(item, "document_date", "performed_at", "uploaded_at"),
            updated_at=item.get("updated_at"),
            status="user_reported",
        )

    return facts
