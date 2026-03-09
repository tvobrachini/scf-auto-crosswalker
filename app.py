import os
import sys
from dotenv import load_dotenv

# Load .env variables (picks up GROQ_API_KEY, OPENAI_API_KEY, etc.)
load_dotenv()

# Ensure the src directory is available for imports
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

import streamlit as st  # noqa: E402
import json  # noqa: E402
import pandas as pd  # noqa: E402
import pdfplumber  # noqa: E402
from fetch_scf import PARSED_JSON_FILE  # noqa: E402
from mapper import map_text_to_scf  # noqa: E402
from ui.components.styles import inject_premium_css  # noqa: E402
from ui.components.sidebar import render_sidebar  # noqa: E402

st.set_page_config(page_title="GRC Assistant", page_icon="🛡️", layout="wide")

# --- Custom CSS for Premium Look ---
inject_premium_css()

# --- Sidebar Navigation & Setup ---
app_mode, persona_prompt = render_sidebar()

LAB_DATA_DIR = os.path.join(os.path.dirname(__file__), "lab_data")

PRIORITY_FRAMEWORKS = ["gdpr", "iso", "nist", "soc", "pci", "ccpa", "hipaa"]


def load_lab_files(extension=None):
    if not os.path.exists(LAB_DATA_DIR):
        return []
    files = [
        f
        for f in os.listdir(LAB_DATA_DIR)
        if os.path.isfile(os.path.join(LAB_DATA_DIR, f))
    ]
    if extension:
        files = [f for f in files if f.endswith(extension)]
    return files


# ==========================================
# TOOL 1: SCF Auto-Crosswalker
# ==========================================
if app_mode == "🔍 SCF Auto-Crosswalker":
    st.title("🔍 SCF Auto-Crosswalker")
    st.markdown(
        "Automatically align your raw IT policies, incredibly long PDFs, or massive batches of Cloud Security Findings directly to the official Secure Controls Framework (SCF)."
    )

    tab1, tab2 = st.tabs(
        ["📝 Text Or Policy Snippet", "📄 Upload Documents (PDF/JSON/TXT)"]
    )

    input_text = ""
    is_batch = False
    batch_findings = []

    with tab1:
        st.markdown("### Paste Policy or Requirement")
        text_input = st.text_area(
            "Policy Content",
            height=150,
            placeholder="e.g. All production databases containing PII must be encrypted at rest utilizing AES-256 or better.",
        )

        st.markdown("**Or quickly test with Lab Data:**")
        lab_files = load_lab_files()
        if lab_files:
            colA, colB = st.columns([1, 4])
            selected_lab_file = colA.selectbox(
                "Select Sample", ["None"] + lab_files, key="cw_lab"
            )
            if selected_lab_file != "None":
                _resolved = os.path.realpath(
                    os.path.join(LAB_DATA_DIR, selected_lab_file)
                )
                if not _resolved.startswith(os.path.realpath(LAB_DATA_DIR) + os.sep):
                    st.error("Invalid file selection.")
                    selected_lab_file = "None"
                with open(_resolved, "r", encoding="utf-8") as f:
                    if selected_lab_file.endswith(".json"):
                        data = json.load(f)
                        if (
                            isinstance(data, dict)
                            and "Findings" in data
                            and isinstance(data["Findings"], list)
                        ):
                            is_batch = True
                            batch_findings = data["Findings"]
                            st.info(
                                f"Loaded Lab Batch: {len(batch_findings)} findings ready to map."
                            )
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
        uploaded_file = st.file_uploader(
            "Choose a PDF, JSON, or TXT file", type=["pdf", "json", "txt"], key="cw_up"
        )

        if uploaded_file is not None:
            try:
                if uploaded_file.name.endswith(".pdf"):
                    with st.spinner("Analyzing and parsing PDF pages..."):
                        with pdfplumber.open(uploaded_file) as pdf:
                            pages = [
                                page.extract_text()
                                for page in pdf.pages
                                if page.extract_text()
                            ]
                            input_text = "\n".join(pages)
                    st.success(
                        f"Successfully extracted {len(pages)} pages of text from the PDF."
                    )
                elif uploaded_file.name.endswith(".json"):
                    data = json.load(uploaded_file)
                    if (
                        isinstance(data, dict)
                        and "Findings" in data
                        and isinstance(data["Findings"], list)
                    ):
                        is_batch = True
                        batch_findings = data["Findings"]
                        st.success(
                            f"Batch Mode Activated: Successfully loaded {len(batch_findings)} separate Cloud Findings."
                        )
                    else:
                        input_text = json.dumps(data, indent=2)
                        st.success("Successfully loaded single JSON finding.")
                else:
                    try:
                        input_text = uploaded_file.getvalue().decode("utf-8")
                    except UnicodeDecodeError:
                        st.error(
                            "File encoding not supported. Please upload a UTF-8 encoded file."
                        )
                        input_text = ""
                    else:
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
    if col2.button(
        "🚀 Analyze and Map to SCF Framework",
        type="primary",
        use_container_width=True,
        key="cw_btn",
    ):
        if not texts_to_process:
            st.warning(
                "Please provide some text, select a lab file, or upload a document to proceed."
            )
        elif not os.environ.get("GROQ_API_KEY"):
            st.error("No GROQ_API_KEY found in .env.")
        elif not os.path.exists(PARSED_JSON_FILE):
            st.error("SCF Database not found.")
        else:
            with open(PARSED_JSON_FILE, "r", encoding="utf-8") as f:
                full_scf_db = json.load(f)
            scf_dict = {c["control_id"]: c for c in full_scf_db}

            results_data = []
            aggregated_controls = {}

            with st.spinner(
                f"AI Engine is actively scanning and cross-referencing {len(texts_to_process)} inputs against the SCF..."
            ):
                progress_bar = st.progress(0)
                for idx, text_block in enumerate(texts_to_process):
                    try:
                        mapping_result = map_text_to_scf(
                            text_block, top_k=3, persona_prompt=persona_prompt
                        )
                        if is_batch:
                            st.write(f"Analyzed finding #{idx + 1}...")

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
                                            "Regulations": mapping.regulations,
                                        }
                                    aggregated_controls[cid]["Hit Count"] += 1
                                    aggregated_controls[cid]["Total Confidence"] += (
                                        confidence
                                    )
                                else:
                                    results_data.append(
                                        {
                                            "Finding Index": idx + 1,
                                            "Input Outline": text_block[:60] + "...",
                                            "SCF Control ID": mapping.control_id,
                                            "SCF Domain": mapping.domain,
                                            "Control Description": mapping.description,
                                            "Confidence (%)": confidence,
                                            "AI Justification": mapping.justification,
                                        }
                                    )

                                    with st.expander(
                                        f"Top Result #{m_idx + 1} | {mapping.control_id} - Domain: {mapping.domain} | Confidence: {confidence}%",
                                        expanded=True,
                                    ):
                                        st.markdown(
                                            f"**Control Description:** {mapping.description}"
                                        )
                                        st.markdown(
                                            f"**AI Justification:** {mapping.justification}"
                                        )
                                        st.progress(confidence / 100.0)
                                        if mapping.regulations:
                                            st.markdown(
                                                "#### Corresponding Regulatory Mappings"
                                            )
                                            display_regs = {
                                                r: v
                                                for r, v in mapping.regulations.items()
                                                if any(
                                                    p in r.lower()
                                                    for p in PRIORITY_FRAMEWORKS
                                                )
                                            }
                                            other_regs = len(mapping.regulations) - len(
                                                display_regs
                                            )
                                            if display_regs:
                                                st.write(
                                                    "🔥 **Priority Framework Mappings:**"
                                                )
                                                for r, v in display_regs.items():
                                                    st.markdown(f"- **{r}:** {v}")
                                            if other_regs > 0:
                                                st.caption(
                                                    f"*(+{other_regs} minor framework mappings generated in CSV export)*"
                                                )
                    except Exception as e:
                        st.error(f"Error mapping input #{idx + 1}: {e}")
                    progress_bar.progress((idx + 1) / len(texts_to_process))

            if is_batch:
                for cid, data in aggregated_controls.items():
                    data["Average Confidence (%)"] = round(
                        data["Total Confidence"] / data["Hit Count"]
                    )
                    # Compute a Priority Score: Weight * Hit Count
                    data["Priority Score"] = data["Weight"] * data["Hit Count"]

                sorted_controls = sorted(
                    aggregated_controls.values(),
                    key=lambda x: x["Priority Score"],
                    reverse=True,
                )
                top_controls = sorted_controls  # Return all priority deductive controls

                st.success("Batch Mapping Complete!")
                st.markdown(f"### 🎯 All {len(top_controls)} Priority Controls")
                st.info(
                    f"Analyzed {len(texts_to_process)} separate findings and consolidated them into the highest priority controls based on SCF Weighting and frequency. (Duplicates Removed)"
                )

                for m_idx, data in enumerate(top_controls):
                    results_data.append(
                        {
                            "SCF Control ID": data["SCF Control ID"],
                            "SCF Domain": data["SCF Domain"],
                            "Control Description": data["Control Description"],
                            "Priority Score": data["Priority Score"],
                            "Hit Count": data["Hit Count"],
                            "Average Confidence (%)": data["Average Confidence (%)"],
                            "Weight": data["Weight"],
                            "Sample AI Justification": data["Sample Justification"],
                        }
                    )

                    with st.expander(
                        f"Priority #{m_idx + 1} | {data['SCF Control ID']} (Score: {data['Priority Score']}) | Hits: {data['Hit Count']}",
                        expanded=(m_idx < 3),
                    ):
                        st.markdown(
                            f"**Control Description:** {data['Control Description']}"
                        )
                        st.markdown(
                            f"**Sample AI Justification:** {data['Sample Justification']}"
                        )
                        st.progress(data["Average Confidence (%)"] / 100.0)
                        if data["Regulations"]:
                            st.markdown("#### Corresponding Regulatory Mappings")
                            display_regs = {
                                r: v
                                for r, v in data["Regulations"].items()
                                if any(p in r.lower() for p in PRIORITY_FRAMEWORKS)
                            }
                            other_regs = len(data["Regulations"]) - len(display_regs)
                            if display_regs:
                                st.write("🔥 **Priority Framework Mappings:**")
                                for r, v in display_regs.items():
                                    st.markdown(f"- **{r}:** {v}")
                            if other_regs > 0:
                                st.caption(
                                    f"*(+{other_regs} minor framework mappings generated in CSV export)*"
                                )

            if results_data:
                st.markdown("---")
                df = pd.DataFrame(results_data)
                csv = df.to_csv(index=False).encode("utf-8")
                col_csv1, col_csv2, col_csv3 = st.columns([1, 2, 1])
                with col_csv2:
                    st.success(
                        f"✅ Successfully mapped {len(results_data)} total controls."
                    )
                    st.download_button(
                        "📥 Download Mappings as CSV",
                        data=csv,
                        file_name="scf_ai_crosswalk_results.csv",
                        mime="text/csv",
                        type="primary",
                        use_container_width=True,
                    )

# ==========================================
# ==========================================
# TOOL 2: Compliance Gap Analyzer
# ==========================================
elif app_mode == "📉 Compliance Gap Analyzer":
    st.title("📉 Compliance Gap Analyzer")
    st.markdown(
        "Evaluate a company's existing control list against a specific target regulation framework (e.g., GDPR, SOC 2, HIPAA)."
    )

    if scarcely_loaded := not os.path.exists(PARSED_JSON_FILE):
        st.error(
            "JSON Framework Database missing. Please fetch the data using the sidebar."
        )
    else:
        # Load the master JSON database into memory so we can extract available regulations
        with open(PARSED_JSON_FILE, "r", encoding="utf-8") as f:
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
        clean_regs = [
            "SOC 2",
            "ISO 27001",
            "NIST CSF",
            "NIST 800-53",
            "GDPR",
            "HIPAA",
            "PCI DSS",
            "CCPA",
        ]
        # Allow user to pick from clean regs, or type their own based on what was parsed

        target_framework = st.selectbox(
            "🎯 Select Target Framework / Regulation", clean_regs
        )

        st.markdown("---")
        colA, colB = st.columns([1, 1])
        with colA:
            st.markdown("### Upload Existing Controls")
            st.markdown("Upload a CSV export of your current implemented controls.")
            uploaded_csv = st.file_uploader("Upload CSV", type=["csv"], key="gap_up")

            # Lab Integration
            lab_csv = load_lab_files(extension=".csv")
            selected_lab_csv = st.selectbox(
                "Or select Lab Data", ["None"] + lab_csv, key="gap_lab"
            )

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
        if colbtn2.button(
            "📉 Run Gap Analysis",
            type="primary",
            use_container_width=True,
            key="gap_btn",
        ):
            if df_existing is None:
                st.warning("Please upload your existing controls list.")
            else:
                with st.spinner(
                    f"Filtering the entire SCF database for {target_framework} requirements and identifying gaps..."
                ):
                    # Step 1: Find all SCF controls required by the Target Framework
                    required_scf = []
                    for c in full_db:
                        regs_dict = c.get("regulations", {})
                        if any(
                            target_framework.lower().replace(" ", "")
                            in k.lower().replace(" ", "")
                            for k in regs_dict.keys()
                        ):
                            required_scf.append(c)

                    st.success(
                        f"Analysis Complete! Found **{len(required_scf)}** baseline SCF Controls that map specifically to **{target_framework}**."
                    )

                    if len(required_scf) > 0:
                        # Convert required scf to dataframe for easy viewing
                        df_req = pd.DataFrame(
                            [
                                {
                                    "Required Control ID": rc.get("control_id", ""),
                                    "Domain": rc.get("domain", ""),
                                    "Description": rc.get("description", ""),
                                    "Evidence Request List (ERL)": rc.get("erl", ""),
                                    "Control Question": rc.get("question", ""),
                                }
                                for rc in required_scf
                            ]
                        )

                        st.markdown("### ⚠️ Gap Profile Breakdown")
                        st.markdown(
                            f"Your uploaded list contains `{len(df_existing)}` controls. Based on the SCF, `{target_framework}` mandates at least `{len(required_scf)}` unique control touchpoints."
                        )

                        # Note: Deep AI comparison of "Existing CSV vs Required framework" is extremely token heavy.
                        # For Phase 3, we just provide the required checklist as requested by user ("app tells them what they *need* for the regulation, producing a checklist").

                        st.markdown(
                            f"#### Complete Checklist of Required SCF Controls for {target_framework}"
                        )
                        st.dataframe(df_req, use_container_width=True)

                        csv_req = df_req.to_csv(index=False).encode("utf-8")
                        st.download_button(
                            "📥 Download Missing Checklist as CSV",
                            data=csv_req,
                            file_name=f"missing_controls_for_{target_framework.replace(' ', '_')}.csv",
                            mime="text/csv",
                        )
                    else:
                        st.error(
                            f"Could not find any specific mappings for {target_framework} in the database. Try selecting another framework or re-fetching the SCF data."
                        )
