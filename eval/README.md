# Evaluation

`scripts/run_eval.py` measures how well the pipeline agrees with two published mappings. It needs no hand labeling.

## How the gold set is built

1. **AWS → NIST.** Every AWS Security Hub control lists the NIST SP 800-53 rev 5 requirements AWS maps it to (`RelatedRequirements`, e.g. `NIST.800-53.r5 SC-8(1)`). `aws securityhub describe-standards-controls` returns them.
2. **NIST → SCF.** The SCF workbook maps each SCF control to NIST SP 800-53. That column is kept in `data/scf_parsed.json`.
3. **Gold.** A Security Hub control's gold SCF controls are the SCF controls that SCF maps to any of its 800-53 requirements. The input text is the control's title and description.

The mapping is transitive. A gold pair says the finding and the SCF control share an 800-53 requirement, not that a reviewer judged the pair. One 800-53 requirement often maps to several SCF controls, so each case can have many gold controls. The numbers measure consistency with AWS's and SCF's published mappings. They are not ground-truth accuracy.

## Run it

You need the SCF database (click **Download / Update SCF Data** in the app once), network access to Hugging Face for the embedding model, and read-only AWS credentials for step 1.

```bash
# 1. Security Hub controls with their NIST mappings (read-only).
#    Use the subscription ARN of the "NIST SP 800-53 Revision 5" standard (or AWS FSBP)
#    from `aws securityhub get-enabled-standards`.
aws securityhub describe-standards-controls \
    --standards-subscription-arn <arn> > eval/standards_controls.json

# 2. Build eval/gold.csv and score retrieval. No Groq key needed.
uv run python scripts/run_eval.py --controls eval/standards_controls.json

# 3. Score the model step too: one Groq call per case.
uv run python scripts/run_eval.py --gold eval/gold.csv --llm
```

The results table is written to `eval/results.md`.

## Metrics

| Stage | Metric | Meaning |
|---|---|---|
| Retrieval | Hit rate @k | Share of cases where at least one gold control is among the top k retrieved candidates. At k = 50 (what the model sees), a miss means the model cannot give a correct answer. |
| Retrieval | Mean recall @k | Mean share of each case's gold controls found in the top k. |
| Model | Precision of suggestions | Share of the controls the pipeline suggested (up to 3 per case) that are gold. |
| Model | Hit rate | Share of cases with at least one gold suggestion. |
| Model | Cases with no valid suggestion | Cases where every ID the model returned was rejected. |

## Results

Not run yet. Paste `eval/results.md` here, with the date, the SCF release and the Groq model, after the first run.
