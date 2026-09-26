# Security Policy

SCF Auto-Crosswalker is a personal open-source project maintained by one person in their own time. There is no support contract or response-time commitment, but reports are welcome and will be read.

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub's private vulnerability reporting: the **Report a vulnerability** button in this repository's **Security** tab. Do not open a public issue for a security problem.

A useful report includes the affected file, steps to reproduce, and the impact you expect.

## Supported versions

Only the current `main` branch is supported. There are no maintained release branches.

## Scope

In scope: the code in this repository, including the Streamlit app (`app.py`, `src/ui/`), the mapping and validation logic (`src/mapper.py`), the SCF download and parser (`src/fetch_scf.py`), the gap analysis (`src/gap_analysis.py`), the CSV and OSCAL exports (`src/exports.py`), the evaluation scripts, the `Dockerfile`, `docker-compose.yml` and the GitHub Actions workflows.

Out of scope: vulnerabilities in third-party dependencies that are already tracked upstream (Dependabot, dependency review and `pip-audit` run on this repository), and deployments that expose the app beyond `127.0.0.1`. The app has no authentication and is built for local, single-user use.

## Handling data safely

- **Text you submit leaves your machine.** The Crosswalker and the Audit Scope Analyzer send the input text to Groq's API: pasted policy text, extracted PDF or TXT text, or, for each Security Hub finding, its title, description, remediation text, resource types, severity and compliance status. JSON that is not a Security Hub finding is sent as submitted, including any identifiers in it. Do not submit confidential audit data unless your organization allows it. The Gap Analyzer runs locally and sends nothing.
- Never commit API keys, `.env` files or real audit data. `.env` and `data/` are git-ignored, and pre-commit runs detect-secrets.
- Model output is untrusted. Control IDs are checked against the candidates the model was given and control text is taken from the SCF database, but whether a suggested control actually fits the input still needs a person to decide.
- Model text shown in the UI is Markdown-escaped, so a prompt-injected document cannot make the page render links or load external images. CSV exports prefix cells that would start a spreadsheet formula (`=`, `+`, `-`, `@`) with an apostrophe.
- PDF uploads are read up to 50 pages, and a batch maps at most 50 distinct findings.
- The SCF workbook is downloaded from the latest release of the official `securecontrolsframework` GitHub repository over HTTPS. No checksum is published for it, so the download is trusted on the basis of that source only.
