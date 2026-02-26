import os
import json
import pandas as pd
import sys

# Ensure src is in path since script is in scripts/
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'src'))
from mapper import map_text_to_scf, analyze_audit_scope

LAB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'lab_data')
OUT_DIR = os.path.join(LAB_DIR, 'sample_outputs')

def run_policy_mapping():
    policy_file = os.path.join(LAB_DIR, 'sample_endpoint_policy.txt')
    if not os.path.exists(policy_file):
        print("[-] Missing endpoint policy file.")
        return
        
    with open(policy_file, 'r') as f:
        policy = f.read()
        
    result = map_text_to_scf(policy, top_k=3)
    if result:
        data = []
        for mapping in result.mappings:
            data.append({
                "Control ID": mapping.control_id,
                "Domain": mapping.domain,
                "Description": mapping.description,
                "Justification": mapping.justification,
                "Confidence": f"{mapping.confidence}%",
            })
        df = pd.DataFrame(data)
        out_path = os.path.join(OUT_DIR, 'policy_mapping_result.csv')
        df.to_csv(out_path, index=False)
        print(f"[+] Policy mapping saved to {out_path}")

def run_aws_mapping():
    aws_file = os.path.join(LAB_DIR, 'aws_securityhub_finding.json')
    if not os.path.exists(aws_file):
        print("[-] Missing AWS finding file.")
        return
        
    with open(aws_file, 'r') as f:
        finding = json.load(f)
        
    # Security Hub exports have a Findings list
    finding_text = json.dumps(finding.get("Findings", [finding])[0])
    
    result = map_text_to_scf(finding_text, top_k=3)
    if result:
        data = []
        for mapping in result.mappings:
            data.append({
                "Control ID": mapping.control_id,
                "Domain": mapping.domain,
                "Description": mapping.description,
                "Justification": mapping.justification,
                "Confidence": f"{mapping.confidence}%",
            })
        df = pd.DataFrame(data)
        out_path = os.path.join(OUT_DIR, 'aws_finding_mapping_result.csv')
        df.to_csv(out_path, index=False)
        print(f"[+] AWS Security Hub mapping saved to {out_path}")

def run_scope_analysis():
    scope_file = os.path.join(LAB_DIR, 'sample_audit_scope.txt')
    if not os.path.exists(scope_file):
        print("[-] Missing audit scope file.")
        return
        
    with open(scope_file, 'r') as f:
        scope = f.read()
        
    rec = analyze_audit_scope(scope)
    if rec:
        out_data = {
            "Recommended_Domains": rec.recommended_domains,
            "Recommended_Controls": rec.recommended_control_ids,
            "Reasoning": rec.reasoning
        }
        out_path = os.path.join(OUT_DIR, 'audit_scope_analysis_result.json')
        with open(out_path, 'w') as f:
            json.dump(out_data, f, indent=4)
        print(f"[+] Scope analysis saved to {out_path}")

if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    if not os.environ.get("GROQ_API_KEY"):
        print("[-] Warning: GROQ_API_KEY is not set. The LLM calls will fail.")
        sys.exit(1)
        
    print("[*] Generating lab data outputs...")
    run_policy_mapping()
    run_aws_mapping()
    run_scope_analysis()
    print("[+] All mock outputs generated successfully.")
