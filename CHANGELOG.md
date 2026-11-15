# Changelog

All notable changes to this project are documented here. The project follows
Semantic Versioning.

## Unreleased

- `export --with-history` now writes `history.json` with every run of a `task_id`
  (`run_id`, `created_at`, `status`, `sample_fingerprint`, `check_counts` and the
  full added/missing sample-key diff versus the previous run), registered in
  `manifest.json` with its SHA-256 and size.
- `verify-archive` accepts legacy four-file archives unchanged and, when
  `history.json` is present, reports reproducibility forks with the adjacent
  `run_id` pair and both fingerprints (`ARCHIVE_REPRODUCIBILITY_FORK`) instead of
  treating them as tampering; a modified `history.json` still fails with
  `ARCHIVE_HASH_MISMATCH`. Malformed history payloads raise
  `ARCHIVE_HISTORY_INVALID`.
- New `Ledger.list_runs_by_task()` query; default export output remains byte-for-byte
  identical to the previous release.

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
