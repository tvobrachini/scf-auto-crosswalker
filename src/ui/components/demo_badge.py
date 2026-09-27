import html

import streamlit as st
from demo import DEMO_BADGE

DEMO_DETAIL = (
    "No Groq call, no Hugging Face download and no SCF download. The control "
    "catalog (IDs starting with D, such as DCRY-01) is synthetic, not SCF content, "
    "and a canned stand-in picks the top retrieved candidates in place of the "
    "language model, so the suggestions say nothing about real accuracy. "
    "Validation, enrichment, batching, gap analysis and exports are the real code."
)

_STYLE = (
    "background:#f59e0b;color:#111827;border-radius:8px;padding:0.55rem 0.9rem;"
    "margin-bottom:0.6rem;font-weight:700;letter-spacing:0.01em;"
)


def render_demo_badge(detail: bool = True) -> None:
    """A prominent DEMO MODE banner. Rendered on every page when DEMO_MODE is on."""
    body = f"🧪 {html.escape(DEMO_BADGE)}"
    if detail:
        body += (
            '<div style="font-weight:400;font-size:0.85rem;margin-top:0.25rem">'
            f"{html.escape(DEMO_DETAIL)}</div>"
        )
    st.markdown(
        f'<div class="demo-badge" style="{_STYLE}">{body}</div>',
        unsafe_allow_html=True,
    )
