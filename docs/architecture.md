# CourseMate — System Architecture

## Overview

CourseMate is a multi-container web application built around a Retrieval-Augmented Generation (RAG) pipeline. Users upload PDF lecture slides; the system parses, embeds, and indexes them so that AI features (Q&A, quiz, summaries, knowledge maps) can work with the actual course material rather than relying on general knowledge alone.

---

## System Components

```
┌─────────────────────────────────────────────────────────────────┐
│                          User Browser                           │
│                  (HTML + CSS + JS, no framework)                │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTP (port 3000)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Nginx (Frontend Container)                  │
│              Serves static files from /frontend                 │
└───────────────────────────┬─────────────────────────────────────┘
                            │ API calls (port 8000)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                   FastAPI (API Container)                       │
│                                                                 │
│  routers/auth.py      → JWT registration & login               │
│  routers/courses.py   → Course CRUD                            │
│  routers/documents.py → PDF upload, status, AI features        │
│  routers/qa.py        → RAG Q&A + history                      │
│  routers/quiz.py      → Quiz generation, grading, history      │
└────────────┬──────────────────────────┬────────────────────────┘
             │ subprocess.Popen         │ SQLAlchemy ORM
             │ (on PDF upload)          ▼
             │              ┌───────────────────────┐
             │              │  PostgreSQL + pgvector │
             │              │                        │
             │              │  users                 │
             │              │  courses               │
             │              │  documents             │
             │              │  chunks (VECTOR 1536)  │
             │              │  qa_history            │
             │              │  quiz_sessions         │
             │              │  quiz_attempts         │
             └──────────────└───────────────────────┘
             ▼                          ▲
┌─────────────────────────────────────────────────────────────────┐
│                   Worker (Worker Container)                     │
│                                                                 │
│  pdf_parser.py  → Extract text chunks from PDF pages           │
│  embedder.py    → Call OpenAI Embeddings API → store vectors   │
│  llm.py         → GPT-4o-mini for summaries, Q&A, quiz, etc.  │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTPS
                            ▼
                  ┌──────────────────────┐
                  │   OpenAI API         │
                  │                      │
                  │  text-embedding-3-   │
                  │  small (embeddings)  │
                  │                      │
                  │  gpt-4o-mini (LLM)   │
                  └──────────────────────┘
```

---

## Data Flow

### 1. PDF Upload & Processing

```
User uploads PDF
      │
      ▼
API saves file to /app/data/uploads
API creates documents record (status=pending)
API spawns worker subprocess
      │
      ▼
Worker: pdf_parser.py
  → pdfplumber extracts text page by page
  → splits into overlapping chunks (~500 tokens each)
      │
      ▼
Worker: embedder.py
  → sends chunks to OpenAI text-embedding-3-small
  → receives 1536-dimensional vectors
  → stores in chunks table (pgvector)
      │
      ▼
Worker: llm.py → update_document_summary()
  → groups pages into sections (3 pages each)
  → GPT generates section-level summaries
  → stores in documents.summary
      │
      ▼
documents.status = "ready"
```

### 2. Q&A (RAG Pipeline)

```
User asks a question
      │
      ▼
API: routers/qa.py
      │
      ▼
llm.py: search_and_answer()
  → embed question with text-embedding-3-small
  → cosine similarity search in pgvector (top-K chunks)
  → build prompt: system + retrieved chunks + question
  → GPT generates answer with source citations
      │
      ▼
Response: { answer, sources: [{ filename, page_number, content }] }
Answer saved to qa_history table
```

### 3. Quiz Generation & Grading

```
User requests quiz (difficulty, num_questions, optional doc filter)
      │
      ▼
llm.py: generate_quiz()
  → fetch top chunks from pgvector
  → GPT generates mixed question types:
      ~50% MCQ  →  local grading (letter match)
      ~25% Short Answer  →  LLM grading
      ~25% Calculation   →  LLM grading
  → questions stored as JSONB in quiz_sessions
      │
      ▼
User submits answers
      │
      ▼
routers/quiz.py: submit()
  → MCQ answers graded instantly (regex letter comparison)
  → Open questions batched → single GPT call → grade_open_answers()
  → Results + score stored in quiz_attempts
```

### 4. On-Demand AI Features (cached)

```
User requests Knowledge Map / Concept Cards
      │
      ▼
API checks documents.knowledge_map / documents.concepts
      │
      ├─ Cached? → return immediately
      │
      └─ Not cached?
            │
            ▼
         llm.py: generate_knowledge_map() / extract_concepts()
           → fetch relevant chunks from pgvector
           → GPT generates structured output
           → stored in documents table
           → returned to user
```

---

## Key Design Decisions

### OpenAI Embeddings over Local Models
The original design used `sentence-transformers/all-MiniLM-L6-v2` (local PyTorch). This was replaced with OpenAI `text-embedding-3-small` for two reasons:
1. **Memory**: PyTorch consumes ~400 MB on load; the OpenAI client uses ~20 MB
2. **Quality**: MTEB benchmark score ~63 vs ~57 for the local model

### pgvector for Vector Search
Embeddings are stored directly in PostgreSQL using the `pgvector` extension. This avoids introducing a separate vector database (Pinecone, Weaviate, etc.) while still supporting efficient approximate nearest-neighbor search via HNSW indexing.

### Subprocess-based Worker
Rather than a persistent worker daemon, the API spawns a Python subprocess per document (`subprocess.Popen`). This keeps the architecture simple for single-server deployments and ensures memory from one document's processing is fully released before the next begins. If SQS is configured, the worker container handles messages instead.

### DB Caching for Expensive Outputs
Knowledge maps and concept cards are expensive to generate (~5–10 seconds). Results are cached in `documents.knowledge_map` (TEXT) and `documents.concepts` (JSONB). Clients can pass `?regenerate=true` to bypass the cache.

### Math in Quiz
LaTeX is used for all mathematical notation in quiz questions and answers. The frontend renders math with MathJax and protects LaTeX expressions from Markdown parsing using a placeholder stash/restore pattern.

---

## Database Schema Summary

```sql
users         (id, email, password, created_at)
courses       (id, owner_id, name, description, created_at)
documents     (id, course_id, filename, s3_key, status,
               summary, knowledge_map, concepts, created_at)
chunks        (id, document_id, page, chunk_index, text,
               embedding VECTOR(1536))
qa_history    (id, course_id, user_id, question, answer,
               sources JSONB, created_at)
quiz_sessions (id UUID, course_id, user_id, questions JSONB, created_at)
quiz_attempts (id, session_id, course_id, user_id, score, total,
               results JSONB, created_at)
```

Indexes:
- `chunks.embedding` — HNSW index for fast cosine similarity search
- `chunks.document_id`, `documents.course_id`, `documents.status` — query performance

---

## Deployment Architecture (AWS EC2)

```
┌────────────────────────────────────────┐
│              AWS EC2 (t3.small)        │
│                                        │
│  ┌──────────┐  ┌──────────┐           │
│  │ frontend │  │   api    │ :8000      │
│  │  nginx   │  │ fastapi  │           │
│  │  :3000   │  └────┬─────┘           │
│  └──────────┘       │                 │
│                 ┌───┴──────┐          │
│                 │  worker  │          │
│                 └───┬──────┘          │
│                     │                 │
│               ┌─────┴──────┐          │
│               │    db      │          │
│               │ postgres + │          │
│               │  pgvector  │          │
│               └────────────┘          │
│                                        │
│  Volumes:                              │
│    pgdata    → database persistence    │
│    uploads   → PDF file storage        │
└────────────────────────────────────────┘
                    │
                    │ HTTPS
                    ▼
           OpenAI API (external)
```

All four services run as Docker containers orchestrated by Docker Compose. The `uploads` volume is shared between the `api` and `worker` containers so the worker can access PDFs saved by the API.
