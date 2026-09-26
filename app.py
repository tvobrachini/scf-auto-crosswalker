import os
import sys
from dotenv import load_dotenv

# Load .env variables (picks up GROQ_API_KEY and GROQ_MODEL)
load_dotenv()

# Ensure the src directory is available for imports
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

import json  # noqa: E402
import re  # noqa: E402

import pandas as pd  # noqa: E402
import pdfplumber  # noqa: E402
import streamlit as st  # noqa: E402
from crosswalk import (  # noqa: E402
    MAX_BATCH,
    CrosswalkInput,
    aggregate,
    all_rejected,
    detail_rows,
    run_crosswalk,
    unique_model_calls,
)
from exports import oscal_mapping_collection, to_safe_csv  # noqa: E402
from fetch_scf import read_scf_release  # noqa: E402
from findings import (  # noqa: E402
    finding_control_id,
    finding_to_text,
    is_securityhub_export,
)
from gap_analysis import (  # noqa: E402
    STATUS_GAP,
    analyze_gaps,
    default_in_place_statuses,
    detect_id_column,
    detect_status_column,
    framework_columns,
)
from mapper import analyze_audit_scope, load_scf_database, map_text_to_scf  # noqa: E402
from ui.components.sidebar import render_sidebar  # noqa: E402
from ui.components.styles import inject_premium_css  # noqa: E402

st.set_page_config(page_title="GRC Assistant", page_icon="🛡️", layout="wide")

# --- Custom CSS ---
inject_premium_css()

# --- Sidebar Navigation & Setup ---
app_mode = render_sidebar()

LAB_DATA_DIR = os.path.join(os.path.dirname(__file__), "lab_data")

PRIORITY_FRAMEWORKS = ["gdpr", "iso", "nist", "soc", "pci", "ccpa", "hipaa"]

MAX_PDF_PAGES = 50

GROQ_NOTICE = (
    "Text you submit is sent to Groq's API for the LLM step. "
    "Do not submit confidential audit data unless your organization allows it."
)

# Characters with meaning in Streamlit Markdown (links, images, emphasis,
# HTML, colour directives). Model output is escaped before rendering, so a
# prompt-injected document cannot make the page load an external image or
# render a link.
_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~$:])")


def md_escape(text: str) -> str:
    return _MD_SPECIAL.sub(r"\\\1", str(text))


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


def extract_pdf_text(file) -> tuple[str, int, bool]:
    """Text of the first MAX_PDF_PAGES pages, the page count read, and whether it was cut."""
    with pdfplumber.open(file) as pdf:
        pages = pdf.pages[:MAX_PDF_PAGES]
        texts = [text for page in pages if (text := page.extract_text())]
        truncated = len(pdf.pages) > MAX_PDF_PAGES
    return "\n".join(texts), len(pages), truncated


def read_uploaded_csv(file) -> pd.DataFrame | None:
    try:
        return pd.read_csv(file)
    except UnicodeDecodeError:
        st.error("The CSV is not UTF-8 encoded. Save it as UTF-8 and upload it again.")
    except (pd.errors.ParserError, pd.errors.EmptyDataError, ValueError) as e:
        st.error(f"Could not read the CSV: {e}")
    return None


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
        st.markdown(f"- **{md_escape(r)}:** {md_escape(v)}")
    other_regs = len(regulations) - len(display_regs)
    if other_regs > 0:
        st.caption(f"*(+{other_regs} more framework references in the SCF data)*")


def render_rejected(rejected: list[str], what: str = "IDs") -> None:
    if rejected:
        st.warning(
            f"The model also returned {what} that are not among the SCF candidates it "
            f"was given, so they were dropped: {', '.join(md_escape(r) for r in rejected)}"
        )


def findings_to_inputs(findings: list) -> list[CrosswalkInput]:
    inputs = []
    for i, finding in enumerate(findings, start=1):
        title = finding.get("Title", "") if isinstance(finding, dict) else ""
        inputs.append(
            CrosswalkInput(
                label=f"Finding {i}" + (f": {title[:60]}" if title else ""),
                text=finding_to_text(finding),
                source_id=finding_control_id(finding),
            )
        )
    return inputs


def cap_batch(inputs: list[CrosswalkInput]) -> list[CrosswalkInput]:
    """Keep the findings whose text is among the first MAX_BATCH unique texts."""
    allowed: list[str] = []
    for item in inputs:
        if item.text not in allowed and len(allowed) < MAX_BATCH:
            allowed.append(item.text)
    kept = [i for i in inputs if i.text in allowed]
    if len(kept) < len(inputs):
        st.warning(
            f"This batch has more than {MAX_BATCH} distinct findings; only the first "
            f"{MAX_BATCH} ({len(kept)} of {len(inputs)} findings) will be mapped."
        )
    return kept


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

    input_label = "Input"
    input_text = ""
    single_source_id = None
    batch_findings: list = []

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
                                batch_findings = data["Findings"]
                                st.info(
                                    f"Loaded Lab Batch: {len(batch_findings)} findings ready to map."
                                )
                            else:
                                input_text = finding_to_text(data)
                                single_source_id = finding_control_id(data)
                                st.info(f"Loaded Lab File: {selected_lab_file}")
                        else:
                            input_text = f.read()
                            st.info(f"Loaded Lab File: {selected_lab_file}")
                    input_label = selected_lab_file

                    if not batch_findings:
                        with st.expander("View Lab File Contents"):
                            st.code(input_text)

        if text_input.strip() and not batch_findings:
            input_text = text_input
            input_label = "Pasted text"
            single_source_id = None

    with tab2:
        st.markdown("### Upload Raw Documents")
        uploaded_file = st.file_uploader(
            "Choose a PDF, JSON, or TXT file", type=["pdf", "json", "txt"], key="cw_up"
        )

        if uploaded_file is not None:
            try:
                if uploaded_file.name.endswith(".pdf"):
                    with st.spinner("Extracting text from the PDF..."):
                        input_text, page_count, cut = extract_pdf_text(uploaded_file)
                    st.success(f"Extracted text from {page_count} PDF pages.")
                    if cut:
                        st.warning(f"Only the first {MAX_PDF_PAGES} pages are used.")
                elif uploaded_file.name.endswith(".json"):
                    data = json.load(uploaded_file)
                    if is_securityhub_export(data):
                        batch_findings = data["Findings"]
                        st.success(
                            f"Batch mode: loaded {len(batch_findings)} Security Hub findings."
                        )
                    else:
                        input_text = finding_to_text(data)
                        single_source_id = finding_control_id(data)
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
                input_label = uploaded_file.name
            except Exception as e:
                st.error(f"Error reading file: {e}")

    st.markdown("---")

    inputs: list[CrosswalkInput] = []
    if batch_findings:
        inputs = cap_batch(findings_to_inputs(batch_findings))
    elif input_text.strip():
        inputs = [
            CrosswalkInput(
                label=input_label, text=input_text, source_id=single_source_id
            )
        ]

    st.caption(GROQ_NOTICE)
    col1, col2, col3 = st.columns([1, 1, 1])
    if col2.button(
        "🚀 Suggest SCF Controls",
        type="primary",
        width="stretch",
        key="cw_btn",
    ):
        scf_db = load_scf_database()
        if not inputs:
            st.warning(
                "Please provide some text, select a lab file, or upload a document to proceed."
            )
        elif not os.environ.get("GROQ_API_KEY"):
            st.error("No GROQ_API_KEY found in .env.")
        elif not scf_db:
            st.error("SCF database not found or empty. Use the sidebar to download it.")
        else:
            calls = unique_model_calls(inputs)
            progress_bar = st.progress(0)
            with st.spinner(
                f"Retrieving candidate controls and asking the model ({calls} call(s))..."
            ):
                results = run_crosswalk(
                    inputs,
                    lambda text, k: map_text_to_scf(text, top_k=k),
                    top_k=3,
                    on_progress=lambda done, total: progress_bar.progress(done / total),
                )
            # Kept in session state so that downloading an export (which
            # reruns the script) does not clear the results.
            st.session_state["cw_results"] = {
                "results": results,
                "is_batch": bool(batch_findings),
            }

    state = st.session_state.get("cw_results")
    if state:
        results = state["results"]
        scf_dict = {c["control_id"]: c for c in load_scf_database()}

        for r in results:
            if r.error:
                st.error(f"{md_escape(r.input.label)}: {md_escape(r.error)}")

        if not state["is_batch"]:
            [r] = results
            render_rejected(r.rejected)
            if r.mappings:
                st.success("Suggestions ready. Review each one.")
                st.markdown("### Suggested Controls")
            elif not r.error:
                st.warning("The model returned no valid SCF controls.")
            for m_idx, m in enumerate(r.mappings):
                with st.expander(
                    f"Suggestion #{m_idx + 1} | {m.control_id} - Domain: {m.domain} | Model confidence: {m.confidence}%",
                    expanded=True,
                ):
                    st.markdown(
                        f"**Control Description (SCF):** {md_escape(m.description)}"
                    )
                    st.markdown(
                        f"**Model Justification:** {md_escape(m.justification)}"
                    )
                    st.progress(m.confidence / 100.0)
                    render_regulations(m.regulations)
        else:
            summary = aggregate(results, scf_dict)
            render_rejected(all_rejected(results))
            st.success("Batch mapping complete.")
            st.markdown(f"### 🎯 {len(summary)} Suggested Controls")
            st.info(
                f"Suggestions for {len(results)} findings ({unique_model_calls([r.input for r in results])} distinct), "
                "merged by control and ranked by Priority Score: SCF relative weight × the sum of "
                "model confidences / 100 across the findings that mapped to it."
            )
            for m_idx, row in enumerate(summary):
                with st.expander(
                    f"#{m_idx + 1} | {row['SCF Control ID']} (Score: {row['Priority Score']}) | Hits: {row['Hit Count']}",
                    expanded=(m_idx < 3),
                ):
                    st.markdown(
                        f"**Control Description (SCF):** {md_escape(row['Control Description'])}"
                    )
                    st.markdown(
                        f"**Sample Model Justification:** {md_escape(row['Sample Model Justification'])}"
                    )
                    st.markdown(
                        "**Source controls / findings:** "
                        + md_escape(", ".join(row["Source Controls"]))
                    )
                    st.progress(row["Average Model Confidence (%)"] / 100.0)
                    render_regulations(row["Regulations"])

        details = detail_rows(results)
        if details:
            st.markdown("---")
            col_csv1, col_csv2, col_csv3 = st.columns([1, 2, 1])
            with col_csv2:
                st.success(f"{len(details)} suggestions ready to export.")
                if state["is_batch"]:
                    summary_df = pd.DataFrame(summary).drop(columns=["Regulations"])
                    summary_df["Source Controls"] = summary_df["Source Controls"].map(
                        ", ".join
                    )
                    st.download_button(
                        "📥 Download Ranked Summary (CSV)",
                        data=to_safe_csv(summary_df),
                        file_name="scf_crosswalk_summary.csv",
                        mime="text/csv",
                        type="primary",
                        width="stretch",
                    )
                st.download_button(
                    "📥 Download All Suggestions (CSV)",
                    data=to_safe_csv(pd.DataFrame(details)),
                    file_name="scf_crosswalk_suggestions.csv",
                    mime="text/csv",
                    type="secondary" if state["is_batch"] else "primary",
                    width="stretch",
                )
                oscal = oscal_mapping_collection(
                    results, scf_version=read_scf_release()
                )
                st.download_button(
                    "📥 Download OSCAL Mapping (JSON)",
                    data=json.dumps(oscal, indent=2).encode("utf-8"),
                    file_name="scf_crosswalk_oscal_mapping.json",
                    mime="application/json",
                    width="stretch",
                    help="An OSCAL 1.2 mapping-collection with status draft: every map is an unreviewed suggestion.",
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
                df_existing = read_uploaded_csv(uploaded_csv)
            elif selected_lab_csv != "None":
                resolved_csv = resolve_lab_file(selected_lab_csv)
                if resolved_csv is None:
                    st.error("Invalid file selection.")
                else:
                    df_existing = read_uploaded_csv(resolved_csv)

        id_column = None
        status_column = None
        in_place: list[str] = []
        with colB:
            if df_existing is not None and not df_existing.empty:
                st.markdown(f"### Current Controls Snapshot ({len(df_existing)} total)")
                st.dataframe(df_existing, height=180, width="stretch")
                columns = [str(c) for c in df_existing.columns]
                df_existing.columns = columns
                id_column = st.selectbox(
                    "Column holding SCF control IDs",
                    columns,
                    index=columns.index(detect_id_column(df_existing)),
                )
                status_options = ["(ignore status)"] + columns
                detected_status = detect_status_column(df_existing)
                picked = st.selectbox(
                    "Status column",
                    status_options,
                    index=status_options.index(detected_status)
                    if detected_status
                    else 0,
                    help="When set, only rows with an in-place status count as listed.",
                )
                if picked != "(ignore status)":
                    status_column = picked
                    values = sorted(
                        df_existing[picked].dropna().astype(str).str.strip().unique()
                    )
                    in_place = st.multiselect(
                        "Statuses that count as in place",
                        values,
                        default=default_in_place_statuses(values),
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
                st.session_state.pop("gap_report", None)
            elif not selected_columns:
                st.warning("Pick a framework that the SCF data has a column for.")
                st.session_state.pop("gap_report", None)
            else:
                st.session_state["gap_report"] = {
                    "report": analyze_gaps(
                        scf_db,
                        selected_columns,
                        df_existing,
                        id_column,
                        status_column,
                        in_place,
                    ),
                    "framework": target_framework,
                }

        gap_state = st.session_state.get("gap_report")
        if gap_state:
            report = gap_state["report"]
            framework_label = report.framework_columns[0]

            if report.unknown_ids:
                st.warning(
                    f"{len(report.unknown_ids)} ID(s) in your list are not SCF control IDs "
                    f"and cannot match anything: {md_escape(', '.join(report.unknown_ids[:15]))}"
                    + (" ..." if len(report.unknown_ids) > 15 else "")
                )
            if report.excluded_by_status:
                st.info(
                    f"{len(report.excluded_by_status)} SCF ID(s) in your list were not counted "
                    f"because of their status: {md_escape(', '.join(report.excluded_by_status[:15]))}"
                )

            if not report.rows:
                st.error(
                    f"No SCF controls map to {framework_label} in the downloaded data."
                )
            else:
                df_req = pd.DataFrame(report.rows)
                df_gaps = df_req[df_req["Status"] == STATUS_GAP]

                st.markdown(f"### Gap profile: {md_escape(framework_label)}")
                col_m1, col_m2, col_m3 = st.columns(3)
                col_m1.metric("SCF controls mapped", len(report.rows))
                col_m2.metric(
                    "✅ Listed in your controls",
                    report.covered,
                    delta=f"{round(report.covered / len(report.rows) * 100)}%",
                )
                col_m3.metric("❌ Not listed", report.gaps)
                st.caption(
                    "“Listed” means the SCF control ID appears in your list (with an in-place status, "
                    "if a status column is used). It says nothing about whether the control is "
                    "designed or operating effectively."
                )

                file_stub = gap_state["framework"].replace(" ", "_")
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
                            data=to_safe_csv(df_gaps),
                            file_name=f"gaps_{file_stub}.csv",
                            mime="text/csv",
                            type="primary",
                        )
                with tab_all:
                    st.dataframe(df_req, width="stretch")
                    st.download_button(
                        "📥 Download Full Checklist as CSV",
                        data=to_safe_csv(df_req),
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
        "controls to test. Suggested domains and control IDs are checked against the SCF database."
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

            if text_input.strip():
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
                        scope_text, _, cut = extract_pdf_text(uploaded_scope)
                        if cut:
                            st.warning(
                                f"Only the first {MAX_PDF_PAGES} pages are used."
                            )
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
            if not scope_text.strip():
                st.warning("Please paste or upload an audit scope document.")
            elif not os.environ.get("GROQ_API_KEY"):
                st.error("No GROQ_API_KEY found in .env.")
            else:
                with st.spinner(
                    "Retrieving candidate controls and asking the model..."
                ):
                    try:
                        st.session_state["scope_result"] = analyze_audit_scope(
                            scope_text
                        )
                    except Exception as e:
                        st.session_state.pop("scope_result", None)
                        st.error(f"Error analyzing scope: {md_escape(e)}")

        result = st.session_state.get("scope_result")
        if result:
            st.success("Suggestions ready. Review each one.")
            render_rejected(result.rejected_control_ids)
            render_rejected(result.rejected_domains, what="domain names")

            scf_dict = {c["control_id"]: c for c in scf_db}
            col_d, col_c = st.columns([1, 1])

            with col_d:
                st.markdown("### Suggested SCF Domains")
                for domain in result.recommended_domains:
                    st.markdown(f"- **{md_escape(domain)}**")

            control_rows = []
            with col_c:
                st.markdown("### Suggested Controls to Test")
                if not result.recommended_control_ids:
                    st.warning("The model returned no valid SCF control IDs.")
                for cid in result.recommended_control_ids:
                    control_info = scf_dict.get(cid, {})
                    description = control_info.get("description", "")
                    st.markdown(f"- `{cid}` — {md_escape(description[:80])}...")
                    control_rows.append(
                        {
                            "Control ID": cid,
                            "Domain": control_info.get("domain", ""),
                            "Description": description,
                            "SCF Control Question": control_info.get("question", ""),
                            "Evidence Request List": control_info.get("erl", ""),
                        }
                    )

            st.markdown("---")
            st.markdown("### Model Reasoning")
            st.info(md_escape(result.reasoning))

            if control_rows:
                col_e1, col_e2, col_e3 = st.columns([1, 2, 1])
                with col_e2:
                    st.download_button(
                        "📥 Download Test Plan as CSV",
                        data=to_safe_csv(pd.DataFrame(control_rows)),
                        file_name="audit_scope_test_plan.csv",
                        mime="text/csv",
                        type="primary",
                        width="stretch",
                    )
