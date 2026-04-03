"""
LLM — Retrieval-Augmented Generation (RAG) pipeline.

Flow:
    query ──► embed query ──► pgvector cosine search ──► build prompt ──► OpenAI

Public API:
    retrieve(query, document_id, top_k, db_url)  →  list of chunk dicts
    answer(query, document_id, top_k, db_url)    →  str  (LLM answer)
    generate_quiz(document_id, num_q, db_url)    →  list of question dicts
"""

from __future__ import annotations

import os
from typing import List

import psycopg2
from pgvector.psycopg2 import register_vector
from openai import OpenAI

from embedder import embed_chunks

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
TOP_K_DEFAULT = 5

# ---------------------------------------------------------------------------
# Vector retrieval
# ---------------------------------------------------------------------------

def retrieve(
    query: str,
    document_id: int,
    top_k: int = TOP_K_DEFAULT,
    db_url: str | None = None,
) -> List[dict]:
    """Find the top_k most relevant chunks for a query using cosine similarity.

    Args:
        query:       The user's question.
        document_id: Restrict search to this document.
        top_k:       Number of chunks to return.
        db_url:      PostgreSQL DSN. Defaults to DATABASE_URL env var.

    Returns:
        List of dicts: {page, chunk_index, text, score}
        Ordered by relevance (highest score first).
    """
    # Embed the query with the same model used for chunks
    embedded = embed_chunks([{"page": 0, "index": 0, "text": query}])
    query_vec = embedded[0]["embedding"]

    url = db_url or os.environ["DATABASE_URL"]
    conn = psycopg2.connect(url)
    register_vector(conn)

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT page, chunk_index, text,
                       1 - (embedding <=> %s::vector) AS score
                FROM   chunks
                WHERE  document_id = %s
                ORDER  BY embedding <=> %s::vector
                LIMIT  %s
                """,
                (query_vec, document_id, query_vec, top_k),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    return [
        {"page": r[0], "chunk_index": r[1], "text": r[2], "score": float(r[3])}
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Q&A
# ---------------------------------------------------------------------------

def answer(
    query: str,
    document_id: int,
    top_k: int = TOP_K_DEFAULT,
    db_url: str | None = None,
) -> str:
    """Answer a question using retrieved context from the document.

    Args:
        query:       The user's question.
        document_id: The document to search within.
        top_k:       Number of context chunks to use.
        db_url:      PostgreSQL DSN. Defaults to DATABASE_URL env var.

    Returns:
        The LLM's answer as a plain string.
    """
    chunks = retrieve(query, document_id, top_k, db_url)

    if not chunks:
        return "No relevant content found in this document."

    context = "\n\n".join(
        f"[Page {c['page']}] {c['text']}" for c in chunks
    )

    prompt = f"""You are a helpful teaching assistant. Answer the student's question
based only on the provided course material excerpts. If the answer is not in the
material, say so clearly.

--- Course Material ---
{context}
--- End of Material ---

Question: {query}
Answer:"""

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return response.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# Quiz generation
# ---------------------------------------------------------------------------

def generate_quiz(
    document_id: int,
    num_questions: int = 5,
    db_url: str | None = None,
) -> List[dict]:
    """Generate multiple-choice questions from a document.

    Randomly samples chunks and asks the LLM to create questions.

    Args:
        document_id:   The document to generate questions from.
        num_questions: How many questions to generate.
        db_url:        PostgreSQL DSN. Defaults to DATABASE_URL env var.

    Returns:
        List of dicts:
        {
            "question": str,
            "choices":  {"A": str, "B": str, "C": str, "D": str},
            "answer":   str,   # "A" / "B" / "C" / "D"
            "explanation": str
        }
    """
    url = db_url or os.environ["DATABASE_URL"]
    conn = psycopg2.connect(url)

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT text FROM chunks
                WHERE document_id = %s
                ORDER BY RANDOM()
                LIMIT %s
                """,
                (document_id, num_questions * 3),   # sample more, LLM picks best
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return []

    context = "\n\n".join(f"- {r[0]}" for r in rows)

    prompt = f"""You are a professor creating a quiz. Based on the following course material,
generate exactly {num_questions} multiple-choice questions.

Respond ONLY with a JSON array, no markdown, no extra text. Each element must have:
  "question"    : the question text
  "choices"     : {{"A": "...", "B": "...", "C": "...", "D": "..."}}
  "answer"      : one of "A", "B", "C", "D"
  "explanation" : one sentence explaining why the answer is correct

--- Course Material ---
{context}
--- End of Material ---"""

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
        response_format={"type": "json_object"},
    )

    import json
    raw = response.choices[0].message.content.strip()
    data = json.loads(raw)

    # The model may wrap the array in a key
    if isinstance(data, dict):
        data = next(iter(data.values()))

    return data


# ---------------------------------------------------------------------------
# Manual test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python llm.py <document_id> <question>")
        print("       python llm.py <document_id> --quiz [num_questions]")
        sys.exit(1)

    doc_id = int(sys.argv[1])

    if sys.argv[2] == "--quiz":
        num_q = int(sys.argv[3]) if len(sys.argv) > 3 else 3
        print(f"Generating {num_q} quiz questions for document {doc_id}...\n")
        questions = generate_quiz(doc_id, num_q)
        import json
        print(json.dumps(questions, indent=2, ensure_ascii=False))
    else:
        question = " ".join(sys.argv[2:])
        print(f"Q: {question}\n")
        result = answer(question, doc_id)
        print(f"A: {result}")
