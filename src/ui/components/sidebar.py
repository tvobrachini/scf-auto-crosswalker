import os
import streamlit as st
from fetch_scf import PARSED_JSON_FILE, download_scf, parse_scf

def render_sidebar():
    """Renders the main navigational sidebar and returns the selected tool mode and AI persona."""
    with st.sidebar:
        st.title("🛡️ Secure Controls Framework (SCF)")
        st.markdown("### GRC Assistant Platform")

        app_mode = st.radio(
            "Select Tool", ["🔍 SCF Auto-Crosswalker", "📉 Compliance Gap Analyzer"]
        )

        st.markdown("---")
        st.header("⚙️ System Status")

        api_key_status = (
            "🟢 Set" if os.environ.get("GROQ_API_KEY") else "🔴 Missing in .env"
        )
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
                "Act as a GDPR Data Privacy Officer (DPO) focusing heavily on PII.",
            ]
            selected_persona = st.selectbox("AI Persona Lens", persona_options)
            persona_prompt = None if "None" in selected_persona else selected_persona
        else:
            persona_prompt = None

        st.markdown("---")
        st.info(
            "Licensed under CC Attribution-NoDerivatives 4.0. Data provided by securecontrolsframework.com"
        )
        
    return app_mode, persona_prompt
