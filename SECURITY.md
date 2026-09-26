# Security Policy

SCF Auto-Crosswalker is a personal open-source project maintained by one person in their own time. There is no support contract or response-time commitment, but reports are welcome and will be read.

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub's private vulnerability reporting: the **Report a vulnerability** button in this repository's **Security** tab. Do not open a public issue for a security problem.

A useful report includes the affected file, steps to reproduce, and the impact you expect.

## Supported versions

Only the current `main` branch is supported. There are no maintained release branches.

## Scope

In scope: the code in this repository, including the Streamlit app (`app.py`, `src/ui/`), the mapping and validation logic (`src/mapper.py`), the SCF download and parser (`src/fetch_scf.py`), the gap analysis (`src/gap_analysis.py`), the `Dockerfile`, `docker-compose.yml` and the GitHub Actions workflows.

Out of scope: vulnerabilities in third-party dependencies that are already tracked upstream (Dependabot, dependency review and `pip-audit` run on this repository), and deployments that expose the app beyond `127.0.0.1`. The app has no authentication and is built for local, single-user use.

## Handling data safely

- **Text you submit leaves your machine.** The Crosswalker and the Audit Scope Analyzer send the input text (policy text, extracted PDF text, or the title, description and remediation of each Security Hub finding) to Groq's API. Do not submit confidential audit data unless your organization allows it. The Gap Analyzer runs locally and sends nothing.
- Never commit API keys, `.env` files or real audit data. `.env` and `data/` are git-ignored, and pre-commit runs detect-secrets.
- Model output is untrusted. Control IDs are checked against the SCF database and control text is taken from it, but whether a suggested control actually fits the input still needs a person to decide.
- The SCF workbook is downloaded from the latest release of the official `securecontrolsframework` GitHub repository over HTTPS. No checksum is published for it, so the download is trusted on the basis of that source only.
