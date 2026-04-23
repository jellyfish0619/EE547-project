"""
Embedder — converts text chunks into vector embeddings via OpenAI API,
then stores them in PostgreSQL (pgvector).

Model: text-embedding-3-small  (1536-dim, better quality than local MiniLM)
Cost:  ~$0.00002 / 1K tokens — a 100-page PDF costs < $0.002
"""

from __future__ import annotations

import os
from typing import List

import psycopg2
from pgvector.psycopg2 import register_vector
from openai import OpenAI

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
EMBED_DIM   = 1536   # text-embedding-3-small native dimension
BATCH_SIZE  = 512    # OpenAI accepts up to 2048 inputs per call; 512 is safe

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _client


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

    client = _get_client()
    texts  = [c["text"] for c in chunks]

    # Process in batches to stay within API limits
    vectors: list[list[float]] = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        response = client.embeddings.create(model=EMBED_MODEL, input=batch)
        # Response items are in the same order as input
        vectors.extend([item.embedding for item in response.data])

    for chunk, vec in zip(chunks, vectors):
        chunk["embedding"] = vec

    return chunks


def store_chunks(document_id: int, chunks: List[dict], db_url: str | None = None) -> int:
    """Insert embedded chunks into the database.

    Deletes any existing chunks for document_id before inserting (idempotent).

    Returns:
        Number of rows inserted.
    """
    url = db_url or os.environ["DATABASE_URL"]
    conn = psycopg2.connect(url)
    register_vector(conn)

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))

                if not chunks:
                    return 0

                rows = [
                    (document_id, c["page"], c["index"], c["text"], c["embedding"])
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
    """Convenience wrapper: embed then store in one call."""
    embedded = embed_chunks(chunks)
    return store_chunks(document_id, embedded, db_url)
