import os
import sys

# Ensure the src directory is available for imports
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

import streamlit as st
import json
import pandas as pd
import pdfplumber
from fetch_scf import RAW_SCF_FILE, PARSED_JSON_FILE, download_scf, parse_scf
from mapper import map_text_to_scf, analyze_audit_scope

st.set_page_config(page_title="GRC Assistant", page_icon="🛡️", layout="wide")

# --- Custom CSS for Premium Look ---
st.markdown("""
<style>
    /* Main Layout */
    .stApp {
        background-color: #0a0a0a;
        color: #ededed;
        font-family: 'Inter', sans-serif;
    }
    
    /* Headers & Text */
    h1, h2, h3 {
        color: #ffffff !important;
        font-weight: 700 !important;
        letter-spacing: -0.02em;
    }
    
    /* Sidebar Styling */
    [data-testid="stSidebar"] {
        background-color: #121212 !important;
        border-right: 1px solid rgba(255,255,255,0.05);
    }
    
    /* Buttons */
    .stButton>button {
        background: linear-gradient(135deg, #8A05BE 0%, #4338ca 100%);
        color: white;
        border: none;
        border-radius: 8px;
        padding: 0.5rem 1rem;
        font-weight: 500;
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        opacity: 0.9;
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(138,5,190,0.3);
    }
    
    /* Dataframes/Tables */
    [data-testid="stDataFrame"] {
        border-radius: 8px;
        overflow: hidden;
        border: 1px solid rgba(255,255,255,0.1);
    }
    
    /* File Uploader */
    [data-testid="stFileUploader"] {
        border: 1px dashed rgba(138,5,190,0.4);
        border-radius: 8px;
        background-color: rgba(255,255,255,0.02);
    }
</style>
""", unsafe_allow_html=True)

# --- Sidebar Navigation & Setup ---
with st.sidebar:
    st.title("🛡️ Secure Controls Framework (SCF)")
    st.markdown("### GRC Assistant Platform")
    
    app_mode = st.radio("Select Tool", [
        "🔍 SCF Auto-Crosswalker",
        "🎯 Audit Scope Analyzer",
        "📉 Compliance Gap Analyzer"
    ])
    
    st.markdown("---")
    st.header("⚙️ System Status")
    
    api_key_status = "🟢 Set" if os.environ.get("GROQ_API_KEY") else "🔴 Missing in .env"
    st.write(f"**Groq Llama-3 API Key:** {api_key_status}")
    
    db_status = "🟢 Ready" if os.path.exists(PARSED_JSON_FILE) else "🔴 Not Found"
    st.write(f"**JSON SCF Database:** {db_status}")
    
    if st.button("🔄 Force Update SCF Framework Data"):
        with st.spinner("Downloading from official SCF GitHub..."):
            if download_scf():
                if parse_scf():
                    st.success("Successfully updated and parsed the latest SCF!")
                    st.rerun()
                else:
                    st.error("Failed to parse the SCF Excel file.")
            else:
                st.error("Failed to download the SCF.")

    # Advanced Settings specifically for Crosswalker
    if app_mode == "🔍 SCF Auto-Crosswalker":
        st.markdown("---")
        st.header("⚙️ Advanced AI Settings")
        st.markdown("Customize the LLM's internal system prompt.")
        persona_options = [
            "None (Default General Auditor)",
            "Act as a strict PCI-DSS Qualified Security Assessor (QSA).",
            "Act as a FedRAMP 3PAO Assessor focusing on US Federal standards.",
            "Act as a GDPR Data Privacy Officer (DPO) focusing heavily on PII."
        ]
        selected_persona = st.selectbox("AI Persona Lens", persona_options)
        persona_prompt = None if "None" in selected_persona else selected_persona
    else:
        persona_prompt = None

    st.markdown("---")
    st.info("Licensed under CC Attribution-NoDerivatives 4.0. Data provided by securecontrolsframework.com")

LAB_DATA_DIR = os.path.join(os.path.dirname(__file__), 'lab_data')

def load_lab_files(extension=None):
    if not os.path.exists(LAB_DATA_DIR):
        return []
    files = [f for f in os.listdir(LAB_DATA_DIR) if os.path.isfile(os.path.join(LAB_DATA_DIR, f))]
    if extension:
        files = [f for f in files if f.endswith(extension)]
    return files


# ==========================================
# TOOL 1: SCF Auto-Crosswalker
# ==========================================
if app_mode == "🔍 SCF Auto-Crosswalker":
    st.title("🔍 SCF Auto-Crosswalker")
    st.markdown("Automatically align your raw IT policies, incredibly long PDFs, or massive batches of Cloud Security Findings directly to the official Secure Controls Framework (SCF).")
    
    tab1, tab2 = st.tabs(["📝 Text Or Policy Snippet", "📄 Upload Documents (PDF/JSON/TXT)"])
    
    input_text = ""
    is_batch = False
    batch_findings = []
    
    with tab1:
        st.markdown("### Paste Policy or Requirement")
        text_input = st.text_area("Policy Content", height=150, placeholder="e.g. All production databases containing PII must be encrypted at rest utilizing AES-256 or better.")
        
        st.markdown("**Or quickly test with Lab Data:**")
        lab_files = load_lab_files()
        if lab_files:
            colA, colB = st.columns([1, 4])
            selected_lab_file = colA.selectbox("Select Sample", ["None"] + lab_files, key="cw_lab")
            if selected_lab_file != "None":
                with open(os.path.join(LAB_DATA_DIR, selected_lab_file), 'r', encoding='utf-8') as f:
                    if selected_lab_file.endswith('.json'):
                        data = json.load(f)
                        if isinstance(data, dict) and "Findings" in data and isinstance(data["Findings"], list):
                            is_batch = True
                            batch_findings = data["Findings"]
                            st.info(f"Loaded Lab Batch: {len(batch_findings)} findings ready to map.")
                        else:
                            input_text = json.dumps(data, indent=2)
                            st.info(f"Loaded Lab File: {selected_lab_file}")
                    else:
                        input_text = f.read()
                        st.info(f"Loaded Lab File: {selected_lab_file}")
                        
                if not is_batch:
                    with st.expander("View Lab File Contents"):
                        st.code(input_text)
                        
        if text_input and not is_batch:
            input_text = text_input

    with tab2:
        st.markdown("### Upload Raw Documents")
        uploaded_file = st.file_uploader("Choose a PDF, JSON, or TXT file", type=['pdf', 'json', 'txt'], key="cw_up")
        
        if uploaded_file is not None:
            try:
                if uploaded_file.name.endswith('.pdf'):
                    with st.spinner("Analyzing and parsing PDF pages..."):
                        with pdfplumber.open(uploaded_file) as pdf:
                            pages = [page.extract_text() for page in pdf.pages if page.extract_text()]
                            input_text = "\n".join(pages)
                    st.success(f"Successfully extracted {len(pages)} pages of text from the PDF.")
                elif uploaded_file.name.endswith('.json'):
                    data = json.load(uploaded_file)
                    if isinstance(data, dict) and "Findings" in data and isinstance(data["Findings"], list):
                        is_batch = True
                        batch_findings = data["Findings"]
                        st.success(f"Batch Mode Activated: Successfully loaded {len(batch_findings)} separate Cloud Findings.")
                    else:
                        input_text = json.dumps(data, indent=2)
                        st.success("Successfully loaded single JSON finding.")
                else:
                    input_text = uploaded_file.getvalue().decode("utf-8")
                    st.success("Successfully loaded text finding.")
            except Exception as e:
                st.error(f"Error reading file: {e}")

    st.markdown("---")
    
    texts_to_process = []
    if is_batch:
        texts_to_process = [json.dumps(f) for f in batch_findings]
    elif input_text:
        texts_to_process = [input_text]
    
    col1, col2, col3 = st.columns([1, 1, 1])
    if col2.button("🚀 Analyze and Map to SCF Framework", type="primary", use_container_width=True, key="cw_btn"):
        if not texts_to_process:
            st.warning("Please provide some text, select a lab file, or upload a document to proceed.")
        elif not os.environ.get("GROQ_API_KEY"):
            st.error("No GROQ_API_KEY found in .env.")
        elif not os.path.exists(PARSED_JSON_FILE):
            st.error("SCF Database not found.")
        else:
            with open(PARSED_JSON_FILE, 'r', encoding='utf-8') as f:
                full_scf_db = json.load(f)
            scf_dict = {c["control_id"]: c for c in full_scf_db}
                
            results_data = [] 
            aggregated_controls = {}
            
            with st.spinner(f"AI Engine is actively scanning and cross-referencing {len(texts_to_process)} inputs against the SCF..."):
                progress_bar = st.progress(0)
                for idx, text_block in enumerate(texts_to_process):
                    try:
                        mapping_result = map_text_to_scf(text_block, top_k=3, persona_prompt=persona_prompt)
                        if is_batch:
                            st.write(f"Analyzed finding #{idx+1}...")
                            
                        if mapping_result and mapping_result.mappings:
                            if not is_batch:
                                st.success("Mapping Complete!")
                                st.markdown("### Engine Recommendations")
                                
                            for m_idx, mapping in enumerate(mapping_result.mappings):
                                confidence = mapping.confidence
                                
                                if is_batch:
                                    cid = mapping.control_id
                                    if cid not in aggregated_controls:
                                        weight = scf_dict.get(cid, {}).get("weight", 1)
                                        aggregated_controls[cid] = {
                                            "SCF Control ID": cid,
                                            "SCF Domain": mapping.domain,
                                            "Control Description": mapping.description,
                                            "Weight": weight,
                                            "Hit Count": 0,
                                            "Total Confidence": 0,
                                            "Sample Justification": mapping.justification,
                                            "Regulations": mapping.regulations
                                        }
                                    aggregated_controls[cid]["Hit Count"] += 1
                                    aggregated_controls[cid]["Total Confidence"] += confidence
                                else:
                                    results_data.append({
                                        "Finding Index": idx + 1,
                                        "Input Outline": text_block[:60] + "...",
                                        "SCF Control ID": mapping.control_id,
                                        "SCF Domain": mapping.domain,
                                        "Control Description": mapping.description,
                                        "Confidence (%)": confidence,
                                        "AI Justification": mapping.justification
                                    })
                                    
                                    with st.expander(f"Top Result #{m_idx+1} | {mapping.control_id} - Domain: {mapping.domain} | Confidence: {confidence}%", expanded=True):
                                        st.markdown(f"**Control Description:** {mapping.description}")
                                        st.markdown(f"**AI Justification:** {mapping.justification}")
                                        st.progress(confidence / 100.0)
                                        if mapping.regulations:
                                            st.markdown("#### Corresponding Regulatory Mappings")
                                            priority = ['gdpr', 'iso', 'nist', 'soc', 'pci', 'ccpa', 'hipaa']
                                            display_regs = {r:v for r,v in mapping.regulations.items() if any(p in r.lower() for p in priority)}
                                            other_regs = len(mapping.regulations) - len(display_regs)
                                            if display_regs:
                                                st.write("🔥 **Priority Framework Mappings:**")
                                                for r, v in display_regs.items():
                                                    st.markdown(f"- **{r}:** {v}")
                                            if other_regs > 0:
                                                st.caption(f"*(+{other_regs} minor framework mappings generated in CSV export)*")
                    except Exception as e:
                        st.error(f"Error mapping input #{idx+1}: {e}")
                    progress_bar.progress((idx + 1) / len(texts_to_process))
                    
            if is_batch:
                for cid, data in aggregated_controls.items():
                    data["Average Confidence (%)"] = round(data["Total Confidence"] / data["Hit Count"])
                    # Compute a Priority Score: Weight * Hit Count
                    data["Priority Score"] = data["Weight"] * data["Hit Count"]
                    
                sorted_controls = sorted(aggregated_controls.values(), key=lambda x: x["Priority Score"], reverse=True)
                top_controls = sorted_controls # Return all priority deductive controls
                
                st.success("Batch Mapping Complete!")
                st.markdown(f"### 🎯 All {len(top_controls)} Priority Controls")
                st.info(f"Analyzed {len(texts_to_process)} separate findings and consolidated them into the highest priority controls based on SCF Weighting and frequency. (Duplicates Removed)")
                
                for m_idx, data in enumerate(top_controls):
                    results_data.append({
                        "SCF Control ID": data["SCF Control ID"],
                        "SCF Domain": data["SCF Domain"],
                        "Control Description": data["Control Description"],
                        "Priority Score": data["Priority Score"],
                        "Hit Count": data["Hit Count"],
                        "Average Confidence (%)": data["Average Confidence (%)"],
                        "Weight": data["Weight"],
                        "Sample AI Justification": data["Sample Justification"]
                    })
                    
                    with st.expander(f"Priority #{m_idx+1} | {data['SCF Control ID']} (Score: {data['Priority Score']}) | Hits: {data['Hit Count']}", expanded=(m_idx < 3)):
                        st.markdown(f"**Control Description:** {data['Control Description']}")
                        st.markdown(f"**Sample AI Justification:** {data['Sample Justification']}")
                        st.progress(data["Average Confidence (%)"] / 100.0)
                        if data["Regulations"]:
                            st.markdown("#### Corresponding Regulatory Mappings")
                            priority = ['gdpr', 'iso', 'nist', 'soc', 'pci', 'ccpa', 'hipaa']
                            display_regs = {r:v for r,v in data["Regulations"].items() if any(p in r.lower() for p in priority)}
                            other_regs = len(data["Regulations"]) - len(display_regs)
                            if display_regs:
                                st.write("🔥 **Priority Framework Mappings:**")
                                for r, v in display_regs.items():
                                    st.markdown(f"- **{r}:** {v}")
                            if other_regs > 0:
                                st.caption(f"*(+{other_regs} minor framework mappings generated in CSV export)*")

            if results_data:
                st.markdown("---")
                df = pd.DataFrame(results_data)
                csv = df.to_csv(index=False).encode('utf-8')
                col_csv1, col_csv2, col_csv3 = st.columns([1,2,1])
                with col_csv2:
                    st.success(f"✅ Successfully mapped {len(results_data)} total controls.")
                    st.download_button("📥 Download Mappings as CSV", data=csv, file_name='scf_ai_crosswalk_results.csv', mime='text/csv', type='primary', use_container_width=True)

# ==========================================
# TOOL 2: Audit Scope Analyzer
# ==========================================
elif app_mode == "🎯 Audit Scope Analyzer":
    st.title("🎯 Audit Scope Analyzer")
    st.markdown("Predict which SCF controls must be tested based on a narrative audit scope document.")
    
    scope_text = ""
    colA, colB = st.columns([1, 1])
    with colA:
        st.markdown("### Upload Scope Document")
        uploaded_scope = st.file_uploader("Upload PDF or TXT Scope", type=['pdf', 'txt'], key="scope_up")
        if uploaded_scope:
            if uploaded_scope.name.endswith('.pdf'):
                with pdfplumber.open(uploaded_scope) as pdf:
                    scope_text = "\n".join([page.extract_text() for page in pdf.pages if page.extract_text()])
            else:
                scope_text = uploaded_scope.getvalue().decode("utf-8")
                
        # Lab integration
        lab_txt = load_lab_files(extension='.txt')
        selected_lab = st.selectbox("Or select Lab Data", ["None"] + lab_txt, key="scope_lab")
        if selected_lab != "None" and not scope_text:
            with open(os.path.join(LAB_DATA_DIR, selected_lab), 'r', encoding='utf-8') as f:
                scope_text = f.read()

    with colB:
        st.markdown("### Scope Document Preview")
        if scope_text:
            st.text_area("Scope Content (Editable)", value=scope_text, height=180, key="scope_text_area")
            # Pull text from the area if user edited
            scope_text = st.session_state.scope_text_area
        else:
            st.info("Upload a document or select lab data to preview.")

    st.markdown("---")
    colbtn1, colbtn2, colbtn3 = st.columns([1, 1, 1])
    if colbtn2.button("🎯 Analyze Scope and Recommend Controls", type="primary", use_container_width=True, key="scope_btn"):
        if not scope_text:
            st.warning("Please provide scope text to analyze.")
        elif not os.path.exists(PARSED_JSON_FILE):
            st.error("JSON Framework Database missing. Please fetch the data using the sidebar.")
        else:
            with open(PARSED_JSON_FILE, 'r', encoding='utf-8') as f:
                full_scf_db = json.load(f)
            scf_dict = {c["control_id"]: c for c in full_scf_db}
            
            with st.spinner("AI is determining audit boundaries and expected controls..."):
                try:
                    recommendation = analyze_audit_scope(scope_text)
                    if recommendation:
                        st.success("Scope Analysis Complete!")
                        st.markdown("### 🧠 AI Strategic Reasoning")
                        st.info(recommendation.reasoning)
                        
                        colRes1, colRes2 = st.columns(2)
                        with colRes1:
                            st.markdown("### 🛡️ Relevant SCF Domains")
                            for dom in recommendation.recommended_domains:
                                st.markdown(f"- {dom}")
                        with colRes2:
                            st.markdown("### 📋 Recommended Controls to Test")
                            
                            # Helper function to do a fuzzy fallback lookup
                            def get_control_data(target_cid):
                                if target_cid in scf_dict:
                                    return target_cid, scf_dict[target_cid]
                                # Fallback: LLM sometimes emits "AC-1" instead of "IAC-01" or "AC-01"
                                target_clean = target_cid.upper().replace("-", "").replace(" ", "")
                                for db_id, data in scf_dict.items():
                                    db_clean = db_id.upper().replace("-", "").replace(" ", "")
                                    if target_clean in db_clean or db_clean in target_clean:
                                        return db_id, data
                                return target_cid, {}

                            for cid in recommendation.recommended_control_ids:
                                actual_id, control_data = get_control_data(cid)
                                desc = control_data.get("description", "Description not found. (The AI recommended a control ID that does not map perfectly to the 2025 SCF Database).")
                                erl = control_data.get("erl", "")
                                question = control_data.get("question", "")
                                
                                display_id = actual_id if actual_id != cid else cid
                                with st.expander(f"**{display_id}** (Predicted: {cid})", expanded=False):
                                    st.markdown(f"**Control Description:** {desc}")
                                    if erl:
                                        st.markdown(f"**Evidence Request List (ERL):** {erl}")
                                    if question:
                                        st.markdown(f"**Walkthrough Question:** {question}")
                except Exception as e:
                    st.error(f"Error during scope analysis: {e}")

# ==========================================
# TOOL 3: Compliance Gap Analyzer
# ==========================================
elif app_mode == "📉 Compliance Gap Analyzer":
    st.title("📉 Compliance Gap Analyzer")
    st.markdown("Evaluate a company's existing control list against a specific target regulation framework (e.g., GDPR, SOC 2, HIPAA).")
    
    if scarcely_loaded := not os.path.exists(PARSED_JSON_FILE):
        st.error("JSON Framework Database missing. Please fetch the data using the sidebar.")
    else:
        # Load the master JSON database into memory so we can extract available regulations
        with open(PARSED_JSON_FILE, 'r', encoding='utf-8') as f:
            full_db = json.load(f)
            
        # Parse all available regulations aggressively
        all_regs = set()
        for control in full_db:
            if "regulations" in control and isinstance(control["regulations"], dict):
                for reg in control["regulations"].keys():
                    # Just split the raw name to make a clean dropdown, e.g. "GDPR 2016" -> "GDPR"
                    base_reg = reg.split()[0].upper()
                    all_regs.add(base_reg)
                    # Also just add the full raw string for safety
                    all_regs.add(reg)
                    
        # Provide a hardcoded clean list of common priority frameworks, plus any dynamically found ones
        clean_regs = ["SOC 2", "ISO 27001", "NIST CSF", "NIST 800-53", "GDPR", "HIPAA", "PCI DSS", "CCPA"]
        # Allow user to pick from clean regs, or type their own based on what was parsed
        
        target_framework = st.selectbox("🎯 Select Target Framework / Regulation", clean_regs)
        
        st.markdown("---")
        colA, colB = st.columns([1, 1])
        with colA:
            st.markdown("### Upload Existing Controls")
            st.markdown("Upload a CSV export of your current implemented controls.")
            uploaded_csv = st.file_uploader("Upload CSV", type=['csv'], key="gap_up")
            
            # Lab Integration
            lab_csv = load_lab_files(extension='.csv')
            selected_lab_csv = st.selectbox("Or select Lab Data", ["None"] + lab_csv, key="gap_lab")
            
            df_existing = None
            if uploaded_csv:
                df_existing = pd.read_csv(uploaded_csv)
            elif selected_lab_csv != "None":
                df_existing = pd.read_csv(os.path.join(LAB_DATA_DIR, selected_lab_csv))
                
        with colB:
            if df_existing is not None:
                st.markdown(f"### Current Controls Snapshot ({len(df_existing)} total)")
                st.dataframe(df_existing, height=180, use_container_width=True)
            else:
                st.info("Awaiting input data...")

        st.markdown("---")
        colbtn1, colbtn2, colbtn3 = st.columns([1, 1, 1])
        if colbtn2.button("📉 Run Gap Analysis", type="primary", use_container_width=True, key="gap_btn"):
            if df_existing is None:
                st.warning("Please upload your existing controls list.")
            else:
                with st.spinner(f"Filtering the entire SCF database for {target_framework} requirements and identifying gaps..."):
                    # Step 1: Find all SCF controls required by the Target Framework
                    required_scf = []
                    for c in full_db:
                        regs_dict = c.get("regulations", {})
                        if any(target_framework.lower().replace(" ", "") in k.lower().replace(" ", "") for k in regs_dict.keys()):
                            required_scf.append(c)
                            
                    st.success(f"Analysis Complete! Found **{len(required_scf)}** baseline SCF Controls that map specifically to **{target_framework}**.")
                    
                    if len(required_scf) > 0:
                        # Convert required scf to dataframe for easy viewing
                        df_req = pd.DataFrame([{
                            "Required Control ID": rc.get("control_id", ""), 
                            "Domain": rc.get("domain", ""),
                            "Description": rc.get("description", ""),
                            "Evidence Request List (ERL)": rc.get("erl", ""),
                            "Control Question": rc.get("question", "")
                        } for rc in required_scf])
                        
                        st.markdown("### ⚠️ Gap Profile Breakdown")
                        st.markdown(f"Your uploaded list contains `{len(df_existing)}` controls. Based on the SCF, `{target_framework}` mandates at least `{len(required_scf)}` unique control touchpoints.")
                        
                        # Note: Deep AI comparison of "Existing CSV vs Required framework" is extremely token heavy.
                        # For Phase 3, we just provide the required checklist as requested by user ("app tells them what they *need* for the regulation, producing a checklist").
                        
                        st.markdown(f"#### Complete Checklist of Required SCF Controls for {target_framework}")
                        st.dataframe(df_req, use_container_width=True)
                        
                        csv_req = df_req.to_csv(index=False).encode('utf-8')
                        st.download_button("📥 Download Missing Checklist as CSV", data=csv_req, file_name=f'missing_controls_for_{target_framework.replace(" ", "_")}.csv', mime='text/csv')
                    else:
                        st.error(f"Could not find any specific mappings for {target_framework} in the database. Try selecting another framework or re-fetching the SCF data.")
