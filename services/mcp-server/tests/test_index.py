"""BM25 index: built once, loaded from file, ranked search (FR-21, FR-23)."""

import json
from pathlib import Path

import pytest

import app.index as index_module
from app.index import PolicyIndex
from app.text import tokenize
from scripts.build_index import main as build_main

POLICY = Path(__file__).resolve().parents[1] / "data" / "University_Tuition_Policies.md"


@pytest.fixture(scope="module")
def index_file(tmp_path_factory) -> Path:
    return build_main(["--source", str(POLICY), "--out", str(tmp_path_factory.mktemp("idx") / "policy_index.json")])


@pytest.fixture(scope="module")
def ix(index_file) -> PolicyIndex:
    return PolicyIndex.load(index_file)


def test_build_script_writes_the_index_file(index_file):
    data = json.loads(index_file.read_text(encoding="utf-8"))
    assert data["documentId"] == "UNI-TUITION-2026-01"
    assert len(data["chunks"]) == len(data["tokens"]) == 25


def test_queries_never_rebuild_the_index(index_file, monkeypatch):
    """M-02: the index loads from the prebuilt file; the build function runs 0 times per query."""
    calls = {"build": 0, "bm25": 0}
    real_bm25 = index_module.BM25Okapi

    def counting_bm25(*args, **kwargs):
        calls["bm25"] += 1
        return real_bm25(*args, **kwargs)

    monkeypatch.setattr(index_module, "build_index", lambda *a, **k: calls.__setitem__("build", calls["build"] + 1))
    monkeypatch.setattr(index_module, "BM25Okapi", counting_bm25)
    loaded = PolicyIndex.load(index_file)
    for q in ("deadline", "installments", "late fee", "refund", "scholarship"):
        loaded.search(q)
    assert calls == {"build": 0, "bm25": 1}  # BM25 model created once at load, never per query


def test_query_payment_deadline_fall(ix):
    """M-03: "payment deadline fall" -> top match 2.1."""
    assert ix.search("payment deadline fall")[0]["section"] == "2.1"


def test_query_installments_how_many(ix):
    """M-04: "installments how many" -> top match 3.2, with 3.1 or 3.3 in the top 3."""
    sections = [m["section"] for m in ix.search("installments how many", top_k=3)]
    assert sections[0] == "3.2"
    assert {"3.1", "3.3"} & set(sections)


def test_query_late_fee_overdue(ix):
    """M-05: "late fee overdue" -> top match 4.1."""
    assert ix.search("late fee overdue")[0]["section"] == "4.1"


def test_nonsense_query_returns_no_matches(ix):
    """M-06: a nonsense query returns no matches (zero scores are dropped)."""
    assert ix.search("zzqx") == []
    assert ix.search("") == []
    assert ix.search("the and of") == []  # only stopwords


def test_results_are_ranked_and_limited(ix):
    results = ix.search("refund withdrawal", top_k=2)
    assert len(results) == 2
    assert results[0]["score"] >= results[1]["score"] > 0
    assert set(results[0]) == {"section", "heading", "text", "score"}
    assert ix.search("refund", top_k=0) == []


def test_unsupported_index_format_is_rejected(index_file):
    data = json.loads(index_file.read_text(encoding="utf-8"))
    data["formatVersion"] = 999
    with pytest.raises(ValueError):
        PolicyIndex.from_dict(data)


def test_tokenizer_normalizes_text():
    assert tokenize("Installments, LATE fees & Deadlines!") == ["installment", "late", "fee", "deadline"]
    assert tokenize("The posting of payments") == ["post", "payment"]
