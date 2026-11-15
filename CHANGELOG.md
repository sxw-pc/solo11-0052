# Changelog

All notable changes to this project are documented here. The project follows
Semantic Versioning.

## Unreleased

- Add optional `subject_field` to stratified plans. When declared, business
  subjects are identified by that field and may appear on multiple rows with
  different `strata_field` values; each subject is attributed to a single
  stratum via its smallest-key row, quotas count subjects rather than rows,
  and the selected sample is deduplicated per subject.
- Subject identity values may repeat across rows (no longer treated as errors
  apart from key conflicts), while `key_field` uniqueness and the
  `population_fingerprint` roster semantics are unchanged. New dataset error
  codes `DATASET_MISSING_SUBJECT_FIELD` and `DATASET_MISSING_SUBJECT`.
- Plans without `subject_field` keep byte-identical behavior and outputs.

## 0.1.0 - 2026-11-14

- Initial release of the local, offline sampling attestation tool.
- Declarative YAML plans with strict field whitelisting and stable error codes.
- CSV/JSONL loaders with duplicate/missing-key detection and population roster fingerprints.
- Deterministic simple random, stratified, systematic and one-stage cluster samplers.
- Seeded effective-seed derivation and sorted/ordered sample fingerprints.
- Verification of quota, sampling-rate range, coverage, key uniqueness and population subset checks.
- Failure attribution, JSON/Markdown reports, SQLite ledger, read-only Flask API.
- Reproducibility verification with added/missing sample-key localization.
- Deterministic archive export with SHA-256 manifest and tamper verification.
- Offline pytest suite with a socket kill-switch.

### Scope notes

Only deterministic sampling and verification are supported. Weighted sampling,
PPS, multi-stage sampling, statistical inference, federated sampling and
machine-learning train/test splits are intentionally out of scope.
