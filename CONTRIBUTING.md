# Contributing

This is a personal portfolio project, but issues and pull requests are welcome.

## Setup

```bash
uv sync                       # Python 3.11–3.13; installs dev dependencies too
uv run pre-commit install     # detect-secrets, ruff, ruff-format, bandit
DEMO_MODE=1 uv run streamlit run app.py   # no keys or downloads needed
```

The real tools need a Groq key in `.env` (see `.env.example`) and the SCF download from the sidebar.

## Before opening a pull request

Run what CI runs:

```bash
uv sync --frozen              # fails if uv.lock is out of date
uv run pre-commit run --all-files
uv run pyright src/
uv run pytest tests/ --cov=src --cov-fail-under=85   # offline
```

Tests must not call Groq, Hugging Face or the SCF download; use the fakes in `tests/conftest.py` (see ADR-007 in [DECISIONS.md](DECISIONS.md)).

## Ground rules

- **No SCF content in the repository.** The SCF is licensed CC BY-ND 4.0, so control text, the workbook and anything derived from it stay in the gitignored `data/` directory (ADR-002). SCF control IDs are fine. The same goes for AWS documentation text used by the evaluation (CC BY-SA 4.0): commit IDs and numbers only.
- **The model proposes, the catalog supplies.** Any new model-backed feature returns IDs that are validated against the retrieved candidates, with content taken from the SCF database (ADR-004).
- **Claims match measurement.** A change that affects retrieval or prompting should re-run `scripts/run_eval.py` and update `eval/` with the result, including when it gets worse.
- **Significant decisions get an ADR** in [DECISIONS.md](DECISIONS.md).

Security issues: see [SECURITY.md](SECURITY.md).
