# CourseMate — Backend

FastAPI HTTP API + async document processing Worker.

---

## Directory Structure

```
backend/
├── api/                      # HTTP API (PYTHONPATH=/app inside container)
│   ├── main.py               # FastAPI app: mounts routers, configures CORS
│   ├── config.py             # Pydantic Settings — reads from .env
│   ├── database.py           # SQLAlchemy engine, SessionLocal, Base
│   ├── models.py             # ORM models (must stay in sync with docs/schema.sql)
│   ├── schemas.py            # Pydantic request/response models
│   ├── deps.py               # get_db(), get_current_user() dependencies
│   ├── security.py           # Password hashing (bcrypt), JWT sign/verify
│   ├── util.py               # Shared helpers (e.g. public_document_status)
│   └── routers/
│       ├── auth.py           # /auth/register, /auth/login, /auth/me
│       ├── courses.py        # Course CRUD
│       ├── documents.py      # PDF upload, status, summary, knowledge-map, concepts, explain
│       ├── qa.py             # RAG Q&A + history management
│       └── quiz.py           # Quiz generation, submission, grading, history
├── worker/
│   ├── main.py               # Entry point: --local mode or SQS consumer loop
│   ├── pdf_parser.py         # PDF → list of {page, index, text} chunks
│   ├── embedder.py           # Calls OpenAI Embeddings API → stores in pgvector
│   └── llm.py                # All LLM logic: RAG, quiz, summaries, concepts, knowledge map
├── Dockerfile
└── requirements.txt
```

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | ✅ | SQLAlchemy DSN. API uses `postgresql+psycopg2://...`; worker normalizes to `postgresql://...` automatically |
| `JWT_SECRET` | ✅ | Secret key for signing JWTs. Must be changed in production |
| `OPENAI_API_KEY` | ✅ | Used for embeddings, Q&A, quiz generation, summaries, and concept extraction |
| `OPENAI_CHAT_MODEL` | | LLM model name, default `gpt-4o-mini` |
| `OPENAI_EMBED_MODEL` | | Embedding model, default `text-embedding-3-small` |
| `LOCAL_UPLOAD_DIR` | | Where uploaded PDFs are stored, default `/app/data/uploads` |
| `S3_BUCKET_NAME` | | If set, PDFs are stored in S3 instead of local disk |
| `SQS_QUEUE_URL` | | If set, worker is triggered via SQS messages; otherwise API spawns a local subprocess |
| `AWS_REGION` | | AWS region, default `us-east-1` |

---

## Running Locally (without Docker)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Set environment variables
export DATABASE_URL="postgresql+psycopg2://postgres:password@localhost:5432/coursemate"
export OPENAI_API_KEY="sk-..."
export JWT_SECRET="dev-secret"

# Run API
PYTHONPATH=. uvicorn api.main:app --reload --port 8000

# Run worker (separate terminal)
PYTHONPATH=. python worker/main.py
```

Health check: `GET http://localhost:8000/health`

---

## Document Processing Pipeline

When a PDF is uploaded:

1. **API** saves the file to `LOCAL_UPLOAD_DIR` and creates a `documents` record with `status=pending`
2. **API** spawns `worker/main.py --local <path> <doc_id>` as a subprocess
3. **Worker** parses the PDF into text chunks (`pdf_parser.py`)
4. **Worker** calls OpenAI Embeddings API to embed each chunk, stores in `chunks` table (`embedder.py`)
5. **Worker** sets `status=ready`
6. **Worker** generates a section-level summary using GPT and stores in `documents.summary`

Knowledge maps and concept cards are generated on first access and cached in `documents.knowledge_map` and `documents.concepts`.

---

## API Reference

### Auth — `routers/auth.py`

#### `POST /auth/register`
```json
Request:  { "email": "user@example.com", "password": "secret" }
Response: { "access_token": "...", "token_type": "bearer" }
```

#### `POST /auth/login`
```json
Request:  { "email": "user@example.com", "password": "secret" }
Response: { "access_token": "...", "token_type": "bearer" }
```

#### `GET /auth/me` 🔒
```json
Response: { "id": 1, "email": "user@example.com", "created_at": "..." }
```

---

### Courses — `routers/courses.py`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/courses` | List all courses for current user |
| POST | `/courses` | Create a course (`name`, `description`) |
| GET | `/courses/{course_id}` | Course detail + document list |
| DELETE | `/courses/{course_id}` | Delete course and all associated data |

---

### Documents — `routers/documents.py`

#### `POST /courses/{course_id}/documents` 🔒
Upload a PDF. Accepts `multipart/form-data` with:
- `file` — the PDF file
- `auto_summary` — boolean, default `true`

Returns `202 Accepted` with `{ "id": ..., "filename": ..., "status": "pending" }`.

#### `GET /documents/{doc_id}/status` 🔒
Poll until `status` is `ready` or `failed`.

#### `GET /documents/{doc_id}/summary` 🔒
Returns the section-level summary (requires `status=ready`).

#### `GET /documents/{doc_id}/knowledge-map` 🔒
Returns a structured Markdown outline. Generated on first call and cached.
Pass `?regenerate=true` to force regeneration.

#### `GET /documents/{doc_id}/concepts` 🔒
Returns a JSON array of concept objects:
```json
[
  {
    "term": "Gradient Descent",
    "definition": "...",
    "example": "...",
    "formula": "w = w - α∇L",
    "related": ["Learning Rate", "Loss Function"]
  }
]
```
Cached after first generation. Pass `?regenerate=true` to refresh.

#### `GET /documents/{doc_id}/pages/{page}/explain` 🔒
Returns an AI explanation of a specific page:
```json
{ "page": 5, "max_page": 30, "raw": "...", "explanation": "..." }
```

#### `DELETE /documents/{doc_id}` 🔒
Deletes the document and all associated chunks.

---

### Q&A — `routers/qa.py`

#### `POST /courses/{course_id}/qa` 🔒
```json
Request:  { "question": "What is backpropagation?", "document_id": 1 }
Response: {
  "answer": "...",
  "sources": [
    { "filename": "lecture5.pdf", "page_number": 12, "content": "..." }
  ]
}
```
`document_id` is optional. Omit to search across all ready documents in the course.

If the topic is not found in the lecture materials, the answer will be prefixed with a warning note.

#### `GET /courses/{course_id}/qa` 🔒
Returns Q&A history for the current user in the course.

#### `DELETE /courses/{course_id}/qa/{qa_id}` 🔒
Delete a single Q&A record.

#### `DELETE /courses/{course_id}/qa` 🔒
Clear all Q&A history for the course.

---

### Quiz — `routers/quiz.py`

#### `POST /courses/{course_id}/quiz/generate` 🔒
```json
Request: {
  "num_questions": 5,
  "document_id": null,
  "difficulty": "medium"
}
```
- `difficulty`: `"easy"` | `"medium"` | `"hard"`
- Returns `session_id` (UUID) and `questions` array

Question types:
- `mcq` — 4-choice multiple choice, graded locally
- `short_answer` — open text, graded by LLM
- `calculation` — math problem, graded by LLM

#### `POST /quiz/{session_id}/submit` 🔒
```json
Request: {
  "answers": [
    { "question_id": 1, "answer": "B" },
    { "question_id": 2, "answer": "The derivative of x² is 2x" }
  ]
}
```
MCQ answers are graded instantly. Short answer and calculation answers are sent to GPT for grading in a single batch call.

#### `GET /quiz/{session_id}/result` 🔒
Detailed results including per-question feedback, correct answers, and explanations.

#### `GET /courses/{course_id}/quiz/history` 🔒
List of past quiz attempts with score and timestamp.

#### `DELETE /courses/{course_id}/quiz/{session_id}` 🔒
Delete a quiz attempt record.

---

## LLM Functions (`worker/llm.py`)

| Function | Description |
|----------|-------------|
| `search_and_answer(question, course_id, db, document_id)` | RAG: embed question → cosine search → GPT answer |
| `generate_quiz(course_id, db, num_questions, document_id, difficulty)` | Generate mixed-type quiz questions from chunks |
| `grade_open_answers(items)` | Batch-grade short answer and calculation responses |
| `update_document_summary(document_id, db_url)` | Generate section-level summaries and store |
| `generate_knowledge_map(document_id, db_url)` | Generate structured Markdown knowledge outline |
| `explain_page(document_id, page, db_url)` | Explain a single page with context |
| `extract_concepts(document_id, db_url)` | Extract key terms as structured JSON |
