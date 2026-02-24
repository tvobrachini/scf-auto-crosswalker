import os
import sys

# Ensure the src directory is available for imports
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

import streamlit as st
import json
import pandas as pd
import pdfplumber
from fetch_scf import RAW_SCF_FILE, PARSED_JSON_FILE, download_scf, parse_scf
from mapper import map_text_to_scf

st.set_page_config(page_title="SCF Auto-Crosswalker", page_icon="🛡️", layout="wide")

st.title("🛡️ Secure Controls Framework (SCF) Auto-Crosswalker")
st.markdown("""
Welcome to the AI-Powered SCF Mapper. This tool automatically aligns your raw IT policies, incredibly long PDFs, or massive batches of Cloud Security Findings directly to the official Secure Controls Framework (SCF).
""")

# --- Sidebar: Setup & Data Management ---
with st.sidebar:
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

    st.markdown("---")
    st.header("⚙️ Advanced AI Settings")
    st.markdown("Customize the LLM's internal system prompt to enforce framework-specific lenses during the mapping phase.")
    persona_options = [
        "None (Default General Auditor)",
        "Act as a strict PCI-DSS Qualified Security Assessor (QSA).",
        "Act as a FedRAMP 3PAO Assessor focusing on US Federal standards.",
        "Act as a GDPR Data Privacy Officer (DPO) focusing heavily on PII."
    ]
    selected_persona = st.selectbox("AI Persona Lens", persona_options)
    persona_prompt = None if "None" in selected_persona else selected_persona

    st.markdown("---")
    st.markdown("### About")
    st.info("""
    This open-source dashboard utilizes Llama-3 (via Groq) to autonomously perform GRC mapping.
    
    All control framework data is owned and managed by the [Secure Controls Framework](https://securecontrolsframework.com).
    Licensed under CC Attribution-NoDerivatives 4.0.
    """)

# --- Main Area: Input and Mapping ---

# Define the lab data path
LAB_DATA_DIR = os.path.join(os.path.dirname(__file__), 'lab_data')

def load_lab_files():
    if not os.path.exists(LAB_DATA_DIR):
        return []
    return [f for f in os.listdir(LAB_DATA_DIR) if os.path.isfile(os.path.join(LAB_DATA_DIR, f))]

tab1, tab2 = st.tabs(["📝 Text Or Policy Snippet", "📄 Upload Documents (PDF/JSON/TXT)"])

input_text = ""
is_batch = False
batch_findings = []

with tab1:
    st.markdown("### Paste Policy or Requirement")
    st.markdown("Enter a raw company policy or specific requirement you need mapped.")
    text_input = st.text_area("Policy Content", height=150, placeholder="e.g. All production databases containing PII must be encrypted at rest utilizing AES-256 or better.")
    
    # Pre-load Lab Data options
    st.markdown("**Or quickly test with Lab Data:**")
    lab_files = load_lab_files()
    if lab_files:
        colA, colB = st.columns([1, 4])
        selected_lab_file = colA.selectbox("Select Sample", ["None"] + lab_files)
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
    st.markdown("Upload a massive PDF Information Security Policy document, or a JSON finding export (e.g. AWS Security Hub).")
    uploaded_file = st.file_uploader("Choose a PDF, JSON, or TXT file", type=['pdf', 'json', 'txt'])
    
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
                # Auto-Detect Batch AWS Security Hub Findings
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

# Determine execution path
texts_to_process = []
if is_batch:
    texts_to_process = [json.dumps(f) for f in batch_findings]
elif input_text:
    texts_to_process = [input_text]

# Provide a big mapping button
col1, col2, col3 = st.columns([1, 1, 1])
if col2.button("🚀 Analyze and Map to SCF Framework", type="primary", use_container_width=True):
    if not texts_to_process:
        st.warning("Please provide some text, select a lab file, or upload a document to proceed.")
    elif not os.environ.get("GROQ_API_KEY"):
        st.error("No GROQ_API_KEY found in .env. The AI engine requires an API key to run.")
    elif not os.path.exists(PARSED_JSON_FILE):
        st.error("SCF Database not found. Please click 'Force Update SCF Framework Data' in the sidebar.")
    else:
        results_data = [] # For CSV export
        
        with st.spinner(f"AI Engine is actively scanning and cross-referencing {len(texts_to_process)} inputs against the SCF..."):
            progress_bar = st.progress(0)
            
            for idx, text_block in enumerate(texts_to_process):
                try:
                    # Pass the persona prompt to the core engine
                    mapping_result = map_text_to_scf(text_block, top_k=3, persona_prompt=persona_prompt)
                    
                    if is_batch:
                        st.markdown(f"**Finding #{idx+1} Mapped:**")
                        
                    if mapping_result and mapping_result.mappings:
                        if not is_batch:
                            st.success("Mapping Complete!")
                            st.markdown("### Engine Recommendations")
                            
                        for m_idx, mapping in enumerate(mapping_result.mappings):
                            confidence = mapping.confidence
                            
                            # Append flat data to our dataframe list for the CSV export
                            results_data.append({
                                "Finding Index": idx + 1,
                                "Input Outline": text_block[:60] + "...",
                                "SCF Control ID": mapping.control_id,
                                "SCF Domain": mapping.domain,
                                "Confidence (%)": confidence,
                                "AI Justification": mapping.justification
                            })
                            
                            with st.expander(f"Top Result #{m_idx+1} | {mapping.control_id} - Domain: {mapping.domain} | Confidence: {confidence}%", expanded=(not is_batch)):
                                st.markdown(f"**AI Justification:** {mapping.justification}")
                                st.progress(confidence / 100.0)
                                
                                if mapping.regulations:
                                    st.markdown("#### Corresponding Regulatory Mappings")
                                    regs = list(mapping.regulations.keys())
                                    priority = ['gdpr', 'iso', 'nist', 'soc', 'pci', 'ccpa', 'hipaa']
                                    display_regs = {}
                                    other_regs = {}
                                    
                                    for reg, val in mapping.regulations.items():
                                        if any(p in reg.lower() for p in priority):
                                            display_regs[reg] = val
                                        else:
                                            other_regs[reg] = val
                                            
                                    if display_regs:
                                        st.write("🔥 **Priority Framework Mappings:**")
                                        for r, v in display_regs.items():
                                            st.markdown(f"- **{r}:** {v}")
                                            
                                    if other_regs:
                                        st.caption(f"*(+{len(other_regs)} minor framework mappings generated in CSV export)*")
                    else:
                        st.warning(f"The engine could not find any confident mappings for input #{idx+1}.")
                except Exception as e:
                    st.error(f"An error occurred during AI mapping for input #{idx+1}: {e}")
                    
                # Update progress
                progress_bar.progress((idx + 1) / len(texts_to_process))
                
        # Generate the CSV Download Button if mappings succeeded
        if results_data:
            st.markdown("---")
            df = pd.DataFrame(results_data)
            csv = df.to_csv(index=False).encode('utf-8')
            
            col_csv1, col_csv2, col_csv3 = st.columns([1,2,1])
            with col_csv2:
                st.success(f"✅ Successfully mapped {len(results_data)} total controls.")
                st.download_button(
                    label="📥 Download AI Mappings as CSV Spreadsheet",
                    data=csv,
                    file_name='scf_ai_crosswalk_results.csv',
                    mime='text/csv',
                    type='primary',
                    use_container_width=True
                )
