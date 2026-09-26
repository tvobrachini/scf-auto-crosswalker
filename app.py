import os
import sys
from dotenv import load_dotenv

# Load .env variables (picks up GROQ_API_KEY and GROQ_MODEL)
load_dotenv()

# Ensure the src directory is available for imports
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

import streamlit as st  # noqa: E402
import json  # noqa: E402
import pandas as pd  # noqa: E402
import pdfplumber  # noqa: E402
from findings import finding_to_text, is_securityhub_export  # noqa: E402
from gap_analysis import (  # noqa: E402
    STATUS_GAP,
    analyze_gaps,
    detect_id_column,
    framework_columns,
)
from mapper import analyze_audit_scope, load_scf_database, map_text_to_scf  # noqa: E402
from ui.components.styles import inject_premium_css  # noqa: E402
from ui.components.sidebar import render_sidebar  # noqa: E402

st.set_page_config(page_title="GRC Assistant", page_icon="🛡️", layout="wide")

# --- Custom CSS ---
inject_premium_css()

# --- Sidebar Navigation & Setup ---
app_mode, persona_prompt = render_sidebar()

LAB_DATA_DIR = os.path.join(os.path.dirname(__file__), "lab_data")

PRIORITY_FRAMEWORKS = ["gdpr", "iso", "nist", "soc", "pci", "ccpa", "hipaa"]

GROQ_NOTICE = (
    "Text you submit is sent to Groq's API for the LLM step. "
    "Do not submit confidential audit data unless your organization allows it."
)


def load_lab_files(extension: str | tuple[str, ...] | None = None):
    if not os.path.exists(LAB_DATA_DIR):
        return []
    files = sorted(
        f
        for f in os.listdir(LAB_DATA_DIR)
        if os.path.isfile(os.path.join(LAB_DATA_DIR, f))
    )
    if extension:
        files = [f for f in files if f.endswith(extension)]
    return files


def resolve_lab_file(name: str) -> str | None:
    """Absolute path of a file directly inside lab_data/, or None if it escapes it."""
    resolved = os.path.realpath(os.path.join(LAB_DATA_DIR, name))
    if not resolved.startswith(os.path.realpath(LAB_DATA_DIR) + os.sep):
        return None
    return resolved


def extract_pdf_text(file) -> tuple[str, int]:
    with pdfplumber.open(file) as pdf:
        pages = [text for page in pdf.pages if (text := page.extract_text())]
    return "\n".join(pages), len(pages)


def render_regulations(regulations: dict) -> None:
    if not regulations:
        return
    st.markdown("#### Framework references (from SCF's crosswalk)")
    display_regs = {
        r: v
        for r, v in regulations.items()
        if any(p in r.lower() for p in PRIORITY_FRAMEWORKS)
    }
    for r, v in display_regs.items():
        st.markdown(f"- **{r}:** {v}")
    other_regs = len(regulations) - len(display_regs)
    if other_regs > 0:
        st.caption(f"*(+{other_regs} more framework references in the SCF data)*")


def render_rejected(rejected: list[str]) -> None:
    if rejected:
        st.warning(
            "The model also returned IDs that are not SCF controls, so they were "
            f"dropped: {', '.join(f'`{r}`' for r in rejected)}"
        )


# ==========================================
# TOOL 1: SCF Auto-Crosswalker
# ==========================================
if app_mode == "🔍 SCF Auto-Crosswalker":
    st.title("🔍 SCF Auto-Crosswalker")
    st.markdown(
        "Suggest the Secure Controls Framework (SCF) controls that best match an IT policy, "
        "a document, or a batch of AWS Security Hub findings. Suggestions are for review by a person."
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
        lab_files = load_lab_files(extension=(".txt", ".json"))
        if lab_files:
            colA, colB = st.columns([1, 4])
            selected_lab_file = colA.selectbox(
                "Select Sample", ["None"] + lab_files, key="cw_lab"
            )
            if selected_lab_file != "None":
                resolved = resolve_lab_file(selected_lab_file)
                if resolved is None:
                    st.error("Invalid file selection.")
                else:
                    with open(resolved, "r", encoding="utf-8") as f:
                        if selected_lab_file.endswith(".json"):
                            data = json.load(f)
                            if is_securityhub_export(data):
                                is_batch = True
                                batch_findings = data["Findings"]
                                st.info(
                                    f"Loaded Lab Batch: {len(batch_findings)} findings ready to map."
                                )
                            else:
                                input_text = finding_to_text(data)
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
                    with st.spinner("Extracting text from the PDF..."):
                        input_text, page_count = extract_pdf_text(uploaded_file)
                    st.success(f"Extracted text from {page_count} PDF pages.")
                elif uploaded_file.name.endswith(".json"):
                    data = json.load(uploaded_file)
                    if is_securityhub_export(data):
                        is_batch = True
                        batch_findings = data["Findings"]
                        st.success(
                            f"Batch mode: loaded {len(batch_findings)} Security Hub findings."
                        )
                    else:
                        input_text = finding_to_text(data)
                        st.success("Loaded a single JSON finding.")
                else:
                    try:
                        input_text = uploaded_file.getvalue().decode("utf-8")
                    except UnicodeDecodeError:
                        st.error(
                            "File encoding not supported. Please upload a UTF-8 encoded file."
                        )
                        input_text = ""
                    else:
                        st.success("Loaded the text file.")
            except Exception as e:
                st.error(f"Error reading file: {e}")

    st.markdown("---")

    texts_to_process = []
    if is_batch:
        texts_to_process = [finding_to_text(f) for f in batch_findings]
    elif input_text:
        texts_to_process = [input_text]

    st.caption(GROQ_NOTICE)
    col1, col2, col3 = st.columns([1, 1, 1])
    if col2.button(
        "🚀 Suggest SCF Controls",
        type="primary",
        width="stretch",
        key="cw_btn",
    ):
        scf_db = load_scf_database()
        if not texts_to_process:
            st.warning(
                "Please provide some text, select a lab file, or upload a document to proceed."
            )
        elif not os.environ.get("GROQ_API_KEY"):
            st.error("No GROQ_API_KEY found in .env.")
        elif not scf_db:
            st.error("SCF database not found or empty. Use the sidebar to download it.")
        else:
            scf_dict = {c["control_id"]: c for c in scf_db}

            results_data = []
            aggregated_controls = {}

            with st.spinner(
                f"Retrieving candidate controls and asking the model about {len(texts_to_process)} input(s)..."
            ):
                progress_bar = st.progress(0)
                for idx, text_block in enumerate(texts_to_process):
                    try:
                        mapping_result = map_text_to_scf(
                            text_block, top_k=3, persona_prompt=persona_prompt
                        )
                        if is_batch:
                            st.write(f"Analyzed finding #{idx + 1}...")

                        if mapping_result is None:
                            st.error(f"No result for input #{idx + 1}.")
                        elif not mapping_result.mappings:
                            st.warning(
                                f"Input #{idx + 1}: the model returned no valid SCF controls."
                            )
                        if mapping_result and not is_batch:
                            render_rejected(mapping_result.rejected_control_ids)

                        if mapping_result and mapping_result.mappings:
                            if not is_batch:
                                st.success("Suggestions ready. Review each one.")
                                st.markdown("### Suggested Controls")

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
                                            "Model Confidence (%)": confidence,
                                            "Model Justification": mapping.justification,
                                        }
                                    )

                                    with st.expander(
                                        f"Suggestion #{m_idx + 1} | {mapping.control_id} - Domain: {mapping.domain} | Model confidence: {confidence}%",
                                        expanded=True,
                                    ):
                                        st.markdown(
                                            f"**Control Description (SCF):** {mapping.description}"
                                        )
                                        st.markdown(
                                            f"**Model Justification:** {mapping.justification}"
                                        )
                                        st.progress(confidence / 100.0)
                                        render_regulations(mapping.regulations)
                    except Exception as e:
                        st.error(f"Error mapping input #{idx + 1}: {e}")
                    progress_bar.progress((idx + 1) / len(texts_to_process))

            if is_batch and aggregated_controls:
                for cid, data in aggregated_controls.items():
                    data["Average Confidence (%)"] = round(
                        data["Total Confidence"] / data["Hit Count"]
                    )
                    # Priority Score: SCF relative weight x number of findings
                    data["Priority Score"] = data["Weight"] * data["Hit Count"]

                sorted_controls = sorted(
                    aggregated_controls.values(),
                    key=lambda x: x["Priority Score"],
                    reverse=True,
                )

                st.success("Batch mapping complete.")
                st.markdown(f"### 🎯 {len(sorted_controls)} Suggested Controls")
                st.info(
                    f"Suggestions for {len(texts_to_process)} findings, merged by control and "
                    "ranked by Priority Score (SCF relative weight x number of findings that mapped to it)."
                )

                for m_idx, data in enumerate(sorted_controls):
                    results_data.append(
                        {
                            "SCF Control ID": data["SCF Control ID"],
                            "SCF Domain": data["SCF Domain"],
                            "Control Description": data["Control Description"],
                            "Priority Score": data["Priority Score"],
                            "Hit Count": data["Hit Count"],
                            "Average Model Confidence (%)": data[
                                "Average Confidence (%)"
                            ],
                            "Weight": data["Weight"],
                            "Sample Model Justification": data["Sample Justification"],
                        }
                    )

                    with st.expander(
                        f"#{m_idx + 1} | {data['SCF Control ID']} (Score: {data['Priority Score']}) | Hits: {data['Hit Count']}",
                        expanded=(m_idx < 3),
                    ):
                        st.markdown(
                            f"**Control Description (SCF):** {data['Control Description']}"
                        )
                        st.markdown(
                            f"**Sample Model Justification:** {data['Sample Justification']}"
                        )
                        st.progress(data["Average Confidence (%)"] / 100.0)
                        render_regulations(data["Regulations"])

            if results_data:
                st.markdown("---")
                df = pd.DataFrame(results_data)
                csv = df.to_csv(index=False).encode("utf-8")
                col_csv1, col_csv2, col_csv3 = st.columns([1, 2, 1])
                with col_csv2:
                    st.success(f"{len(results_data)} suggestions ready to export.")
                    st.download_button(
                        "📥 Download Suggestions as CSV",
                        data=csv,
                        file_name="scf_ai_crosswalk_results.csv",
                        mime="text/csv",
                        type="primary",
                        width="stretch",
                    )

# ==========================================
# TOOL 2: Compliance Gap Analyzer
# ==========================================
elif app_mode == "📉 Compliance Gap Analyzer":
    st.title("📉 Compliance Gap Analyzer")
    st.markdown(
        "List the SCF controls that SCF's own crosswalk maps to a framework, and check which "
        "of them appear, by SCF control ID, in your existing control list. No LLM is used."
    )

    scf_db = load_scf_database()
    if not scf_db:
        st.error("SCF database missing. Please download it using the sidebar.")
    else:
        common_frameworks = [
            "SOC 2",
            "ISO 27001",
            "NIST CSF",
            "NIST 800-53",
            "GDPR",
            "HIPAA",
            "PCI DSS",
            "CCPA",
        ]
        colF1, colF2 = st.columns([1, 2])
        target_framework = colF1.selectbox(
            "🎯 Target Framework / Regulation", common_frameworks
        )
        matching_columns = framework_columns(scf_db, target_framework)
        selected_columns = []
        if matching_columns:
            selected_column = colF2.selectbox(
                "SCF crosswalk column",
                matching_columns,
                help="SCF can have more than one column for a framework (for example, two editions). Pick the one you are assessing against.",
            )
            selected_columns = [selected_column]
        else:
            colF2.warning(
                f"The downloaded SCF data has no crosswalk column for {target_framework}."
            )

        st.markdown("---")
        colA, colB = st.columns([1, 1])
        with colA:
            st.markdown("### Upload Existing Controls")
            st.markdown(
                "Upload a CSV of your current controls. The ID column must use **SCF control IDs** (e.g. `CRY-01`)."
            )
            uploaded_csv = st.file_uploader("Upload CSV", type=["csv"], key="gap_up")

            lab_csv = load_lab_files(extension=".csv")
            selected_lab_csv = st.selectbox(
                "Or select Lab Data", ["None"] + lab_csv, key="gap_lab"
            )

            df_existing = None
            if uploaded_csv:
                df_existing = pd.read_csv(uploaded_csv)
            elif selected_lab_csv != "None":
                resolved_csv = resolve_lab_file(selected_lab_csv)
                if resolved_csv is None:
                    st.error("Invalid file selection.")
                else:
                    df_existing = pd.read_csv(resolved_csv)

        id_column = None
        with colB:
            if df_existing is not None and not df_existing.empty:
                st.markdown(f"### Current Controls Snapshot ({len(df_existing)} total)")
                st.dataframe(df_existing, height=180, width="stretch")
                columns = list(df_existing.columns)
                id_column = st.selectbox(
                    "Column holding SCF control IDs",
                    columns,
                    index=columns.index(detect_id_column(df_existing)),
                )
            else:
                st.info("Awaiting input data...")

        st.markdown("---")
        colbtn1, colbtn2, colbtn3 = st.columns([1, 1, 1])
        if colbtn2.button(
            "📉 Run Gap Analysis",
            type="primary",
            width="stretch",
            key="gap_btn",
        ):
            if df_existing is None or df_existing.empty or id_column is None:
                st.warning("Please upload your existing controls list.")
            elif not selected_columns:
                st.warning("Pick a framework that the SCF data has a column for.")
            else:
                report = analyze_gaps(scf_db, selected_columns, df_existing, id_column)
                framework_label = selected_columns[0]

                if report.unknown_ids:
                    st.warning(
                        f"{len(report.unknown_ids)} ID(s) in your list are not SCF control IDs "
                        f"and cannot match anything: {', '.join(report.unknown_ids[:15])}"
                        + (" ..." if len(report.unknown_ids) > 15 else "")
                    )

                if not report.rows:
                    st.error(
                        f"No SCF controls map to {framework_label} in the downloaded data."
                    )
                else:
                    df_req = pd.DataFrame(report.rows)
                    df_gaps = df_req[df_req["Status"] == STATUS_GAP]

                    st.markdown(f"### Gap profile: {framework_label}")
                    col_m1, col_m2, col_m3 = st.columns(3)
                    col_m1.metric("SCF controls mapped", len(report.rows))
                    col_m2.metric(
                        "✅ Listed in your controls",
                        report.covered,
                        delta=f"{round(report.covered / len(report.rows) * 100)}%",
                    )
                    col_m3.metric("❌ Not listed", report.gaps)
                    st.caption(
                        "“Listed” means the SCF control ID appears in your list. It says nothing about "
                        "whether the control is designed or operating effectively."
                    )

                    file_stub = target_framework.replace(" ", "_")
                    tab_gaps, tab_all = st.tabs(
                        [
                            f"❌ Not listed ({len(df_gaps)})",
                            f"Full Checklist ({len(df_req)})",
                        ]
                    )
                    with tab_gaps:
                        if df_gaps.empty:
                            st.success(
                                "Every SCF control mapped to this framework is listed in your controls."
                            )
                        else:
                            st.dataframe(df_gaps, width="stretch")
                            st.download_button(
                                "📥 Download Gaps as CSV",
                                data=df_gaps.to_csv(index=False).encode("utf-8"),
                                file_name=f"gaps_{file_stub}.csv",
                                mime="text/csv",
                                type="primary",
                            )
                    with tab_all:
                        st.dataframe(df_req, width="stretch")
                        st.download_button(
                            "📥 Download Full Checklist as CSV",
                            data=df_req.to_csv(index=False).encode("utf-8"),
                            file_name=f"checklist_{file_stub}.csv",
                            mime="text/csv",
                        )

# ==========================================
# TOOL 3: Audit Scope Analyzer
# ==========================================
elif app_mode == "🎯 Audit Scope Analyzer":
    st.title("🎯 Audit Scope Analyzer")
    st.markdown(
        "Paste or upload an audit scope document and the model will suggest SCF domains and "
        "controls to test. Suggested control IDs are checked against the SCF database."
    )

    scf_db = load_scf_database()
    if not scf_db:
        st.error("SCF database not found. Please download it using the sidebar.")
    else:
        tab_text, tab_file = st.tabs(
            ["📝 Paste Scope Document", "📄 Upload Scope (TXT/PDF)"]
        )

        scope_text = ""

        with tab_text:
            text_input = st.text_area(
                "Audit Scope Document",
                height=200,
                placeholder="Paste your audit scope narrative here...",
            )
            st.markdown("**Or quickly test with Lab Data:**")
            lab_txt = load_lab_files(extension=".txt")
            if lab_txt:
                selected_lab_txt = st.selectbox(
                    "Select Sample", ["None"] + lab_txt, key="scope_lab"
                )
                if selected_lab_txt != "None":
                    resolved = resolve_lab_file(selected_lab_txt)
                    if resolved is None:
                        st.error("Invalid file selection.")
                    else:
                        with open(resolved, "r", encoding="utf-8") as f:
                            scope_text = f.read()
                        st.info(f"Loaded: {selected_lab_txt}")
                        with st.expander("View File Contents"):
                            st.code(scope_text)

            if text_input:
                scope_text = text_input

        with tab_file:
            uploaded_scope = st.file_uploader(
                "Upload Scope Document (TXT or PDF)",
                type=["txt", "pdf"],
                key="scope_up",
            )
            if uploaded_scope is not None:
                try:
                    if uploaded_scope.name.endswith(".pdf"):
                        scope_text, _ = extract_pdf_text(uploaded_scope)
                    else:
                        scope_text = uploaded_scope.getvalue().decode("utf-8")
                    st.success(f"Loaded: {uploaded_scope.name}")
                except UnicodeDecodeError:
                    st.error("File encoding not supported. Please upload a UTF-8 file.")
                except Exception as e:
                    st.error(f"Error reading file: {e}")

        st.markdown("---")
        st.caption(GROQ_NOTICE)
        col1, col2, col3 = st.columns([1, 1, 1])
        if col2.button(
            "🎯 Suggest Controls to Test",
            type="primary",
            width="stretch",
            key="scope_btn",
        ):
            if not scope_text:
                st.warning("Please paste or upload an audit scope document.")
            elif not os.environ.get("GROQ_API_KEY"):
                st.error("No GROQ_API_KEY found in .env.")
            else:
                with st.spinner(
                    "Retrieving candidate controls and asking the model..."
                ):
                    try:
                        result = analyze_audit_scope(scope_text)

                        if result:
                            st.success("Suggestions ready. Review each one.")
                            render_rejected(result.rejected_control_ids)

                            scf_dict = {c["control_id"]: c for c in scf_db}
                            col_d, col_c = st.columns([1, 1])

                            with col_d:
                                st.markdown("### Suggested SCF Domains")
                                for domain in result.recommended_domains:
                                    st.markdown(f"- **{domain}**")

                            control_rows = []
                            with col_c:
                                st.markdown("### Suggested Controls to Test")
                                if not result.recommended_control_ids:
                                    st.warning(
                                        "The model returned no valid SCF control IDs."
                                    )
                                for cid in result.recommended_control_ids:
                                    control_info = scf_dict[cid]
                                    description = control_info.get("description", "")
                                    st.markdown(f"- `{cid}` — {description[:80]}...")
                                    control_rows.append(
                                        {
                                            "Control ID": cid,
                                            "Domain": control_info.get("domain", ""),
                                            "Description": description,
                                            "SCF Control Question": control_info.get(
                                                "question", ""
                                            ),
                                            "Evidence Request List": control_info.get(
                                                "erl", ""
                                            ),
                                        }
                                    )

                            st.markdown("---")
                            st.markdown("### Model Reasoning")
                            st.info(result.reasoning)

                            if control_rows:
                                df_scope = pd.DataFrame(control_rows)
                                csv_scope = df_scope.to_csv(index=False).encode("utf-8")
                                col_e1, col_e2, col_e3 = st.columns([1, 2, 1])
                                with col_e2:
                                    st.download_button(
                                        "📥 Download Test Plan as CSV",
                                        data=csv_scope,
                                        file_name="audit_scope_test_plan.csv",
                                        mime="text/csv",
                                        type="primary",
                                        width="stretch",
                                    )
                    except Exception as e:
                        st.error(f"Error analyzing scope: {e}")
