"""Tool 3: Audit Scope Analyzer."""

import os

import pandas as pd
import streamlit as st

from exports import to_safe_csv
from mapper import analyze_audit_scope, load_scf_database
from ui.common import (
    MAX_PDF_PAGES,
    Labels,
    extract_pdf_text,
    fingerprint,
    load_lab_files,
    md_escape,
    render_rejected,
    resolve_lab_file,
    show_if_current,
)


def render(labels: Labels, lab_data_dir: str) -> None:
    st.title("🎯 Audit Scope Analyzer")
    st.markdown(
        "Paste or upload an audit scope document and the model will suggest SCF domains and "
        "controls to test. Suggested domains and control IDs are checked against the SCF database."
    )

    scf_db = load_scf_database()
    if not scf_db:
        st.error("SCF database not found. Please download it using the sidebar.")
        return

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
        lab_txt = load_lab_files(lab_data_dir, labels.demo_mode, extension=".txt")
        if lab_txt:
            selected_lab_txt = st.selectbox(
                "Select Sample", ["None"] + lab_txt, key="scope_lab"
            )
            if selected_lab_txt != "None":
                resolved = resolve_lab_file(lab_data_dir, selected_lab_txt)
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
                        st.warning(f"Only the first {MAX_PDF_PAGES} pages are used.")
                else:
                    scope_text = uploaded_scope.getvalue().decode("utf-8")
                st.success(f"Loaded: {uploaded_scope.name}")
            except UnicodeDecodeError:
                st.error("File encoding not supported. Please upload a UTF-8 file.")
            except Exception as e:
                st.error(f"Error reading file: {e}")

    scope_fingerprint = fingerprint(scope_text)

    st.markdown("---")
    st.caption(labels.groq_notice)
    col1, col2, col3 = st.columns([1, 1, 1])
    if col2.button(
        "🎯 Suggest Controls to Test",
        type="primary",
        width="stretch",
        key="scope_btn",
    ):
        st.session_state.pop("scope_result", None)
        if not scope_text.strip():
            st.warning("Please paste or upload an audit scope document.")
        elif not labels.demo_mode and not os.environ.get("GROQ_API_KEY"):
            st.error("No GROQ_API_KEY found in .env.")
        else:
            with st.spinner("Retrieving candidate controls and asking the model..."):
                try:
                    analysis = analyze_audit_scope(scope_text)
                except Exception as e:
                    analysis = None
                    st.error(f"Error analyzing scope: {md_escape(e)}")
                if analysis is not None:
                    st.session_state["scope_result"] = {
                        "result": analysis,
                        "fingerprint": scope_fingerprint,
                    }

    scope_state = show_if_current("scope_result", scope_fingerprint)
    result = scope_state["result"] if scope_state else None
    if result:
        st.success("Suggestions ready. Review each one.")
        render_rejected(result.rejected_control_ids, labels.catalog_short)
        render_rejected(
            result.rejected_domains, labels.catalog_short, what="domain names"
        )
        if result.capped_control_ids:
            st.caption(
                f"The model also suggested {md_escape(', '.join(result.capped_control_ids))}, "
                "beyond the 10-control limit; not shown."
            )

        scf_dict = {c["control_id"]: c for c in scf_db}
        col_d, col_c = st.columns([1, 1])

        with col_d:
            st.markdown(
                "### Suggested Domains" + labels.demo_suffix
                if labels.demo_mode
                else "### Suggested SCF Domains"
            )
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
