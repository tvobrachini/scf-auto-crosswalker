"""
Regenerate the sample outputs in lab_data/sample_outputs/ from the lab inputs.

Needs GROQ_API_KEY, network access to Hugging Face (embedding model) and the
SCF database in data/ (use the app's sidebar or `python src/fetch_scf.py`).
The outputs are raw model suggestions, not reviewed mappings.
"""

import json
import os
import sys

import pandas as pd

# Ensure src is in path since script is in scripts/
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))
from findings import finding_to_text  # noqa: E402
from mapper import analyze_audit_scope, map_text_to_scf  # noqa: E402

LAB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "lab_data")
OUT_DIR = os.path.join(LAB_DIR, "sample_outputs")


def _write_mappings(result, out_name: str) -> None:
    rows = [
        {
            "SCF Control ID": m.control_id,
            "SCF Domain": m.domain,
            "Control Description": m.description,
            "Model Confidence (%)": m.confidence,
            "Model Justification": m.justification,
        }
        for m in result.mappings
    ]
    out_path = os.path.join(OUT_DIR, out_name)
    pd.DataFrame(rows).to_csv(out_path, index=False)
    print(f"[+] Saved {out_path}")
    if result.rejected_control_ids:
        print(f"    Dropped non-SCF IDs: {', '.join(result.rejected_control_ids)}")


def run_policy_mapping():
    policy_file = os.path.join(LAB_DIR, "sample_endpoint_policy.txt")
    with open(policy_file, "r", encoding="utf-8") as f:
        policy = f.read()

    result = map_text_to_scf(policy, top_k=3)
    if result:
        _write_mappings(result, "policy_mapping_result.csv")


def run_aws_mapping():
    aws_file = os.path.join(LAB_DIR, "aws_securityhub_finding.json")
    with open(aws_file, "r", encoding="utf-8") as f:
        finding = json.load(f)

    # Security Hub exports have a Findings list; the app maps each one.
    finding_text = finding_to_text(finding.get("Findings", [finding])[0])

    result = map_text_to_scf(finding_text, top_k=3)
    if result:
        _write_mappings(result, "aws_finding_mapping_result.csv")


def run_scope_analysis():
    scope_file = os.path.join(LAB_DIR, "sample_audit_scope.txt")
    with open(scope_file, "r", encoding="utf-8") as f:
        scope = f.read()

    rec = analyze_audit_scope(scope)
    if rec:
        out_data = {
            "Recommended_Domains": rec.recommended_domains,
            "Recommended_Controls": rec.recommended_control_ids,
            "Rejected_Non_SCF_IDs": rec.rejected_control_ids,
            "Reasoning": rec.reasoning,
        }
        out_path = os.path.join(OUT_DIR, "audit_scope_analysis_result.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out_data, f, indent=4)
        print(f"[+] Saved {out_path}")


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    if not os.environ.get("GROQ_API_KEY"):
        print("[-] GROQ_API_KEY is not set. The LLM calls would fail.")
        sys.exit(1)

    print("[*] Generating lab data outputs...")
    run_policy_mapping()
    run_aws_mapping()
    run_scope_analysis()
    print("[+] Done. Review the outputs before committing them.")
