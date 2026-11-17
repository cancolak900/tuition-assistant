"""Traceability: every MCP test case in docs/03_Test_Plan.md (M-xx) is referenced by a test docstring."""

import ast
import re
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
PLAN = TESTS_DIR.parents[2] / "docs" / "03_Test_Plan.md"
ID = re.compile(r"\bM-\d{2}\b")


def _plan_ids() -> set[str]:
    return {m for line in PLAN.read_text(encoding="utf-8").splitlines() if line.startswith("| M-") for m in ID.findall(line.split("|")[1])}


def _docstring_ids() -> set[str]:
    ids: set[str] = set()
    for path in TESTS_DIR.glob("test_*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                ids |= set(ID.findall(ast.get_docstring(node) or ""))
    return ids


@pytest.mark.skipif(not PLAN.exists(), reason="test plan not available")
def test_every_plan_case_has_a_test():
    plan = _plan_ids()
    assert plan, "no M-xx rows found in the test plan"
    assert sorted(plan - _docstring_ids()) == []


@pytest.mark.skipif(not PLAN.exists(), reason="test plan not available")
def test_no_test_references_an_unknown_case():
    assert sorted(_docstring_ids() - _plan_ids()) == []
