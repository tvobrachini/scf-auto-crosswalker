"""Direct tests for src/ui/common.py helpers that pages rely on."""

import io
import os
from types import SimpleNamespace

import pandas as pd
import pytest

from crosswalk import MAX_BATCH, CrosswalkInput
from ui import common
from ui.common import (
    cap_batch,
    extract_pdf_text,
    fingerprint,
    load_lab_files,
    md_escape,
    read_uploaded_csv,
    resolve_lab_file,
)


class _St:
    """Records what a helper shows, instead of needing a Streamlit runtime."""

    def __init__(self):
        self.shown: list[tuple[str, str]] = []
        self.session_state: dict = {}

    def error(self, msg):
        self.shown.append(("error", msg))

    def warning(self, msg):
        self.shown.append(("warning", msg))

    def info(self, msg):
        self.shown.append(("info", msg))


@pytest.fixture
def fake_st(monkeypatch):
    st = _St()
    monkeypatch.setattr(common, "st", st)
    return st


def test_md_escape_blocks_links_images_and_html():
    out = md_escape("![x](https://evil) <b>*hi*</b> $x$")
    for ch in "![]()<>*$":
        assert out.count(ch) == out.count("\\" + ch)  # every one is escaped


def test_fingerprint_is_stable_and_input_sensitive():
    assert fingerprint("a", 1) == fingerprint("a", 1)
    assert fingerprint("a", 1) != fingerprint("a", 2)
    assert fingerprint("ab", "c") != fingerprint("a", "bc")


def test_resolve_lab_file_rejects_escapes(tmp_path):
    lab = tmp_path / "lab"
    lab.mkdir()
    (lab / "ok.txt").write_text("x")
    (tmp_path / "secret.txt").write_text("s")
    assert resolve_lab_file(str(lab), "ok.txt") == os.path.realpath(lab / "ok.txt")
    assert resolve_lab_file(str(lab), "../secret.txt") is None
    assert resolve_lab_file(str(lab), "/etc/passwd") is None
    (lab / "link").symlink_to(tmp_path / "secret.txt")
    assert resolve_lab_file(str(lab), "link") is None  # symlink out of the folder
    # A sibling whose name starts with the lab folder's name is not inside it.
    (tmp_path / "lab2").mkdir()
    (tmp_path / "lab2" / "f.txt").write_text("x")
    assert resolve_lab_file(str(lab), "../lab2/f.txt") is None


def test_load_lab_files_filters_by_mode_and_extension(tmp_path):
    for name in ["a.txt", "b.json", "c.csv", "demo_c.csv", "demo_d.txt"]:
        (tmp_path / name).write_text("x")
    (tmp_path / "sub").mkdir()
    real = load_lab_files(str(tmp_path), demo_mode=False)
    demo = load_lab_files(str(tmp_path), demo_mode=True)
    assert real == ["a.txt", "b.json", "c.csv"]
    assert demo == ["a.txt", "b.json", "demo_c.csv", "demo_d.txt"]
    assert load_lab_files(str(tmp_path), False, extension=(".txt", ".json")) == [
        "a.txt",
        "b.json",
    ]
    assert load_lab_files(str(tmp_path / "missing"), False) == []


def test_cap_batch_keeps_first_unique_texts_and_warns(fake_st):
    items = [CrosswalkInput(label=f"F{i}", text=f"t{i}") for i in range(MAX_BATCH + 3)]
    items.append(CrosswalkInput(label="dup", text="t0"))  # duplicate of a kept text
    kept = cap_batch(items)
    assert {i.text for i in kept} == {f"t{i}" for i in range(MAX_BATCH)}
    assert any(i.label == "dup" for i in kept)
    assert fake_st.shown and fake_st.shown[0][0] == "warning"


def test_cap_batch_is_silent_under_the_limit(fake_st):
    items = [CrosswalkInput(label="a", text="x"), CrosswalkInput(label="b", text="x")]
    assert cap_batch(items) == items
    assert fake_st.shown == []


def test_extract_pdf_text_cuts_at_the_page_limit(monkeypatch):
    def page(text):
        return SimpleNamespace(extract_text=lambda: text)

    pages = [page(f"p{i}") for i in range(common.MAX_PDF_PAGES + 2)]
    pages[1] = page(None)  # a scanned page with no text layer is skipped

    class Pdf:
        def __init__(self):
            self.pages = pages

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(common.pdfplumber, "open", lambda f: Pdf())
    text, read, truncated = extract_pdf_text(io.BytesIO(b""))
    assert read == common.MAX_PDF_PAGES and truncated is True
    assert text.startswith("p0\np2") and "p1" not in text.split("\n")
    assert f"p{common.MAX_PDF_PAGES}" not in text


def test_read_uploaded_csv_reports_bad_files(fake_st):
    ok = read_uploaded_csv(io.BytesIO(b"a,b\n1,2\n"))
    assert isinstance(ok, pd.DataFrame) and list(ok.columns) == ["a", "b"]
    assert read_uploaded_csv(io.BytesIO(b"\xff\xfe\x00bad")) is None
    assert read_uploaded_csv(io.BytesIO(b"")) is None
    kinds = [k for k, _ in fake_st.shown]
    assert kinds == ["error", "error"]
    assert "UTF-8" in fake_st.shown[0][1]


def test_show_if_current_hides_stale_results(fake_st):
    fake_st.session_state["r"] = {"fingerprint": "f1", "result": 1}
    assert common.show_if_current("r", "f1")["result"] == 1
    assert common.show_if_current("r", "f2") is None
    assert fake_st.shown[-1][0] == "info"
    assert common.show_if_current("missing", "f1") is None
