"""Split the policy markdown into one chunk per numbered section (FR-20).

- Every `### 2.1 Heading` becomes a chunk.
- A `## 1. Heading` section with no `###` subsections becomes a chunk of its own.
- Headings inside fenced code blocks are ignored.
Each chunk keeps: id, section, heading, parent_heading, text, document, documentId.
"""

import re
from dataclasses import asdict, dataclass
from pathlib import Path

H2 = re.compile(r"^##\s+(\d+)\.\s+(.+?)\s*$")
H3 = re.compile(r"^###\s+(\d+\.\d+)\s+(.+?)\s*$")
DOC_ID = re.compile(r"\*\*Document ID:\*\*\s*([A-Za-z0-9-]+)")


@dataclass(frozen=True)
class Chunk:
    id: str
    section: str
    heading: str
    parent_heading: str | None
    text: str
    document: str
    documentId: str  # noqa: N815 (field name is part of the JSON contract)

    def to_dict(self) -> dict:
        return asdict(self)


def _clean(lines: list[str]) -> str:
    """Join body lines into readable plain text (drop bold/inline-code markers, keep code blocks)."""
    text = "\n".join(lines).strip()
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<!`)`([^`\n]+)`(?!`)", r"\1", text)
    return re.sub(r"\n{3,}", "\n\n", text)


def chunk_markdown(markdown: str, document: str) -> list[Chunk]:
    match = DOC_ID.search(markdown)
    document_id = match.group(1) if match else Path(document).stem

    chunks: list[Chunk] = []
    h2_num = h2_title = None
    h2_has_children = False
    current: dict | None = None  # the section being collected
    in_code = False

    def flush() -> None:
        if current is None:
            return
        text = _clean(current["lines"])
        if text:  # never emit empty chunks
            chunks.append(Chunk(
                id=f"{document_id}#{current['section']}",
                section=current["section"],
                heading=current["heading"],
                parent_heading=current["parent"],
                text=text,
                document=document,
                documentId=document_id,
            ))

    for line in markdown.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
        if not in_code and (m := H2.match(line)):
            flush()
            h2_num, h2_title, h2_has_children = m.group(1), m.group(2), False
            current = {"section": h2_num, "heading": h2_title, "parent": None, "lines": []}
            continue
        if not in_code and (m := H3.match(line)):
            if not h2_has_children and current is not None and current["section"] == h2_num:
                current = None  # the ## intro is dropped when the section has subsections (only a short lead-in)
            flush()
            h2_has_children = True
            current = {"section": m.group(1), "heading": m.group(2), "parent": h2_title, "lines": []}
            continue
        if current is not None:
            current["lines"].append(line)
    flush()
    return chunks


def chunk_file(path: str | Path) -> list[Chunk]:
    path = Path(path)
    return chunk_markdown(path.read_text(encoding="utf-8"), path.name)
