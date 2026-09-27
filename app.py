import os
import sys
from dotenv import load_dotenv

# Load .env variables (picks up OPENROUTER_API_KEY and OPENROUTER_MODEL)
load_dotenv()

# Ensure the src directory is available for imports
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

import streamlit as st  # noqa: E402
from demo import (  # noqa: E402
    DemoModeNotAllowedError,
    demo_mode_enabled,
)
from ui.common import build_labels  # noqa: E402
from ui.components.demo_badge import render_demo_badge  # noqa: E402
from ui.components.sidebar import render_sidebar  # noqa: E402
from ui.components.styles import inject_premium_css  # noqa: E402
from ui.pages import crosswalker, gap_analyzer, scope_analyzer  # noqa: E402

st.set_page_config(page_title="GRC Assistant", page_icon="🛡️", layout="wide")

# --- Custom CSS ---
inject_premium_css()

# --- Demo mode (src/demo.py): refused in production, always badged ---
try:
    DEMO_MODE = demo_mode_enabled()
except DemoModeNotAllowedError as e:
    st.error(str(e))
    st.stop()
if DEMO_MODE:
    render_demo_badge()

# --- Sidebar Navigation & Setup ---
app_mode = render_sidebar()

LAB_DATA_DIR = os.path.join(os.path.dirname(__file__), "lab_data")

# Wording that switches between the real SCF and the synthetic demo catalog,
# shared by all three tools below.
LABELS = build_labels(DEMO_MODE)

if app_mode == "🔍 SCF Auto-Crosswalker":
    crosswalker.render(LABELS, LAB_DATA_DIR)
elif app_mode == "📉 Compliance Gap Analyzer":
    gap_analyzer.render(LABELS, LAB_DATA_DIR)
elif app_mode == "🎯 Audit Scope Analyzer":
    scope_analyzer.render(LABELS, LAB_DATA_DIR)
