"""Pure continuity analysis for Autoanosis.

This module is deliberately free of Flask/DB dependencies so the product rules
can be unit-tested independently from WordPress, Render and mobile clients.

Safety boundary:
- describe what Autoanosis data contains;
- identify explicit stale/conflicting/missing records;
- generate process-oriented next actions only;
- never diagnose, recommend treatment, or recommend dose changes.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Iterable


ALLOWED_STATUSES = {
    "confirmed",
    "user_reported",
    "outdated",
    "conflicting",
    "missing",
}

ALLOWED_CONFIDENCE = {"high", "medium", "low", "unknown"}


def _parse_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        try:
            dt = datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
                try:
                    dt = datetime.strptime(raw, fmt)
                    break
                except ValueError:
                    dt = None
            if dt is None:
                return None
    else:
        return None

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _stable_value(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_stable_value(item) for item in value]
    return value


def _same_value(left: Any, right: Any) -> bool:
    return _stable_value(left) == _stable_value(right)


def _normalise_fact(raw: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    fact_key = str(raw.get("fact_key") or "").strip()
    fact_type = str(raw.get("fact_type") or "").strip()
    source = str(raw.get("source") or "unknown").strip()

    if not fact_key or not fact_type:
        return None

    status = str(raw.get("status") or "user_reported").strip().lower()
    if status not in ALLOWED_STATUSES:
        status = "user_reported"

    confidence = str(raw.get("confidence") or "unknown").strip().lower()
    if confidence not in ALLOWED_CONFIDENCE:
        confidence = "unknown"

    observed_at = _parse_dt(raw.get("observed_at"))
    updated_at = _parse_dt(raw.get("updated_at"))
    valid_from = _parse_dt(raw.get("valid_from"))
    valid_until = _parse_dt(raw.get("valid_until"))

    provenance = raw.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}

    stale_reason = None
    if status == "outdated":
        stale_reason = "explicit_status"
    elif valid_until and valid_until < now:
        stale_reason = "validity_expired"
    else:
        stale_after_days = provenance.get("stale_after_days")
        if stale_after_days is not None and observed_at is not None:
            try:
                threshold = int(stale_after_days)
            except (TypeError, ValueError):
                threshold = None
            if threshold is not None and threshold >= 0:
                age_days = (now - observed_at).total_seconds() / 86400
                if age_days > threshold:
                    stale_reason = "source_policy"

    currentness = "unknown"
    if stale_reason:
        currentness = "stale"
    elif observed_at or updated_at or valid_from or valid_until:
        currentness = "dated"

    return {
        "fact_type": fact_type,
        "fact_key": fact_key,
        "value": deepcopy(raw.get("value")),
        "unit": raw.get("unit"),
        "source": source,
        "source_reference_id": raw.get("source_reference_id"),
        "observed_at": _iso(observed_at),
        "updated_at": _iso(updated_at),
        "valid_from": _iso(valid_from),
        "valid_until": _iso(valid_until),
        "status": status,
        "confidence": confidence,
        "currentness": currentness,
        "stale_reason": stale_reason,
        "provenance": deepcopy(provenance),
    }


def _fact_sort_key(fact: dict[str, Any]) -> tuple[datetime, datetime]:
    observed = _parse_dt(fact.get("observed_at")) or datetime.min.replace(tzinfo=timezone.utc)
    updated = _parse_dt(fact.get("updated_at")) or datetime.min.replace(tzinfo=timezone.utc)
    return observed, updated


def _domain_from_type(fact_type: str) -> str:
    lowered = fact_type.lower()
    if lowered.startswith("medication") or lowered.startswith("dose"):
        return "medication"
    if lowered.startswith("exam") or lowered.startswith("lab") or lowered.startswith("document"):
        return "exam"
    if lowered.startswith("checkin") or lowered.startswith("symptom"):
        return "checkin"
    if lowered.startswith("condition") or lowered.startswith("profile"):
        return "condition"
    if lowered.startswith("best"):
        return "best"
    if lowered.startswith("rights") or lowered.startswith("kepa"):
        return "rights"
    return lowered.split(".", 1)[0]


def _safe_action(kind: str, fact_key: str | None = None, domain: str | None = None) -> dict[str, str]:
    if kind == "stale":
        return {
            "type": "confirm_or_update",
            "target": fact_key or "",
            "message": "Confirm or update this record before relying on it as current.",
        }
    if kind == "conflict":
        return {
            "type": "review_conflict",
            "target": fact_key or "",
            "message": "Review the conflicting records and keep both sources visible until clarified.",
        }
    if kind == "missing":
        return {
            "type": "add_missing_data",
            "target": domain or "",
            "message": "Add or connect this missing data domain if it is relevant to your Autoanosis record.",
        }
    return {
        "type": "review",
        "target": fact_key or domain or "",
        "message": "Review this item in Autoanosis.",
    }


def build_continuity_summary(
    facts: Iterable[dict[str, Any]],
    *,
    required_domains: Iterable[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the canonical continuity summary.

    The function never invents timestamps or stale status. A record becomes
    stale only from an explicit status, an explicit valid_until, or an explicit
    source policy (provenance.stale_after_days).
    """

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)

    normalised = []
    seen_fingerprints: set[str] = set()
    for raw in facts:
        if not isinstance(raw, dict):
            continue
        fact = _normalise_fact(raw, now)
        if fact is None:
            continue

        # The same underlying record may arrive through both home snapshot and
        # longitudinal analytics. Collapse exact duplicates so the "previous"
        # value really means a previous observation, not the same day twice.
        fingerprint = repr(
            (
                fact.get("fact_key"),
                fact.get("observed_at"),
                fact.get("updated_at"),
                _stable_value(fact.get("value")),
                fact.get("source"),
                fact.get("status"),
            )
        )
        if fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(fingerprint)
        normalised.append(fact)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fact in normalised:
        grouped[fact["fact_key"]].append(fact)

    current: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    conflicting: list[dict[str, Any]] = []

    for fact_key, items in grouped.items():
        ordered = sorted(items, key=_fact_sort_key)
        latest = ordered[-1]
        current.append(latest)

        if latest.get("stale_reason"):
            stale.append(
                {
                    "fact_key": fact_key,
                    "fact_type": latest["fact_type"],
                    "source": latest["source"],
                    "observed_at": latest["observed_at"],
                    "reason": latest["stale_reason"],
                }
            )

        explicit_conflicts = [item for item in ordered if item["status"] == "conflicting"]
        if explicit_conflicts:
            conflicting.append(
                {
                    "fact_key": fact_key,
                    "fact_type": latest["fact_type"],
                    "sources": sorted({item["source"] for item in explicit_conflicts}),
                    "count": len(explicit_conflicts),
                }
            )

        if len(ordered) >= 2:
            previous = ordered[-2]
            if not _same_value(previous.get("value"), latest.get("value")):
                changes.append(
                    {
                        "fact_key": fact_key,
                        "fact_type": latest["fact_type"],
                        "from": deepcopy(previous.get("value")),
                        "to": deepcopy(latest.get("value")),
                        "from_observed_at": previous.get("observed_at"),
                        "to_observed_at": latest.get("observed_at"),
                        "source": latest["source"],
                    }
                )

    current.sort(key=lambda item: item["fact_key"])
    changes.sort(key=lambda item: item["fact_key"])
    stale.sort(key=lambda item: item["fact_key"])
    conflicting.sort(key=lambda item: item["fact_key"])

    present_domains = sorted({_domain_from_type(item["fact_type"]) for item in normalised})
    required = sorted({str(item).strip().lower() for item in (required_domains or []) if str(item).strip()})
    missing = [domain for domain in required if domain not in present_domains]

    dated_points = [
        _parse_dt(item.get("observed_at")) or _parse_dt(item.get("updated_at"))
        for item in normalised
    ]
    dated_points = [item for item in dated_points if item is not None]

    unknown_currentness = sum(1 for item in current if item["currentness"] == "unknown")

    next_actions: list[dict[str, str]] = []
    for item in stale:
        next_actions.append(_safe_action("stale", fact_key=item["fact_key"]))
    for item in conflicting:
        next_actions.append(_safe_action("conflict", fact_key=item["fact_key"]))
    for domain in missing:
        next_actions.append(_safe_action("missing", domain=domain))

    return {
        "schema_version": "continuity-core.v1",
        "generated_at": _iso(now),
        "data_window": {
            "from": _iso(min(dated_points)) if dated_points else None,
            "to": _iso(max(dated_points)) if dated_points else None,
        },
        "coverage": {
            "fact_count": len(normalised),
            "current_fact_count": len(current),
            "present_domains": present_domains,
            "required_domains": required,
            "missing_domains": missing,
            "unknown_currentness_count": unknown_currentness,
        },
        "current": current,
        "changes": changes,
        "stale": stale,
        "conflicting": conflicting,
        "next_actions": next_actions,
        "safety": {
            "mode": "process_guidance_only",
            "clinical_decision_support": False,
            "treatment_recommendations": False,
        },
    }
