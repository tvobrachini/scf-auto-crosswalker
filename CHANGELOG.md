# Changelog

Notable changes. Dates are UTC.

## [Unreleased]

### Added
- Gap Analyzer reports coverage per framework requirement (for example, 8 of 69 SOC 2 criteria with a listed control), with a *By requirement* tab and CSV. SOC 2 points of focus roll up to their criterion and ISO 27001 list items to their clause (ADR-011).
- Control lists with their own numbering work through an SCF mapping column. The ID column is detected by which column names the most SCF IDs, and a cell can hold several IDs. New sample `lab_data/sample_controls_with_scf_mapping.csv`.
- `CONTRIBUTING.md`.

### Changed
- `app.py` split into one module per page under `src/ui/pages/`.
- README intro states the retrieval result as a ceiling for the model, not an accuracy figure.

## [0.1.0] - 2026-09-27

First tagged release.

### Added
- Three tools: SCF Auto-Crosswalker (policy text, documents and Security Hub findings), Compliance Gap Analyzer, Audit Scope Analyzer.
- Retrieval with `all-MiniLM-L6-v2`, one structured Groq call, and validation that only accepts retrieved SCF IDs, with control content copied from the SCF database.
- CSV exports and OSCAL 1.2 `mapping-collection` export (`draft`, `intersects-with`), validated with compliance-trestle in the tests.
- `DEMO_MODE` with a synthetic catalog and a canned model, for running all three tools without keys or downloads.
- Evaluation harness against AWS's and SCF's published NIST SP 800-53 mappings, with random and TF-IDF baselines. First results (retrieval only): 62.0% hit rate at k = 50 on 221 Security Hub controls.
- CI: pre-commit (detect-secrets, ruff, bandit), pyright, tests on Python 3.11–3.13 with an 85% coverage floor, pip-audit, dependency review, Docker build; actions pinned by SHA.
