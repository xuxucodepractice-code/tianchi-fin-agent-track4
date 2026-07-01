#!/usr/bin/env python3
"""Map one raw document id to its local file path."""

import argparse
from pathlib import Path


def find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "public_dataset_upload").exists():
            return parent
    raise FileNotFoundError("Cannot find project root with public_dataset_upload/")


def map_doc_id(repo_root: Path, domain: str, doc_id: str) -> Path:
    return repo_root / "public_dataset_upload" / "raw" / domain / f"{doc_id}.pdf"


def main() -> int:
    parser = argparse.ArgumentParser(description="Map domain and doc_id to a raw file path.")
    parser.add_argument("domain", help="Domain name, for example: insurance")
    parser.add_argument("doc_id", help="Document id, for example: 1")
    args = parser.parse_args()

    repo_root = find_repo_root()
    raw_path = map_doc_id(repo_root, args.domain, args.doc_id)
    relative_path = raw_path.relative_to(repo_root)

    if not raw_path.exists():
        print(f"Raw file not found: {relative_path}")
        return 1

    print(relative_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
