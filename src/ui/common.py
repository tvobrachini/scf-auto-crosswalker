"""Shared helpers and labels used by more than one page in src/ui/pages/."""

import hashlib
import json
import os
import re
from dataclasses import dataclass

import pandas as pd
import pdfplumber
import streamlit as st

from crosswalk import MAX_BATCH, CrosswalkInput
from findings import finding_control_id, finding_to_text

# Frameworks whose crosswalk references are surfaced by default (the rest are
# collapsed behind a "+N more" caption).
PRIORITY_FRAMEWORKS = ["gdpr", "iso", "nist", "soc", "pci", "ccpa", "hipaa"]

MAX_PDF_PAGES = 50

# Characters with meaning in Streamlit Markdown (links, images, emphasis,
# HTML, colour directives). Model output is escaped before rendering, so a
# prompt-injected document cannot make the page load an external image or
# render a link.
_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~$:])")


def md_escape(text: str) -> str:
    return _MD_SPECIAL.sub(r"\\\1", str(text))


@dataclass(frozen=True)
class Labels:
    """Wording that switches between the real SCF and the synthetic demo catalog."""

    demo_mode: bool
    catalog_label: str  # "SCF" / "synthetic demo catalog"
    catalog_short: str  # "SCF" / "demo catalog"
    example_id: str  # "CRY-01" / "DCRY-01"
    demo_suffix: str  # "" / " (demo catalog)"
    groq_notice: str


def build_labels(demo_mode: bool) -> Labels:
    """Derive the catalog wording and Groq notice from whether demo mode is on."""
    groq_notice = (
        "DEMO MODE: nothing is sent to Groq; a canned stand-in picks from the retrieved "
        "candidates of the synthetic catalog."
        if demo_mode
        else "Text you submit is sent to Groq's API for the LLM step. "
        "Do not submit confidential audit data unless your organization allows it."
    )
    return Labels(
        demo_mode=demo_mode,
        # Where control text and crosswalk references come from, as shown in labels.
        catalog_label="synthetic demo catalog" if demo_mode else "SCF",
        # Short form for IDs, domains and buttons ("SCF controls mapped" / "demo catalog controls mapped").
        catalog_short="demo catalog" if demo_mode else "SCF",
        example_id="DCRY-01" if demo_mode else "CRY-01",
        demo_suffix=" (demo catalog)" if demo_mode else "",
        groq_notice=groq_notice,
    )


def fingerprint(*parts: object) -> str:
    """
    A stable digest of the inputs a result was computed from.

    Results are kept in session state (so a download click, which reruns the
    script, does not clear them) together with this digest, and are shown
    only while the current inputs still match. Otherwise a result, and its
    exports, could be attributed to an input that is no longer on screen.
    """
    return hashlib.sha256(
        json.dumps(parts, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def show_if_current(key: str, current: str):
    """The stored result for `key` if it was computed from `current` inputs."""
    state = st.session_state.get(key)
    if not state:
        return None
    if state["fingerprint"] != current:
        st.info(
            "The inputs changed since the last run. Run the analysis again to see results."
        )
        return None
    return state


def load_lab_files(lab_data_dir: str, demo_mode: bool, extension=None):
    if not os.path.exists(lab_data_dir):
        return []
    files = sorted(
        f
        for f in os.listdir(lab_data_dir)
        if os.path.isfile(os.path.join(lab_data_dir, f))
    )
    if extension:
        files = [f for f in files if f.endswith(extension)]
    # demo_* inputs match only the synthetic demo catalog, and the other
    # control lists match only real SCF IDs, so each mode lists its own.
    if demo_mode:
        return [f for f in files if f.startswith("demo_") or not f.endswith(".csv")]
    return [f for f in files if not f.startswith("demo_")]


def resolve_lab_file(lab_data_dir: str, name: str) -> str | None:
    """Absolute path of a file directly inside lab_data_dir, or None if it escapes it."""
    resolved = os.path.realpath(os.path.join(lab_data_dir, name))
    if not resolved.startswith(os.path.realpath(lab_data_dir) + os.sep):
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


def render_regulations(regulations: dict, catalog_label: str) -> None:
    if not regulations:
        return
    st.markdown(f"#### Framework references (from the {catalog_label} crosswalk)")
    display_regs = {
        r: v
        for r, v in regulations.items()
        if any(p in r.lower() for p in PRIORITY_FRAMEWORKS)
    }
    for r, v in display_regs.items():
        st.markdown(f"- **{md_escape(r)}:** {md_escape(v)}")
    other_regs = len(regulations) - len(display_regs)
    if other_regs > 0:
        st.caption(
            f"*(+{other_regs} more framework references in the {catalog_label} data)*"
        )


def render_rejected(rejected: list[str], catalog_short: str, what: str = "IDs") -> None:
    if rejected:
        st.warning(
            f"The model also returned {what} that are not among the {catalog_short} candidates it "
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
