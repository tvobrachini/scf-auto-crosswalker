# Lab data

Sample inputs for trying the three tools, and raw outputs from earlier runs. The inputs are synthetic; the account ID `123456789012` and all resource names are placeholders.

## Inputs

| File | Used by | Notes |
|---|---|---|
| `sample_endpoint_policy.txt` | Crosswalker | A short endpoint encryption policy. |
| `aws_securityhub_finding.json` | Crosswalker (batch mode) | One finding in AWS Security Hub (ASFF) export format. Its title says `S3.8`, but its text describes the CloudFront HTTPS check; the ID is a leftover from editing a sample and does not affect mapping. |
| `sample_audit_scope.txt` | Audit Scope Analyzer | A short audit scope narrative. |
| `sample_existing_controls.csv` | Gap Analyzer | A control list that uses its **own** numbering (`SEC-01`, `IAM-01`, …). Only IDs that happen to be SCF IDs can match, so the Gap Analyzer flags the rest as "not SCF control IDs". It also shows that the tool compares IDs only: `CRY-02` is named "Data Encryption in Transit" here, and the tool does not check that the name matches SCF's `CRY-02`. |

## Sample outputs (`sample_outputs/`)

These files are raw, unreviewed output from an 8B model (`llama-3.1-8b-instant`). They were generated **before** the validation added in this version, and they are kept as a record of the failure modes that validation now handles:

- **`audit_scope_analysis_result.json`**: every recommended control ID (`AC-1`, `IA-2`, `SC-8`, `AU-2`, …) is a NIST SP 800-53 ID, not an SCF ID. The current code checks scope recommendations against the SCF database and would reject all ten.
- **`aws_finding_mapping_result.csv`** and **`policy_mapping_result.csv`**: the control IDs exist in SCF, but several matches are weak (for example, a laptop-encryption policy mapped to `DCH-05.5`, which is about human-readable security labels). The description column was written by the model, which is why some entries start with a domain prefix; the current code takes descriptions from the SCF database instead. The columns also differ from the app's current CSV export.

To regenerate them with the current code, run `uv run python scripts/generate_mock_output.py` (needs `GROQ_API_KEY`, access to Hugging Face and the SCF data in `data/`), then review the results before committing them.

The CSVs quote short excerpts of SCF control text with attribution. SCF content © Secure Controls Framework, licensed CC BY-ND 4.0.
