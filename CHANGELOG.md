# Changelog

All notable changes to this project are documented here. The project follows
Semantic Versioning.

## Unreleased

- `verify` output gains a top-level `by_strata` breakdown: added/missing
  sample keys are attributed to strata over the complete diff sets (never the
  truncated display lists). Added keys resolve via the current dataset and
  plan `strata_field`; missing keys resolve via the baseline dataset restored
  from the ledger's plan copy. Keys without a matching row fall into an
  explicit `unclassified` stratum, plans without `strata_field` degrade to a
  single `all` group, and per-stratum counts always sum to the top-level
  `added_count`/`missing_count`. `diff_explanations` gains per-stratum lines.

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
