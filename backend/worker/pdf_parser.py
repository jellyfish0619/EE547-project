"""
PDF Parser — converts a PDF file into a list of text chunks.

Each chunk is a dict:
    {
        "page":    int,   # 1-based page number
        "index":   int,   # chunk index within the page
        "text":    str,   # cleaned text content
    }

Strategy:
  1. Try pdfplumber first (better at text + table extraction).
  2. Fall back to PyMuPDF (fitz) if pdfplumber yields nothing.
  3. Split each page's text into sentences, then greedily accumulate sentences
     until the chunk length falls in [CHUNK_MIN, CHUNK_MAX].
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Union

import pdfplumber
import fitz  # PyMuPDF

# Target chunk size range (characters).
CHUNK_MIN = 150
CHUNK_MAX = 270
# Hard ceiling — a single sentence longer than this gets force-cut.
CHUNK_HARD_MAX = 350
# Discard chunks shorter than this.
MIN_CHUNK_CHARS = 30

# Sentence boundary: period / ! / ? followed by whitespace or end-of-string,
# but not mid-abbreviation (e.g. "Fig. 1", "U.S.A").
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"\(])|(?<=[.!?])$", re.MULTILINE)


def _clean(text: str) -> str:
    """Collapse excessive whitespace while preserving sentence flow."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Replace single newlines (soft wraps) with a space
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    # Collapse multiple blank lines to one
    text = re.sub(r"\n{2,}", "\n\n", text)
    # Collapse multiple spaces
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def _sentences(text: str) -> list[str]:
    """Split text into sentences."""
    parts = _SENT_SPLIT.split(text)
    return [p.strip() for p in parts if p.strip()]


def _build_chunks(page_text: str, page_num: int) -> list[dict]:
    """Greedily accumulate sentences into chunks of CHUNK_MIN–CHUNK_MAX chars."""
    chunks: list[dict] = []
    idx = 0
    current = ""

    def flush(text: str) -> None:
        nonlocal idx
        text = text.strip()
        if len(text) >= MIN_CHUNK_CHARS:
            chunks.append({"page": page_num, "index": idx, "text": text})
            idx += 1

    for sent in _sentences(page_text):
        # Force-cut a single sentence that is too long on its own
        while len(sent) > CHUNK_HARD_MAX:
            flush(current + " " + sent[:CHUNK_HARD_MAX] if current else sent[:CHUNK_HARD_MAX])
            current = ""
            sent = sent[CHUNK_HARD_MAX:].strip()

        candidate = (current + " " + sent).strip() if current else sent

        if len(candidate) <= CHUNK_MAX:
            current = candidate
            # Close the chunk if we're already in the target range and the
            # next sentence would push us over.
            if len(current) >= CHUNK_MIN:
                # Peek: if adding another sentence would exceed CHUNK_MAX,
                # we'll close here naturally on the next iteration.
                # For now just keep accumulating — closing happens below.
                pass
        else:
            # Adding this sentence would exceed the max.
            if current:
                flush(current)
            current = sent

    flush(current)
    return chunks


def _parse_with_pdfplumber(pdf_path: str) -> list[dict]:
    chunks: list[dict] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            raw = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
            text = _clean(raw)
            if text:
                chunks.extend(_build_chunks(text, page_num))
    return chunks


def _parse_with_pymupdf(pdf_path: str) -> list[dict]:
    chunks: list[dict] = []
    doc = fitz.open(pdf_path)
    try:
        for page_num, page in enumerate(doc, start=1):
            raw = page.get_text("text") or ""
            text = _clean(raw)
            if text:
                chunks.extend(_build_chunks(text, page_num))
    finally:
        doc.close()
    return chunks


def parse_pdf(pdf_path: Union[str, Path]) -> list[dict]:
    """Parse a PDF and return a list of text chunk dicts.

    Args:
        pdf_path: Path to the PDF file (str or Path).

    Returns:
        List of dicts with keys: page (int), index (int), text (str).

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If no text could be extracted.
    """
    path = str(pdf_path)
    if not Path(path).exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    chunks = _parse_with_pdfplumber(path)
    if not chunks:
        # Fallback to PyMuPDF (handles some malformed / scanned PDFs better)
        chunks = _parse_with_pymupdf(path)

    if not chunks:
        raise ValueError(f"No text could be extracted from: {path}")

    return chunks


if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) < 2:
        print("Usage: python pdf_parser.py <path/to/file.pdf> [--json]")
        sys.exit(1)

    target = sys.argv[1]
    as_json = "--json" in sys.argv

    try:
        result = parse_pdf(target)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}")
        sys.exit(1)

    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        lengths = [len(chunk["text"]) for chunk in result]
        avg = sum(lengths) / len(lengths)
        print(f"Extracted {len(result)} chunks from '{target}'")
        print(f"  avg {avg:.0f} chars | min {min(lengths)} | max {max(lengths)}\n")
        for chunk in result:
            preview = chunk["text"][:120].replace("\n", " ")
            print(f"  [P{chunk['page']:>3}-{chunk['index']:>2}] ({len(chunk['text']):>4}c) {preview}")