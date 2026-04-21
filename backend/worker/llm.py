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


def _strip_code_fence(text: str) -> str:
    """Remove leading/trailing markdown code fences that LLMs sometimes add."""
    text = text.strip()
    # Remove opening fence (```markdown, ```md, ``` etc.)
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
    # Remove closing fence
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def update_document_summary(document_id: int, db_url: str | None = None) -> None:
    """Write a sectioned LLM summary into documents.summary (best-effort)."""
    if not os.getenv("OPENAI_API_KEY"):
        return
    url = db_url or os.environ["DATABASE_URL"]
    conn = psycopg2.connect(url)
    try:
        with conn.cursor() as cur:
            # Group chunks by page sections (every 3 pages = 1 section)
            cur.execute(
                """
                SELECT page, string_agg(text, ' ' ORDER BY chunk_index) as page_text
                FROM chunks
                WHERE document_id = %s
                GROUP BY page
                ORDER BY page
                """,
                (document_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return

    # Build sections of ~3 pages each
    section_size = 3
    sections = []
    for i in range(0, len(rows), section_size):
        batch = rows[i:i + section_size]
        pages = [r[0] for r in batch]
        text = " ".join(r[1] for r in batch if r[1])[:3000]
        sections.append((pages, text))

    section_summaries = []
    client = _openai_client()
    for pages, text in sections:
        page_label = f"p.{pages[0]}" if len(pages) == 1 else f"p.{pages[0]}–{pages[-1]}"
        prompt = (
            f"Summarize the following course content from {page_label} in 2–3 sentences. "
            "Focus on the main concepts introduced. Use LaTeX for math (\\(formula\\)).\n\n"
            f"---\n{text}\n---"
        )
        try:
            resp = client.chat.completions.create(
                model=CHAT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            s = (resp.choices[0].message.content or "").strip()
            if s:
                section_summaries.append(f"**{page_label}**: {s}")
        except Exception:
            continue

    if not section_summaries:
        return

    summary = "\n\n".join(section_summaries)

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
        context = "(No course material available.)"
        sources = []
    else:
        context = "\n\n".join(f"[{r[3]} page {r[0]}]\n{r[2]}" for r in rows)
        sources = [
            {"filename": r[3], "page_number": int(r[0]), "content": r[2]}
            for r in rows
        ]

    prompt = f"""You are a helpful teaching assistant for a university course.

Use the provided course material excerpts as your primary source.
- If the answer is clearly covered in the material, answer from it directly.
- If the answer is NOT in the material (or only partially covered), still answer the question using your general knowledge, but begin your response with: "⚠️ This topic is not covered in the lecture materials. Here is a general explanation:"

Always give a helpful, accurate answer. Use LaTeX notation for math (e.g. \\(Ax = b\\)).

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


def generate_knowledge_map(document_id: int, db_url: str | None = None) -> str:
    """Generate a structured knowledge outline for a document."""
    url = db_url or os.environ["DATABASE_URL"]
    conn = psycopg2.connect(url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT text FROM chunks
                WHERE document_id = %s
                ORDER BY page, chunk_index
                LIMIT 80
                """,
                (document_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return "No content available."

    excerpt = "\n".join(r[0] for r in rows if r[0])[:16000]
    prompt = f"""You are an expert academic tutor. Analyze the following course material and produce a detailed **knowledge map** (structured outline) in this exact format:

## Overview
One sentence describing what this document is about.

## Knowledge Structure
### 1. [Main Topic]
- **Core concept**: brief explanation
- **Key points**: bullet list
- Related formula/theorem if any (use LaTeX: \\(formula\\))

### 2. [Main Topic]
...

## Key Formulas & Definitions
| Term | Definition |
|------|-----------|
| ... | ... |

## Concept Relationships
Brief description of how the main topics connect to each other.

Be thorough. Use LaTeX for all math. Do NOT wrap output in code fences.

--- Course Material ---
{excerpt}
--- End ---"""

    client = _openai_client()
    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return _strip_code_fence(response.choices[0].message.content or "")


def explain_page(document_id: int, page: int, db_url: str | None = None) -> dict[str, Any]:
    """Return the raw text of a page and an AI explanation of it."""
    url = db_url or os.environ["DATABASE_URL"]
    conn = psycopg2.connect(url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT text FROM chunks
                WHERE document_id = %s AND page = %s
                ORDER BY chunk_index
                """,
                (document_id, page),
            )
            rows = cur.fetchall()
            # Total pages
            cur.execute(
                "SELECT COALESCE(MAX(page), 0) FROM chunks WHERE document_id = %s",
                (document_id,),
            )
            max_page = cur.fetchone()[0]
    finally:
        conn.close()

    page_text = "\n".join(r[0] for r in rows if r[0])
    if not page_text.strip():
        return {"page": page, "max_page": max_page, "raw": "", "explanation": "This page has no extractable text."}

    prompt = f"""You are a university professor explaining lecture material to a student.

For the following page content:
1. **Summary** – What is this page about? (2-3 sentences)
2. **Key Concepts** – List and briefly explain each important concept/term
3. **Formulas & Theorems** – List any formulas or theorems with explanation (use LaTeX: \\(formula\\))
4. **Why It Matters** – How does this connect to the bigger picture?
5. **Common Confusion** – What do students often misunderstand here?

Be concise but complete. Use Markdown and LaTeX for math.

--- Page {page} Content ---
{page_text}
--- End ---"""

    client = _openai_client()
    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    explanation = _strip_code_fence(response.choices[0].message.content or "")
    return {"page": page, "max_page": max_page, "raw": page_text, "explanation": explanation}


def extract_concepts(document_id: int, db_url: str | None = None) -> list[dict[str, Any]]:
    """Extract key concepts from a document and return flashcard-style data."""
    url = db_url or os.environ["DATABASE_URL"]
    conn = psycopg2.connect(url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT text FROM chunks
                WHERE document_id = %s
                ORDER BY page, chunk_index
                LIMIT 60
                """,
                (document_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return []

    excerpt = "\n".join(r[0] for r in rows if r[0])[:14000]
    prompt = f"""Extract the most important concepts, terms, and theorems from the following course material.

Return ONLY valid JSON (no markdown) with this shape:
{{
  "concepts": [
    {{
      "term": "concept name",
      "definition": "clear, concise definition (1-2 sentences)",
      "example": "a concrete example or application (optional, can be empty string)",
      "formula": "LaTeX formula if applicable, else empty string",
      "related": ["related term 1", "related term 2"]
    }}
  ]
}}

Extract 10-20 concepts. Focus on terms a student must know to pass an exam.

--- Course Material ---
{excerpt}
--- End ---"""

    client = _openai_client()
    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    raw = (response.choices[0].message.content or "").strip()
    try:
        data = json.loads(raw)
        return data.get("concepts", [])
    except Exception:
        return []


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
        qtype = str(item.get("type", "mcq")).strip().lower()
        if qtype not in ("mcq", "short_answer", "calculation"):
            qtype = "mcq"
        qtext = str(item.get("question", "")).strip()
        explanation = str(item.get("explanation", "")).strip()

        if qtype == "mcq":
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
            if len(options) < 4:
                continue
            ans = str(item.get("answer", "")).strip().upper()
            m = re.match(r"[A-D]", ans)
            ans = m.group(0) if m else "A"
        else:
            options = []
            ans = str(item.get("answer", "")).strip()

        out.append({
            "id": qid,
            "type": qtype,
            "question": qtext,
            "options": options[:4] if qtype == "mcq" else [],
            "answer": ans,
            "explanation": explanation,
        })
    return out


def generate_quiz(
    course_id: str,
    db: Session,
    num_questions: int = 5,
    document_id: str | None = None,
    difficulty: str = "medium",
) -> list[dict[str, Any]]:
    """
    Returns mixed question types:
    [{"id", "type", "question", "options", "answer", "explanation"}]
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
                    (cid, did, max(num_questions * 4, 10)),
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
                    (cid, max(num_questions * 4, 10)),
                )
            rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return []

    # Distribute question types: ~50% MCQ, ~25% short_answer, ~25% calculation
    n_mcq = max(1, round(num_questions * 0.5))
    n_short = max(1, round(num_questions * 0.25))
    n_calc = num_questions - n_mcq - n_short

    difficulty_guide = {
        "easy":   "Focus on definitions, basic concepts, and direct recall. Calculations should be straightforward with small integers.",
        "medium": "Mix concept understanding with moderate calculations. Require application of formulas. Some multi-step problems.",
        "hard":   "Emphasize deep understanding, proof-style reasoning, and complex multi-step calculations. Tricky edge cases welcome.",
    }.get(difficulty, "medium")

    context = "\n\n".join(f"- {r[0]}" for r in rows if r[0])
    prompt = f"""You are a university professor creating a **{difficulty.upper()}** difficulty exam. Based on the course material below, generate exactly {num_questions} questions with this distribution:
- {n_mcq} multiple-choice questions (type: "mcq")
- {n_short} short-answer questions (type: "short_answer")
- {n_calc} calculation/derivation questions (type: "calculation")

Difficulty guidance ({difficulty}): {difficulty_guide}

Rules:
- MCQ must have exactly 4 options labeled "A. ...", "B. ...", "C. ...", "D. ..." and answer is one letter A-D
- Short-answer: student writes 1-3 sentences; provide a concise reference answer
- Calculation: student shows work; provide full step-by-step solution as the answer
- Every question MUST have a detailed "explanation" field explaining why the answer is correct
- Use LaTeX for ALL math: inline \\(formula\\), display \\[formula\\]
- Do NOT wrap output in code fences

Respond ONLY with valid JSON:
{{
  "questions": [
    {{
      "id": 1,
      "type": "mcq",
      "question": "question text",
      "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
      "answer": "B",
      "explanation": "B is correct because..."
    }},
    {{
      "id": 2,
      "type": "short_answer",
      "question": "question text",
      "options": [],
      "answer": "reference answer (1-3 sentences)",
      "explanation": "detailed explanation..."
    }},
    {{
      "id": 3,
      "type": "calculation",
      "question": "question text with specific numbers",
      "options": [],
      "answer": "step-by-step solution with final answer",
      "explanation": "key insight and method used..."
    }}
  ]
}}

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


def grade_open_answers(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Grade short_answer and calculation questions using LLM.
    items: [{"question_id", "type", "question", "reference_answer", "user_answer"}]
    Returns: [{"question_id", "correct", "feedback"}]
    """
    if not items:
        return []

    items_text = json.dumps(items, ensure_ascii=False, indent=2)
    prompt = f"""You are grading student answers for a university exam. For each item below, evaluate the student's answer against the reference answer.

Be fair but academically rigorous:
- "correct": true if the student demonstrates understanding of the core concept (allow different phrasing/notation)
- For calculation questions: correct only if the final answer is right (partial work shown is noted in feedback)
- "feedback": 1-2 sentences explaining what was right/wrong and what the key insight is

Return ONLY valid JSON (no markdown):
{{
  "grades": [
    {{
      "question_id": <int>,
      "correct": <bool>,
      "feedback": "<feedback string>"
    }}
  ]
}}

Items to grade:
{items_text}"""

    client = _openai_client()
    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    raw = (response.choices[0].message.content or "").strip()
    try:
        data = json.loads(raw)
        return data.get("grades", [])
    except Exception:
        return [{"question_id": it["question_id"], "correct": False, "feedback": "Grading error."} for it in items]


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
