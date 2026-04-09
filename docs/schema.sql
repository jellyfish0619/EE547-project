-- ============================================
-- CourseMate Database Schema
-- PostgreSQL 16 + pgvector
-- ============================================

CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================
-- Users
-- ============================================
CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    email       TEXT UNIQUE NOT NULL,
    password    TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- Courses
-- ============================================
CREATE TABLE IF NOT EXISTS courses (
    id          SERIAL PRIMARY KEY,
    owner_id    INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- Documents
-- status: pending / processing / ready / failed
-- ============================================
CREATE TABLE IF NOT EXISTS documents (
    id          SERIAL PRIMARY KEY,
    course_id   INT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    filename    TEXT NOT NULL,
    s3_key      TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',
    summary     TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- Chunks (written by worker/embedder.py)
-- ============================================
CREATE TABLE IF NOT EXISTS chunks (
    id          SERIAL PRIMARY KEY,
    document_id INT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page        INT NOT NULL,
    chunk_index INT NOT NULL,
    text        TEXT NOT NULL,
    embedding   VECTOR(384),
    UNIQUE (document_id, page, chunk_index)
);

-- ============================================
-- QA History
-- ============================================
CREATE TABLE IF NOT EXISTS qa_history (
    id          SERIAL PRIMARY KEY,
    course_id   INT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    user_id     INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    question    TEXT NOT NULL,
    answer      TEXT NOT NULL,
    sources     JSONB NOT NULL DEFAULT '[]',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- Quiz Sessions
-- ============================================
CREATE TABLE IF NOT EXISTS quiz_sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id   INT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    user_id     INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    questions   JSONB NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- Quiz Attempts
-- ============================================
CREATE TABLE IF NOT EXISTS quiz_attempts (
    id          SERIAL PRIMARY KEY,
    session_id  UUID NOT NULL REFERENCES quiz_sessions(id) ON DELETE CASCADE,
    course_id   INT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    user_id     INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    score       INT NOT NULL,
    total       INT NOT NULL,
    results     JSONB NOT NULL DEFAULT '[]',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- Indexes
-- ============================================
CREATE INDEX IF NOT EXISTS idx_chunks_embedding
    ON chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_chunks_document_id  ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_documents_course_id ON documents(course_id);
CREATE INDEX IF NOT EXISTS idx_documents_status    ON documents(status);
CREATE INDEX IF NOT EXISTS idx_courses_owner_id    ON courses(owner_id);
CREATE INDEX IF NOT EXISTS idx_qa_history_course   ON qa_history(course_id);
CREATE INDEX IF NOT EXISTS idx_quiz_course         ON quiz_sessions(course_id);
