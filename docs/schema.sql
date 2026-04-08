-- ============================================
-- CourseMate Database Schema
-- PostgreSQL 16 + pgvector
-- ============================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================
-- Users
-- ============================================
CREATE TABLE users (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email            TEXT UNIQUE NOT NULL,
    hashed_password  TEXT NOT NULL,
    created_at       TIMESTAMP DEFAULT NOW()
);

-- ============================================
-- Courses
-- ============================================
CREATE TABLE courses (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- Documents
-- ============================================
-- status values: pending / processing / ready / failed
CREATE TABLE documents (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    course_id   UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    filename    TEXT NOT NULL,
    s3_key      TEXT,                    -- S3 object key or local pseudo-key
    status      TEXT NOT NULL DEFAULT 'pending',
                                         -- pending | processing | ready | failed
    summary     TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- Chunks (core table)
-- ============================================
-- course_id is stored redundantly to avoid JOIN with documents during vector search
CREATE TABLE chunks (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id  UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    course_id    UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    chunk_index  INT NOT NULL,
    content      TEXT NOT NULL,
    embedding    vector(384),        -- all-MiniLM-L6-v2 outputs 384 dimensions
    page_number  INT
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
