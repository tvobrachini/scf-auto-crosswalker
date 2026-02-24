import os
import sys

# Ensure the src directory is available for imports
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

import streamlit as st
import json
from fetch_scf import RAW_SCF_FILE, PARSED_JSON_FILE, download_scf, parse_scf
from mapper import map_text_to_scf

st.set_page_config(page_title="SCF Auto-Crosswalker", page_icon="🛡️", layout="wide")

st.title("🛡️ Secure Controls Framework (SCF) Auto-Crosswalker")
st.markdown("""
Welcome to the AI-Powered SCF Maper. This tool automatically aligns your raw IT policies, procedures, and Cloud Security Findings to the official Secure Controls Framework (SCF).
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

tab1, tab2 = st.tabs(["📝 Text Or Policy Snippet", "📄 Upload Findings (JSON/TXT)"])

input_text = ""

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
                lab_content = f.read()
            # We want to fill the text area if a sample is selected. 
            # In Streamlit, modifying a widget's value from another widget is tricky via state,
            # so we'll just parse the lab content directly if the user hit's map.
            st.info(f"Loaded `{selected_lab_file}`. You can view its content or just hit Map below.")
            with st.expander("View Lab File Contents"):
                st.code(lab_content)
            
            if not text_input: # Fallback to lab content if textarea is empty
                 input_text = lab_content
        
    if text_input:
        input_text = text_input

with tab2:
    st.markdown("### Upload Raw Findings")
    st.markdown("Upload a raw format finding (like an AWS Security Hub JSON export).")
    uploaded_file = st.file_uploader("Choose a JSON or TXT file", type=['json', 'txt'])
    if uploaded_file is not None:
        try:
            # Try parsing as JSON to format it nicely for the text prompt
            if uploaded_file.name.endswith('.json'):
                data = json.load(uploaded_file)
                input_text = json.dumps(data, indent=2)
                st.success("Successfully loaded JSON finding.")
            else:
                input_text = uploaded_file.getvalue().decode("utf-8")
                st.success("Successfully loaded text finding.")
        except Exception as e:
            st.error(f"Error reading file: {e}")

st.markdown("---")
# Provide a big mapping button
col1, col2, col3 = st.columns([1, 1, 1])
if col2.button("🚀 Analyze and Map to SCF Framework", type="primary", use_container_width=True):
    if not input_text:
        st.warning("Please provide some text, select a lab file, or upload a document to proceed.")
    elif not os.environ.get("GROQ_API_KEY"):
        st.error("No GROQ_API_KEY found in .env. The AI engine requires an API key to run.")
    elif not os.path.exists(PARSED_JSON_FILE):
        st.error("SCF Database not found. Please click 'Force Update SCF Framework Data' in the sidebar.")
    else:
        with st.spinner("AI Engine is actively scanning and cross-referencing controls..."):
            try:
                mapping_result = map_text_to_scf(input_text, top_k=3)
                
                if mapping_result and mapping_result.mappings:
                    st.success("Mapping Complete!")
                    st.markdown("### Engine Recommendations")
                    
                    for idx, mapping in enumerate(mapping_result.mappings):
                        confidence = mapping.confidence
                        # Color code confidence
                        color = "green" if confidence >= 80 else ("orange" if confidence >= 50 else "red")
                        
                        with st.expander(f"Top Result #{idx+1} | {mapping.control_id} - Domain: {mapping.domain} | Confidence: {confidence}%", expanded=True):
                            st.markdown(f"**AI Justification:** {mapping.justification}")
                            st.progress(confidence / 100.0)
                            
                            if mapping.regulations:
                                st.markdown("#### Corresponding Regulatory Mappings")
                                regs = list(mapping.regulations.keys())
                                
                                # Filter to prioritize user requested frameworks first
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
                                    # Use a dictionary to display clean rows
                                    for r, v in display_regs.items():
                                        st.markdown(f"- **{r}:** {v}")
                                        
                                if other_regs:
                                    st.caption(f"*(+{len(other_regs)} minor framework mappings available in export)*")
                                    
                else:
                    st.warning("The engine could not find any confident mappings for the provided input.")
            except Exception as e:
                st.error(f"An error occurred during AI mapping: {e}")
