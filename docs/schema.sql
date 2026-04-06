-- CourseMate Database Schema
-- PostgreSQL 16 + pgvector extension

-- Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------------------
-- Users
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    email       TEXT UNIQUE NOT NULL,
    password    TEXT NOT NULL,           -- bcrypt hash
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Courses
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS courses (
    id          SERIAL PRIMARY KEY,
    owner_id    INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Documents (uploaded PDFs)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
    id          SERIAL PRIMARY KEY,
    course_id   INT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    filename    TEXT NOT NULL,
    s3_key      TEXT,                    -- S3 object key or local pseudo-key
    status      TEXT NOT NULL DEFAULT 'pending',
                                         -- pending | processing | ready | failed
    summary     TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Chunks (text + vector embeddings — written by worker/embedder.py)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chunks (
    id          SERIAL PRIMARY KEY,
    document_id INT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page        INT NOT NULL,            -- 1-based page number
    chunk_index INT NOT NULL,            -- position within the page
    text        TEXT NOT NULL,
    embedding   VECTOR(384),             -- all-MiniLM-L6-v2 output
    UNIQUE (document_id, page, chunk_index)
);

-- ANN index for fast cosine similarity search
CREATE INDEX IF NOT EXISTS chunks_embedding_idx
    ON chunks USING hnsw (embedding vector_cosine_ops);

-- ---------------------------------------------------------------------------
-- Q&A history
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS qa_history (
    id          SERIAL PRIMARY KEY,
    course_id   INT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    user_id     INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    question    TEXT NOT NULL,
    answer      TEXT NOT NULL,
    sources     JSONB NOT NULL DEFAULT '[]',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Quiz sessions (generated questions + correct answers)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS quiz_sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id   INT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    user_id     INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    questions   JSONB NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Quiz attempts (submitted answers / scores)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS quiz_attempts (
    id          SERIAL PRIMARY KEY,
    session_id  UUID NOT NULL REFERENCES quiz_sessions(id) ON DELETE CASCADE,
    course_id   INT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    user_id     INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    score       INT NOT NULL,
    total       INT NOT NULL,
    results     JSONB NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
