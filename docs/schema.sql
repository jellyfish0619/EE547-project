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
    description TEXT,
    created_at  TIMESTAMP DEFAULT NOW()
);

-- ============================================
-- Documents
-- ============================================
-- status values: pending / processing / ready / failed
CREATE TABLE documents (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    course_id   UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    filename    TEXT NOT NULL,
    s3_key      TEXT NOT NULL,       -- file path in S3
    status      TEXT NOT NULL DEFAULT 'pending',
    summary     TEXT,                -- written by Worker after async generation
    uploaded_at TIMESTAMP DEFAULT NOW()
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

-- ============================================
-- QA History
-- ============================================
-- source_chunks stores referenced chunk metadata, format:
-- [{"filename": "lecture3.pdf", "page_number": 5, "content": "..."}]
CREATE TABLE qa_history (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    course_id     UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    question      TEXT NOT NULL,
    answer        TEXT NOT NULL,
    source_chunks JSONB,
    created_at    TIMESTAMP DEFAULT NOW()
);

-- ============================================
-- Quiz Sessions
-- ============================================
-- questions format:
-- [{"id": 1, "question": "...", "options": ["A","B","C","D"], "answer": "B"}]
-- user_answers format:
-- [{"question_id": 1, "answer": "B"}]
CREATE TABLE quiz_sessions (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    course_id    UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    questions    JSONB NOT NULL,
    user_answers JSONB,
    score        INT,
    created_at   TIMESTAMP DEFAULT NOW()
);

-- ============================================
-- Indexes
-- ============================================

-- Vector similarity search index (IVFFlat, cosine distance)
-- Recommended lists value: total chunks / 10, minimum 10
CREATE INDEX idx_chunks_embedding
ON chunks USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- Indexes for common query patterns
CREATE INDEX idx_chunks_course_id     ON chunks(course_id);
CREATE INDEX idx_chunks_document_id   ON chunks(document_id);
CREATE INDEX idx_documents_course_id  ON documents(course_id);
CREATE INDEX idx_documents_status     ON documents(status);
CREATE INDEX idx_courses_user_id      ON courses(user_id);
CREATE INDEX idx_qa_history_course_id ON qa_history(course_id);
CREATE INDEX idx_quiz_course_id       ON quiz_sessions(course_id);