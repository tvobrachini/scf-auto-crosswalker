import os
import streamlit as st
from fetch_scf import PARSED_JSON_FILE, download_scf, parse_scf, setup_directories
from mapper import load_scf_database


def render_sidebar():
    """Renders the main navigational sidebar and returns the selected tool mode and AI persona."""
    with st.sidebar:
        st.title("🛡️ Secure Controls Framework (SCF)")
        st.markdown("### GRC Assistant Platform")

        app_mode = st.radio(
            "Select Tool",
            [
                "🔍 SCF Auto-Crosswalker",
                "📉 Compliance Gap Analyzer",
                "🎯 Audit Scope Analyzer",
            ],
        )

        st.markdown("---")
        st.header("⚙️ System Status")

        api_key_status = (
            "🟢 Set" if os.environ.get("GROQ_API_KEY") else "🔴 Missing in .env"
        )
        st.write(f"**Groq API Key:** {api_key_status}")

        db_status = "🟢 Ready" if os.path.exists(PARSED_JSON_FILE) else "🔴 Not Found"
        st.write(f"**JSON SCF Database:** {db_status}")

        if st.button("🔄 Download / Update SCF Data"):
            with st.spinner("Downloading the latest SCF release from GitHub..."):
                setup_directories()
                if download_scf(force=True):
                    if parse_scf():
                        # Drop the in-memory copy so every tool sees the new
                        # data. The embedding cache rebuilds itself when the
                        # control texts change.
                        load_scf_database.clear()
                        st.success("Downloaded and parsed the latest SCF release.")
                        st.rerun()
                    else:
                        st.error("Failed to parse the SCF Excel file.")
                else:
                    st.error("Failed to download the SCF.")

        # Advanced Settings specifically for Crosswalker
        if app_mode == "🔍 SCF Auto-Crosswalker":
            st.markdown("---")
            st.header("⚙️ Advanced AI Settings")
            st.markdown("Add a reviewer perspective to the model's system prompt.")
            persona_options = [
                "None (Default General Auditor)",
                "Act as a strict PCI-DSS Qualified Security Assessor (QSA).",
                "Act as a FedRAMP 3PAO Assessor focusing on US Federal standards.",
                "Act as a GDPR Data Privacy Officer (DPO) focusing heavily on PII.",
            ]
            selected_persona = st.selectbox("AI Persona Lens", persona_options)
            persona_prompt = None if "None" in selected_persona else selected_persona
        else:
            persona_prompt = None

        st.markdown("---")
        st.info(
            "SCF data © Secure Controls Framework (securecontrolsframework.com), "
            "licensed CC BY-ND 4.0. It is downloaded at runtime and not redistributed."
        )

    return app_mode, persona_prompt
