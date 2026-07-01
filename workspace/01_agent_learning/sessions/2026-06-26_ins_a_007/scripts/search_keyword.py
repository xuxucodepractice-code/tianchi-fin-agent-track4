#!/usr/bin/env python3
"""Search one keyword in a PDF and print page-level context."""

import argparse
from pathlib import Path

from pypdf import PdfReader


def normalize_space(text: str) -> str:
    return " ".join(text.split())


def search_pdf(pdf_path: Path, keyword: str, context_chars: int = 120) -> list[tuple[int, str]]:
    reader = PdfReader(str(pdf_path))
    matches = []

    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        start = text.find(keyword)
        if start == -1:
            continue

        context_start = max(0, start - context_chars)
        context_end = min(len(text), start + len(keyword) + context_chars)
        context = normalize_space(text[context_start:context_end])
        matches.append((page_number, context))

    return matches


def main() -> int:
    parser = argparse.ArgumentParser(description="Search one keyword in a PDF.")
    parser.add_argument("pdf_path", help="Path to a PDF file")
    parser.add_argument("keyword", help="Keyword to search")
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path)
    if not pdf_path.exists():
        print(f"PDF not found: {pdf_path}")
        return 1

    matches = search_pdf(pdf_path, args.keyword)
    if not matches:
        print(f"No matches found for keyword: {args.keyword}")
        return 1

    print(f"file: {pdf_path}")
    print(f"keyword: {args.keyword}")
    print()

    for page_number, context in matches:
        print(f"page: {page_number}")
        print(context)
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
