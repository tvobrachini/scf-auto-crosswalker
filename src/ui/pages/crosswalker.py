"""Tool 1: SCF Auto-Crosswalker."""

import json
import os

import pandas as pd
import streamlit as st

from crosswalk import (
    CrosswalkInput,
    aggregate,
    all_rejected,
    detail_rows,
    run_crosswalk,
    unique_model_calls,
)
from exports import oscal_mapping_collection, to_safe_csv
from fetch_scf import read_scf_release
from findings import finding_control_id, finding_to_text, is_securityhub_export
from mapper import load_scf_database, map_text_to_scf
from ui.common import (
    MAX_PDF_PAGES,
    Labels,
    cap_batch,
    extract_pdf_text,
    findings_to_inputs,
    fingerprint,
    load_lab_files,
    md_escape,
    render_regulations,
    render_rejected,
    resolve_lab_file,
    show_if_current,
)


def render(labels: Labels, lab_data_dir: str) -> None:
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
        lab_files = load_lab_files(lab_data_dir, labels.demo_mode, extension=(".txt", ".json"))
        if lab_files:
            colA, colB = st.columns([1, 4])
            selected_lab_file = colA.selectbox(
                "Select Sample", ["None"] + lab_files, key="cw_lab"
            )
            if selected_lab_file != "None":
                resolved = resolve_lab_file(lab_data_dir, selected_lab_file)
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

    cw_fingerprint = fingerprint([(i.label, i.text, i.source_id) for i in inputs])

    st.caption(labels.groq_notice)
    col1, col2, col3 = st.columns([1, 1, 1])
    if col2.button(
        "🚀 Suggest Controls (demo catalog)"
        if labels.demo_mode
        else "🚀 Suggest SCF Controls",
        type="primary",
        width="stretch",
        key="cw_btn",
    ):
        scf_db = load_scf_database()
        st.session_state.pop("cw_results", None)
        if not inputs:
            st.warning(
                "Please provide some text, select a lab file, or upload a document to proceed."
            )
        elif not labels.demo_mode and not os.environ.get("GROQ_API_KEY"):
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
                "fingerprint": cw_fingerprint,
            }

    state = show_if_current("cw_results", cw_fingerprint)
    if state:
        results = state["results"]
        scf_dict = {c["control_id"]: c for c in load_scf_database()}

        for r in results:
            if r.error:
                st.error(f"{md_escape(r.input.label)}: {md_escape(r.error)}")

        if not state["is_batch"]:
            [r] = results
            render_rejected(r.rejected, labels.catalog_short)
            if r.capped:
                st.caption(
                    f"The model also suggested {md_escape(', '.join(r.capped))}, "
                    "beyond the top 3; not shown."
                )
            if r.mappings:
                st.success("Suggestions ready. Review each one.")
                st.markdown("### Suggested Controls")
            elif not r.error:
                st.warning(f"The model returned no valid {labels.catalog_short} controls.")
            for m_idx, m in enumerate(r.mappings):
                with st.expander(
                    f"Suggestion #{m_idx + 1} | {m.control_id} - Domain: {m.domain} | Model confidence: {m.confidence}%",
                    expanded=True,
                ):
                    st.markdown(
                        f"**Control Description ({labels.catalog_label}):** {md_escape(m.description)}"
                    )
                    st.markdown(
                        f"**Model Justification:** {md_escape(m.justification)}"
                    )
                    st.progress(m.confidence / 100.0)
                    render_regulations(m.regulations, labels.catalog_label)
        else:
            summary = aggregate(results, scf_dict)
            render_rejected(all_rejected(results), labels.catalog_short)
            st.success("Batch mapping complete.")
            st.markdown(f"### 🎯 {len(summary)} Suggested Controls")
            st.info(
                f"Suggestions for {len(results)} findings ({unique_model_calls([r.input for r in results])} distinct), "
                f"merged by control and ranked by Priority Score: {labels.catalog_short} relative weight × the sum of "
                "model confidences / 100 across the distinct findings that mapped to it (identical "
                "findings, such as one control failing on many resources, count once)."
            )
            for m_idx, row in enumerate(summary):
                with st.expander(
                    f"#{m_idx + 1} | {row['SCF Control ID']} (Score: {row['Priority Score']}) | Findings: {row['Findings']}",
                    expanded=(m_idx < 3),
                ):
                    st.markdown(
                        f"**Control Description ({labels.catalog_label}):** {md_escape(row['Control Description'])}"
                    )
                    st.markdown(
                        f"**Sample Model Justification:** {md_escape(row['Sample Model Justification'])}"
                    )
                    st.markdown(
                        "**Source controls / findings:** "
                        + md_escape(", ".join(row["Source Controls"]))
                    )
                    st.progress(row["Average Model Confidence (%)"] / 100.0)
                    render_regulations(row["Regulations"], labels.catalog_label)

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
