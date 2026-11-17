"""Chunking of the policy document (FR-20)."""

from pathlib import Path

from app.chunker import chunk_file, chunk_markdown

POLICY = Path(__file__).resolve().parents[1] / "data" / "University_Tuition_Policies.md"
EXPECTED_SECTIONS = [
    "1", "2.1", "2.2", "2.3", "3.1", "3.2", "3.3", "3.4", "4.1", "4.2", "4.3", "5.1", "5.2",
    "6.1", "6.2", "6.3", "7.1", "7.2", "7.3", "7.4", "8.1", "8.2", "8.3", "8.4", "9",
]


def test_one_chunk_per_numbered_section():
    """M-01: one chunk per numbered section; sections 1, 2.1 ... 9 present; no empty chunks."""
    chunks = chunk_file(POLICY)
    assert [c.section for c in chunks] == EXPECTED_SECTIONS
    assert all(c.text.strip() for c in chunks)
    assert len({c.id for c in chunks}) == len(chunks)


def test_chunk_fields_keep_references():
    chunks = {c.section: c for c in chunk_file(POLICY)}
    c = chunks["3.2"]
    assert (c.heading, c.parent_heading) == ("Number and size of installments", "Installment policy")
    assert (c.document, c.documentId, c.id) == ("University_Tuition_Policies.md", "UNI-TUITION-2026-01", "UNI-TUITION-2026-01#3.2")
    assert "up to three installments" in c.text
    assert "**" not in c.text  # markdown emphasis removed
    assert chunks["1"].parent_heading is None  # a ## section without subsections stands alone


def test_headings_inside_code_blocks_are_ignored():
    md = "**Document ID:** DOC-1\n\n## 1. Intro\n\nText.\n\n```\n## 2. Not a heading\n### 2.1 Nope\n```\n\nMore text.\n"
    chunks = chunk_markdown(md, "doc.md")
    assert [c.section for c in chunks] == ["1"]
    assert "Not a heading" in chunks[0].text


def test_section_without_body_is_not_emitted():
    md = "## 1. Empty\n\n## 2. Parent\n\n### 2.1 Child\n\nBody.\n"
    assert [c.section for c in chunk_markdown(md, "doc.md")] == ["2.1"]


def test_document_id_falls_back_to_file_name():
    assert chunk_markdown("## 1. A\n\nB\n", "my_policy.md")[0].documentId == "my_policy"
