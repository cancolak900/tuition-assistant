"""Build the BM25 index once, before any query (FR-21).

Usage:  python -m scripts.build_index [--source data/University_Tuition_Policies.md] [--out index/policy_index.json]
"""

import argparse
from pathlib import Path

from app.chunker import chunk_file
from app.index import build_index, save_index

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "data" / "University_Tuition_Policies.md"
DEFAULT_OUT = ROOT / "index" / "policy_index.json"


def main(argv: list[str] | None = None) -> Path:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    chunks = chunk_file(args.source)
    path = save_index(build_index(chunks), args.out)
    print(f"Indexed {len(chunks)} sections of {args.source.name} -> {path}")
    return path


if __name__ == "__main__":
    main()
