"""
Embedder — converts text chunks into vector embeddings and stores them in PostgreSQL (pgvector).

Pipeline:
    chunks (from pdf_parser) ──► embed_chunks() ──► store_chunks()

Each chunk dict is extended with an "embedding" key (list[float]) after embed_chunks().

Model: all-MiniLM-L6-v2  (384-dim, fast, runs on CPU, ~80 MB)
"""

from __future__ import annotations

import os
from typing import List

import psycopg2
from pgvector.psycopg2 import register_vector
from sentence_transformers import SentenceTransformer

# ---------------------------------------------------------------------------
# Model (lazy singleton — loaded once per process)
# ---------------------------------------------------------------------------

_MODEL: SentenceTransformer | None = None
MODEL_NAME = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2")
EMBED_DIM = 384  # dimension for all-MiniLM-L6-v2


def _get_model() -> SentenceTransformer:
    global _MODEL
    if _MODEL is None:
        _MODEL = SentenceTransformer(MODEL_NAME)
    return _MODEL


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def embed_chunks(chunks: List[dict]) -> List[dict]:
    """Add an 'embedding' field (list[float]) to each chunk dict.

    Args:
        chunks: Output of pdf_parser.parse_pdf() — list of
                {"page": int, "index": int, "text": str}.

    Returns:
        Same list with each dict extended by {"embedding": list[float]}.
    """
    if not chunks:
        return chunks

    model = _get_model()
    texts = [c["text"] for c in chunks]

    # batch encode; normalize=True gives cosine-comparable unit vectors
    vectors = model.encode(texts, batch_size=64, normalize_embeddings=True)

    for chunk, vec in zip(chunks, vectors):
        chunk["embedding"] = vec.tolist()

    return chunks


def store_chunks(document_id: int, chunks: List[dict], db_url: str | None = None) -> int:
    """Insert embedded chunks into the database.

    Requires the 'chunks' table to exist (see docs/schema.sql).
    Deletes any existing chunks for document_id before inserting,
    so this function is safely re-entrant (re-processing the same document).

    Args:
        document_id: FK to the documents table.
        chunks:      Output of embed_chunks() — must have "embedding" key.
        db_url:      PostgreSQL DSN. Defaults to DATABASE_URL env var.

    Returns:
        Number of rows inserted.
    """
    url = db_url or os.environ["DATABASE_URL"]
    conn = psycopg2.connect(url)
    register_vector(conn)

    try:
        with conn:
            with conn.cursor() as cur:
                # Remove stale data for this document (idempotent re-runs)
                cur.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))

                if not chunks:
                    return 0

                rows = [
                    (
                        document_id,
                        c["page"],
                        c["index"],
                        c["text"],
                        c["embedding"],
                    )
                    for c in chunks
                ]

                cur.executemany(
                    """
                    INSERT INTO chunks (document_id, page, chunk_index, text, embedding)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    rows,
                )
                return len(rows)
    finally:
        conn.close()


def embed_and_store(document_id: int, chunks: List[dict], db_url: str | None = None) -> int:
    """Convenience wrapper: embed then store in one call.

    Returns:
        Number of chunks stored.
    """
    embedded = embed_chunks(chunks)
    return store_chunks(document_id, embedded, db_url)


# ---------------------------------------------------------------------------
# Manual test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import json

    sample = [
        {"page": 1, "index": 0, "text": "This is the first chunk of text from the PDF."},
        {"page": 1, "index": 1, "text": "Another chunk with different content about machine learning."},
        {"page": 2, "index": 0, "text": "A third chunk on page two discussing neural networks."},
    ]

    print(f"Embedding {len(sample)} sample chunks with model '{MODEL_NAME}'...")
    result = embed_chunks(sample)

    for r in result:
        vec_preview = r["embedding"][:6]
        print(f"  [P{r['page']}-{r['index']}] dim={len(r['embedding'])}  "
              f"first 6 values: {[round(v, 4) for v in vec_preview]}")

    if "--store" in sys.argv:
        doc_id = int(sys.argv[sys.argv.index("--store") + 1])
        stored = store_chunks(doc_id, result)
        print(f"\nStored {stored} chunks for document_id={doc_id}")
