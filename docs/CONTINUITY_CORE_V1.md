# Autoanosis Continuity Core v1

## Product purpose

Continuity Core turns the existing Autoanosis data silos into one consistent
continuity layer. It is not a diagnosis engine. It answers four product
questions:

1. What Autoanosis currently has on record.
2. What changed over time.
3. What is explicitly stale, conflicting, or missing.
4. What safe process action can help the user prepare/update/clarify next.

## North Star

A patient-owned, timestamped, provenance-aware longitudinal health record that
can power the AI Assistant, Mobile, Doctor Visit Pack/BEST, medications,
exams, doctor sharing and Rights Navigator without each subsystem inventing a
different version of the user's current state.

## v1 scope in this branch

- Pure continuity analysis engine.
- Conservative adapters for the current WordPress/mobile snapshot shapes.
- Read-only authenticated endpoint:
  - POST /continuity/v1/preview
- No database writes.
- No production data migration.
- No treatment or dose recommendations.
- No automatic stale classification unless an explicit status, valid_until or
  source staleness policy exists.
- Unit tests for changes, stale/currentness, conflicts, missing domains,
  privacy and safety behavior.

## Canonical fact contract

Each normalized fact may carry:

- fact_type
- fact_key
- value
- unit
- source
- source_reference_id
- observed_at
- updated_at
- valid_from
- valid_until
- status: confirmed | user_reported | outdated | conflicting | missing
- confidence: high | medium | low | unknown
- provenance

The adapter never copies ordinary identity fields such as user_name or email
into Continuity Core facts.

## Why preview-first

Current production data is split between WordPress/MySQL, Render/PostgreSQL,
mobile snapshots and several legacy bridges. Persisting a new canonical store
before validating the contract would create yet another silo.

The preview endpoint allows us to validate the continuity model against the
existing live payloads first. Persistence/event sourcing is the next milestone
after the contract is stable.

## Next milestone after this PR

Continuity Core v1.1:

- persistent event/fact store;
- source adapters for medications, check-ins, exams/documents and BEST;
- deterministic supersession/conflict rules;
- "since last visit" Doctor Pack payload;
- AI consumption of continuity summary instead of raw stale profile fields.
