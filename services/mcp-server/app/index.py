"""BM25 index over the policy chunks (FR-21).

The index is built once (scripts/build_index.py, at image build time) and saved as JSON.
At startup the server loads that file and creates the BM25 model a single time; queries never
rebuild anything.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from rank_bm25 import BM25Okapi

from app.chunker import Chunk
from app.text import tokenize

HEADING_BOOST = 2  # heading tokens are repeated so a match in the heading counts more
FORMAT_VERSION = 1


def chunk_tokens(chunk: Chunk) -> list[str]:
    tokens = tokenize(chunk.heading) * HEADING_BOOST
    if chunk.parent_heading:
        tokens += tokenize(chunk.parent_heading)
    return tokens + tokenize(chunk.text)


def build_index(chunks: list[Chunk]) -> dict:
    if not chunks:
        raise ValueError("no chunks to index")
    return {
        "formatVersion": FORMAT_VERSION,
        "document": chunks[0].document,
        "documentId": chunks[0].documentId,
        "chunks": [c.to_dict() for c in chunks],
        "tokens": [chunk_tokens(c) for c in chunks],
    }


def save_index(index: dict, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


@dataclass
class PolicyIndex:
    document: str
    document_id: str
    chunks: list[dict]
    bm25: BM25Okapi = field(repr=False)

    @classmethod
    def from_dict(cls, data: dict) -> "PolicyIndex":
        if data.get("formatVersion") != FORMAT_VERSION:
            raise ValueError("unsupported index format; rebuild it with scripts/build_index.py")
        return cls(data["document"], data["documentId"], data["chunks"], BM25Okapi(data["tokens"]))

    @classmethod
    def load(cls, path: str | Path) -> "PolicyIndex":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        """Best matching sections first. Sections with no matching term (score 0) are never returned."""
        terms = tokenize(query)
        if not terms or top_k < 1:
            return []
        scores = self.bm25.get_scores(terms)
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        results = []
        for i in ranked[:top_k]:
            if scores[i] <= 0:
                break
            c = self.chunks[i]
            results.append({"section": c["section"], "heading": c["heading"], "text": c["text"], "score": round(float(scores[i]), 4)})
        return results
