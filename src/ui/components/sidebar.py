import os

import streamlit as st
from fetch_scf import (
    PARSED_JSON_FILE,
    download_scf,
    parse_scf,
    read_scf_release,
    setup_directories,
)
from mapper import clear_scf_cache

TOOLS = [
    "🔍 SCF Auto-Crosswalker",
    "📉 Compliance Gap Analyzer",
    "🎯 Audit Scope Analyzer",
]


def render_sidebar() -> str:
    """Render the navigation sidebar and return the selected tool."""
    with st.sidebar:
        st.title("🛡️ Secure Controls Framework (SCF)")
        st.markdown("### GRC Assistant Platform")

        app_mode = st.radio("Select Tool", TOOLS)

        st.markdown("---")
        st.header("⚙️ System Status")

        api_key_status = (
            "🟢 Set" if os.environ.get("GROQ_API_KEY") else "🔴 Missing in .env"
        )
        st.write(f"**Groq API Key:** {api_key_status}")

        if os.path.exists(PARSED_JSON_FILE):
            release = read_scf_release()
            st.write(f"**SCF Database:** 🟢 {release or 'Ready'}")
        else:
            st.write("**SCF Database:** 🔴 Not downloaded")

        if st.button("🔄 Download / Update SCF Data"):
            with st.spinner("Downloading the latest SCF release from GitHub..."):
                setup_directories()
                if download_scf(force=True):
                    if parse_scf():
                        # Drop the in-memory copy so every tool sees the new
                        # data. The embedding cache rebuilds itself when the
                        # control texts change.
                        clear_scf_cache()
                        st.success("Downloaded and parsed the latest SCF release.")
                        st.rerun()
                    else:
                        st.error("Failed to parse the SCF Excel file.")
                else:
                    st.error("Failed to download the SCF.")

        st.markdown("---")
        st.info(
            "SCF data © Secure Controls Framework (securecontrolsframework.com), "
            "licensed CC BY-ND 4.0. It is downloaded at runtime and not redistributed."
        )

    return app_mode
