"""Tool 2: Compliance Gap Analyzer."""

import pandas as pd
import streamlit as st

from exports import to_safe_csv
from gap_analysis import (
    STATUS_GAP,
    analyze_gaps,
    default_in_place_statuses,
    detect_id_column,
    detect_status_column,
    framework_columns,
)
from mapper import load_scf_database
from ui.common import (
    Labels,
    fingerprint,
    load_lab_files,
    md_escape,
    read_uploaded_csv,
    resolve_lab_file,
    show_if_current,
)


def render(labels: Labels, lab_data_dir: str) -> None:
    st.title("📉 Compliance Gap Analyzer")
    st.markdown(
        f"For each requirement of a framework that the {labels.catalog_label}'s own crosswalk cites, "
        f"check whether any {labels.catalog_short} control mapped to it appears, by "
        f"{labels.catalog_short} control ID, in your existing control list. No LLM is used."
    )

    scf_db = load_scf_database()
    if not scf_db:
        st.error("SCF database missing. Please download it using the sidebar.")
        return

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
            f"{labels.catalog_short} crosswalk column",
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
            f"Upload a CSV of your current controls. Pick the column that holds **{labels.catalog_short} control IDs** "
            f"(e.g. `{labels.example_id}`): the ID column if you number controls the {labels.catalog_short} way, or a column "
            f"that maps each of your controls to {labels.catalog_short} IDs. A cell can hold several IDs, separated "
            "by `;`, `,`, `|` or new lines."
        )
        uploaded_csv = st.file_uploader("Upload CSV", type=["csv"], key="gap_up")

        lab_csv = load_lab_files(lab_data_dir, labels.demo_mode, extension=".csv")
        selected_lab_csv = st.selectbox(
            "Or select Lab Data", ["None"] + lab_csv, key="gap_lab"
        )

        df_existing = None
        if uploaded_csv:
            df_existing = read_uploaded_csv(uploaded_csv)
        elif selected_lab_csv != "None":
            resolved_csv = resolve_lab_file(lab_data_dir, selected_lab_csv)
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
                f"Column holding {labels.catalog_short} control IDs (detected)",
                columns,
                index=columns.index(
                    detect_id_column(df_existing, {c["control_id"] for c in scf_db})
                ),
            )
            status_options = ["(ignore status)"] + columns
            detected_status = detect_status_column(df_existing)
            picked = st.selectbox(
                "Status column",
                status_options,
                index=status_options.index(detected_status) if detected_status else 0,
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

    gap_fingerprint = fingerprint(
        selected_columns,
        id_column,
        status_column,
        sorted(in_place),
        None
        if df_existing is None
        else int(pd.util.hash_pandas_object(df_existing, index=True).sum()),
        list(df_existing.columns) if df_existing is not None else None,
    )

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
                "fingerprint": gap_fingerprint,
            }

    gap_state = show_if_current("gap_report", gap_fingerprint)
    if gap_state:
        report = gap_state["report"]
        framework_label = report.framework_columns[0]

        if report.unknown_ids:
            st.warning(
                f"{len(report.unknown_ids)} ID(s) in your list are not {labels.catalog_short} control IDs "
                f"and cannot match anything: {md_escape(', '.join(report.unknown_ids[:15]))}"
                + (" ..." if len(report.unknown_ids) > 15 else "")
            )
        if report.excluded_by_status:
            st.info(
                f"{len(report.excluded_by_status)} {labels.catalog_short} ID(s) in your list were not counted "
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
            n_req = len(report.requirements)
            col_r1, col_r2, col_r3 = st.columns(3)
            col_r1.metric(
                f"Requirements {labels.catalog_short} maps controls to", n_req
            )
            col_r2.metric(
                "✅ With a listed control",
                report.requirements_addressed,
                # A share, not a change: no arrow, one decimal.
                delta=f"{report.requirements_addressed / n_req * 100:.1f}% of requirements"
                if n_req
                else None,
                delta_color="off",
                delta_arrow="off",
            )
            col_r3.metric("❌ With none", n_req - report.requirements_addressed)
            col_m1, col_m2, col_m3 = st.columns(3)
            col_m1.metric(f"{labels.catalog_short} controls mapped", len(report.rows))
            col_m2.metric(
                "✅ Listed in your controls",
                report.covered,
                delta=f"{report.covered / len(report.rows) * 100:.1f}% of mapped",
                delta_color="off",
                delta_arrow="off",
            )
            col_m3.metric("❌ Not listed", report.gaps)
            st.caption(
                "Requirements are the framework's own references as the "
                f"{labels.catalog_short} crosswalk cites them (SOC 2 points of focus roll up to "
                "their criterion, ISO 27001 list items to their clause). A requirement "
                "with a listed control is a place to start testing, not a requirement met. "
                f"“Listed” means the {labels.catalog_short} control ID appears in your list (with an "
                "in-place status, if a status column is used). It says nothing about "
                "whether the control is designed or operating effectively."
            )

            file_stub = gap_state["framework"].replace(" ", "_")
            # Column names follow the catalog in use (SCF or the demo catalog).
            df_reqs = pd.DataFrame(report.requirements).rename(
                columns={
                    "SCF controls mapped": f"{labels.catalog_short} controls mapped",
                    "Listed SCF controls": f"Listed {labels.catalog_short} controls",
                    "Not listed SCF controls": f"Not listed {labels.catalog_short} controls",
                }
            )
            tab_reqs, tab_gaps, tab_all = st.tabs(
                [
                    f"By requirement ({len(df_reqs)})",
                    f"❌ Controls not listed ({len(df_gaps)})",
                    f"Full Checklist ({len(df_req)})",
                ]
            )
            with tab_reqs:
                st.dataframe(df_reqs, width="stretch")
                st.download_button(
                    "📥 Download Requirements as CSV",
                    data=to_safe_csv(df_reqs),
                    file_name=f"requirements_{file_stub}.csv",
                    mime="text/csv",
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
