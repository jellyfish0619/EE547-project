"""
LLM — Retrieval-Augmented Generation (RAG).

API layer calls:
    search_and_answer(question, course_id, db, document_id=None)
    generate_quiz(course_id, db, num_questions=5, document_id=None)
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import psycopg2
from openai import OpenAI
from pgvector.psycopg2 import register_vector
from sqlalchemy.orm import Session

CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
TOP_K_DEFAULT = 5


def _session_dsn(db: Session) -> str:
    u = db.get_bind().url
    s = u.render_as_string(hide_password=False)
    for prefix in ("postgresql+psycopg2://", "postgresql+psycopg://"):
        if s.startswith(prefix):
            return "postgresql://" + s[len(prefix) :]
    return s


def _openai_client() -> OpenAI:
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def update_document_summary(document_id: int, db_url: str | None = None) -> None:
    """Write an LLM summary into documents.summary (best-effort)."""
    if not os.getenv("OPENAI_API_KEY"):
        return
    url = db_url or os.environ["DATABASE_URL"]
    conn = psycopg2.connect(url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT text FROM chunks
                WHERE document_id = %s
                ORDER BY page, chunk_index
                LIMIT 40
                """,
                (document_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    if not rows:
        return
    excerpt = "\n".join(r[0] for r in rows if r[0])[:12000]
    prompt = (
        "Summarize the following course material in 3–6 concise sentences "
        "for a student. Focus on main topics and definitions.\n\n---\n"
        f"{excerpt}\n---"
    )
    try:
        client = _openai_client()
        response = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        summary = (response.choices[0].message.content or "").strip()
    except Exception:
        return
    if not summary:
        return
    conn = psycopg2.connect(url)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE documents SET summary = %s WHERE id = %s",
                    (summary, document_id),
                )
    finally:
        conn.close()


def search_and_answer(
    question: str,
    course_id: str,
    db: Session,
    document_id: str | None = None,
    top_k: int = TOP_K_DEFAULT,
) -> dict[str, Any]:
    """
    Returns:
        {"answer": str, "sources": [{"filename", "page_number", "content"}]}
    """
    from worker.embedder import embed_chunks

    cid = int(course_id)
    did = int(document_id) if document_id else None

    embedded = embed_chunks([{"page": 0, "index": 0, "text": question}])
    query_vec = embedded[0]["embedding"]

    dsn = _session_dsn(db)
    conn = psycopg2.connect(dsn)
    register_vector(conn)
    try:
        with conn.cursor() as cur:
            if did is not None:
                cur.execute(
                    """
                    SELECT c.page, c.chunk_index, c.text, d.filename,
                           1 - (c.embedding <=> %s::vector) AS score
                    FROM chunks c
                    JOIN documents d ON d.id = c.document_id
                    WHERE d.course_id = %s AND d.id = %s AND d.status = 'ready'
                    ORDER BY c.embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (query_vec, cid, did, query_vec, top_k),
                )
            else:
                cur.execute(
                    """
                    SELECT c.page, c.chunk_index, c.text, d.filename,
                           1 - (c.embedding <=> %s::vector) AS score
                    FROM chunks c
                    JOIN documents d ON d.id = c.document_id
                    WHERE d.course_id = %s AND d.status = 'ready'
                    ORDER BY c.embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (query_vec, cid, query_vec, top_k),
                )
            rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return {
            "answer": "No relevant content found in the course materials.",
            "sources": [],
        }

    context = "\n\n".join(f"[{r[3]} page {r[0]}]\n{r[2]}" for r in rows)
    sources = [
        {"filename": r[3], "page_number": int(r[0]), "content": r[2]}
        for r in rows
    ]

    prompt = f"""You are a helpful teaching assistant. Answer the student's question
based only on the provided course material excerpts. If the answer is not in the
material, say so clearly.

--- Course Material ---
{context}
--- End of Material ---

Question: {question}
Answer:"""

    client = _openai_client()
    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    answer = (response.choices[0].message.content or "").strip()
    return {"answer": answer, "sources": sources}


def _normalize_quiz_questions(raw: Any, num_questions: int) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        raw = raw.get("questions") or raw.get("quiz") or next(iter(raw.values()), [])
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for i, item in enumerate(raw[:num_questions], start=1):
        if not isinstance(item, dict):
            continue
        qid = int(item.get("id", i))
        qtext = str(item.get("question", "")).strip()
        opts = item.get("options")
        if isinstance(opts, dict):
            options = [
                f"A. {opts.get('A', '')}".strip(),
                f"B. {opts.get('B', '')}".strip(),
                f"C. {opts.get('C', '')}".strip(),
                f"D. {opts.get('D', '')}".strip(),
            ]
        elif isinstance(opts, list):
            options = [str(x) for x in opts]
        else:
            options = []
        ans = str(item.get("answer", "")).strip().upper()
        m = re.match(r"[A-D]", ans)
        ans = m.group(0) if m else "A"
        if len(options) < 4:
            continue
        out.append(
            {
                "id": qid,
                "question": qtext,
                "options": options[:4],
                "answer": ans,
            }
        )
    return out


def generate_quiz(
    course_id: str,
    db: Session,
    num_questions: int = 5,
    document_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Returns:
        [{"id": int, "question": str, "options": list[str], "answer": str}]
    """
    cid = int(course_id)
    did = int(document_id) if document_id else None

    dsn = _session_dsn(db)
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            if did is not None:
                cur.execute(
                    """
                    SELECT c.text FROM chunks c
                    JOIN documents d ON d.id = c.document_id
                    WHERE d.course_id = %s AND d.id = %s AND d.status = 'ready'
                    ORDER BY RANDOM()
                    LIMIT %s
                    """,
                    (cid, did, max(num_questions * 3, 5)),
                )
            else:
                cur.execute(
                    """
                    SELECT c.text FROM chunks c
                    JOIN documents d ON d.id = c.document_id
                    WHERE d.course_id = %s AND d.status = 'ready'
                    ORDER BY RANDOM()
                    LIMIT %s
                    """,
                    (cid, max(num_questions * 3, 5)),
                )
            rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return []

    context = "\n\n".join(f"- {r[0]}" for r in rows if r[0])
    prompt = f"""You are a professor creating a quiz. Based on the following course material,
create exactly {num_questions} multiple-choice questions with four options each.

Respond ONLY with JSON (no markdown) using this shape:
{{"questions": [
  {{
    "id": 1,
    "question": "question text",
    "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
    "answer": "B"
  }}
]}}

The "answer" field must be exactly one letter: A, B, C, or D.

--- Course Material ---
{context}
--- End of Material ---"""

    client = _openai_client()
    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
        response_format={"type": "json_object"},
    )
    raw_text = (response.choices[0].message.content or "").strip()
    data = json.loads(raw_text)
    return _normalize_quiz_questions(data, num_questions)


# --- CLI ---
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print(
            "Usage: DATABASE_URL=... OPENAI_API_KEY=... "
            "python llm.py <course_id> <question>"
        )
        sys.exit(1)

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    eng = create_engine(os.environ["DATABASE_URL"])
    Sess = sessionmaker(bind=eng)
    s = Sess()
    cid = sys.argv[1]
    q = " ".join(sys.argv[2:])
    print(json.dumps(search_and_answer(q, cid, s), indent=2, ensure_ascii=False))
