# CourseMate — AI-Powered Course Assistant

CourseMate is a full-stack web application that helps students learn more effectively from course materials. Upload a PDF lecture, and CourseMate provides AI-generated summaries, knowledge maps, concept cards, page-by-page explanations, Q&A, and adaptive quizzes.

---

## Features

| Feature | Description |
|---------|-------------|
| **Document Upload** | Upload PDF lecture slides; automatically parsed, chunked, and embedded |
| **Section Summaries** | LLM-generated summaries grouped by page range |
| **Knowledge Map** | Structured outline of the document's key concepts and relationships |
| **Study Mode** | Page-by-page reader with on-demand AI explanation for each page |
| **Concept Cards** | Automatically extracted key terms with definitions, examples, and formulas |
| **Q&A (RAG)** | Ask questions; answers are grounded in the lecture material with source citations |
| **Quiz** | Auto-generated MCQ, short-answer, and calculation questions with AI grading |

---

## Repository Structure

```
EE547-project/
├── backend/                  # FastAPI API + async Worker
│   ├── api/                  # HTTP layer
│   │   ├── main.py           # FastAPI app entry point
│   │   ├── config.py         # Environment settings (pydantic-settings)
│   │   ├── database.py       # SQLAlchemy engine & session
│   │   ├── models.py         # ORM models (mirrors docs/schema.sql)
│   │   ├── schemas.py        # Pydantic request/response schemas
│   │   ├── deps.py           # Dependency injection (DB session, current user)
│   │   ├── security.py       # bcrypt password hashing, JWT sign/verify
│   │   ├── util.py           # Shared helpers
│   │   └── routers/
│   │       ├── auth.py       # POST /auth/register, /auth/login
│   │       ├── courses.py    # Course CRUD
│   │       ├── documents.py  # PDF upload, status, summary, knowledge-map, concepts
│   │       ├── qa.py         # RAG question answering + history
│   │       └── quiz.py       # Quiz generation, submission, results, history
│   ├── worker/               # Background document processing
│   │   ├── main.py           # Entry point (local subprocess or SQS consumer)
│   │   ├── pdf_parser.py     # PDF → text chunks (pdfplumber + PyMuPDF)
│   │   ├── embedder.py       # OpenAI text-embedding-3-small → pgvector
│   │   └── llm.py            # RAG search, quiz generation, summaries, concepts
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/                 # Static HTML/CSS/JS (served by Nginx)
│   ├── index.html            # Login / Register
│   ├── dashboard.html        # Course list
│   ├── course.html           # Course detail: documents, summary, Q&A, quiz
│   ├── css/style.css
│   └── js/api.js             # All API calls encapsulated here
├── docs/
│   ├── schema.sql            # PostgreSQL schema (auto-loaded on first run)
│   └── architecture.md       # System architecture, data flow, design decisions
├── docker-compose.yml        # One-command local + production setup
├── .env.example              # Environment variable template
└── README.md                 # This file
```

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| API | Python 3.11, FastAPI, Uvicorn |
| Database | PostgreSQL 16 + pgvector extension |
| Embeddings | OpenAI `text-embedding-3-small` (1536-dim) |
| LLM | OpenAI `gpt-4o-mini` |
| PDF Processing | pdfplumber, PyMuPDF |
| Auth | JWT (python-jose) + bcrypt |
| Frontend | Vanilla HTML/CSS/JS, marked.js, MathJax |
| Serving | Nginx (frontend), Uvicorn (API) |
| Container | Docker, Docker Compose |

---

## Prerequisites

- Docker and Docker Compose installed
- An OpenAI API key

---

## Quick Start (Local)

### 1. Clone the repository

```bash
git clone https://github.com/jellyfish0619/EE547-project.git
cd EE547-project
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in the required values:

```env
OPENAI_API_KEY=sk-...          # Required
JWT_SECRET=your-secret-key     # Change this in production
DATABASE_URL=postgresql+psycopg2://postgres:password@db:5432/coursemate
```

### 3. Start all services

```bash
docker compose up --build
```

This starts four containers:
- `api` — FastAPI on port 8000
- `worker` — background PDF processor
- `db` — PostgreSQL 16 with pgvector
- `frontend` — Nginx serving static files on port 3000

### 4. Open the application

Navigate to **http://localhost:3000** in your browser.

The API documentation (Swagger UI) is available at **http://localhost:8000/docs**.

---

## Deployment to AWS EC2

### 1. Launch an EC2 instance

- Recommended: **t3.small** (2 vCPU, 2 GB RAM) or larger
- AMI: Ubuntu 22.04 LTS
- Open inbound ports: **22** (SSH), **3000** (frontend), **8000** (API)

### 2. Install Docker on the instance

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-plugin
sudo usermod -aG docker ubuntu
# Log out and back in for group change to take effect
```

### 3. Add swap space (recommended for t3.small)

```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### 4. Clone and configure

```bash
git clone https://github.com/jellyfish0619/EE547-project.git
cd EE547-project
cp .env.example .env
nano .env   # Fill in OPENAI_API_KEY and a strong JWT_SECRET
```

### 5. Update CORS origins

In `backend/api/main.py`, add your EC2 public IP or domain to the `allow_origins` list:

```python
allow_origins=["http://<your-ec2-ip>:3000", "http://localhost:3000"]
```

### 6. Start the application

```bash
docker compose up -d --build
```

### 7. Verify it's running

```bash
docker compose ps
curl http://localhost:8000/health
```

---

## Database Schema

The schema is defined in `docs/schema.sql` and is automatically applied when the PostgreSQL container starts for the first time.

Key tables:

| Table | Description |
|-------|-------------|
| `users` | Email + bcrypt hashed password |
| `courses` | Courses owned by users |
| `documents` | PDF metadata, processing status, cached AI outputs |
| `chunks` | Text chunks with 1536-dim vector embeddings |
| `qa_history` | Q&A logs with source citations |
| `quiz_sessions` | Generated quiz questions (JSONB) |
| `quiz_attempts` | Submitted answers and scores (JSONB) |

To reset the database (e.g., after a schema change):

```bash
docker compose down -v   # -v removes all volumes including pgdata
docker compose up -d --build
```

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | ✅ | — | OpenAI API key for embeddings and LLM |
| `OPENAI_CHAT_MODEL` | | `gpt-4o-mini` | LLM model for Q&A, quiz, summaries |
| `OPENAI_EMBED_MODEL` | | `text-embedding-3-small` | Embedding model |
| `DATABASE_URL` | ✅ | — | SQLAlchemy connection string |
| `JWT_SECRET` | ✅ | — | Secret key for JWT signing |
| `LOCAL_UPLOAD_DIR` | | `/app/data/uploads` | Local PDF storage path |
| `S3_BUCKET_NAME` | | — | Optional: S3 bucket for PDF storage |
| `SQS_QUEUE_URL` | | — | Optional: SQS queue for async processing |
| `AWS_REGION` | | `us-east-1` | AWS region |

---

## API Overview

Full interactive docs available at `http://localhost:8000/docs`.

All endpoints except `/auth/register` and `/auth/login` require:
```
Authorization: Bearer <access_token>
```

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/register` | Create account |
| POST | `/auth/login` | Get access token |
| GET | `/courses` | List courses |
| POST | `/courses` | Create course |
| DELETE | `/courses/{id}` | Delete course |
| POST | `/courses/{id}/documents` | Upload PDF |
| GET | `/documents/{id}/status` | Check processing status |
| GET | `/documents/{id}/summary` | Get section summaries |
| GET | `/documents/{id}/knowledge-map` | Get knowledge map |
| GET | `/documents/{id}/concepts` | Get concept cards |
| GET | `/documents/{id}/pages/{page}/explain` | Explain a specific page |
| DELETE | `/documents/{id}` | Delete document |
| POST | `/courses/{id}/qa` | Ask a question (RAG) |
| GET | `/courses/{id}/qa` | Q&A history |
| DELETE | `/courses/{id}/qa/{qa_id}` | Delete one Q&A record |
| DELETE | `/courses/{id}/qa` | Clear all Q&A history |
| POST | `/courses/{id}/quiz/generate` | Generate quiz |
| POST | `/quiz/{session_id}/submit` | Submit answers |
| GET | `/quiz/{session_id}/result` | Get detailed results |
| GET | `/courses/{id}/quiz/history` | Quiz history |
| DELETE | `/courses/{id}/quiz/{session_id}` | Delete quiz record |

---

## Development Notes

- The worker spawns as a subprocess when SQS is not configured (suitable for single-server deployments)
- Knowledge maps and concept cards are cached in the database after first generation; pass `?regenerate=true` to force regeneration
- Math formulas in quiz questions use LaTeX syntax rendered by MathJax
- The frontend uses ES modules; clear browser cache if JS changes don't appear (`Cmd+Shift+R` on Mac)
