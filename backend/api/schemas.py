from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# --- Auth ---
class RegisterRequest(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    email: str
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Courses ---
class CourseCreate(BaseModel):
    name: str
    description: str = ""


class CourseOut(BaseModel):
    id: int
    name: str
    description: str
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentBrief(BaseModel):
    id: int
    filename: str
    status: str

    model_config = {"from_attributes": True}


class CourseDetailOut(CourseOut):
    documents: list[DocumentBrief]


class MessageOut(BaseModel):
    message: str


# --- Documents ---
class DocumentCreatedOut(BaseModel):
    id: int
    filename: str
    status: str


class DocumentListOut(BaseModel):
    id: int
    filename: str
    status: str
    uploaded_at: datetime

    model_config = {"from_attributes": True}


class DocumentStatusOut(BaseModel):
    id: int
    filename: str
    status: str


class DocumentSummaryOut(BaseModel):
    id: int
    filename: str
    summary: str


# --- QA ---
class SourceChunk(BaseModel):
    filename: str
    page_number: int
    content: str


class QAAskRequest(BaseModel):
    question: str
    document_id: str | None = None


class QAAskResponse(BaseModel):
    answer: str
    sources: list[SourceChunk]


class QAHistoryItem(BaseModel):
    id: int
    question: str
    answer: str
    sources: list[dict[str, Any]]
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Quiz ---
class QuizGenerateRequest(BaseModel):
    num_questions: int = Field(default=5, ge=1, le=30)
    document_id: str | None = None


class QuizQuestionOut(BaseModel):
    id: int
    question: str
    options: list[str]
    answer: str


class QuizGenerateResponse(BaseModel):
    session_id: UUID
    questions: list[QuizQuestionOut]


class QuizAnswerItem(BaseModel):
    question_id: int
    answer: str


class QuizSubmitRequest(BaseModel):
    answers: list[QuizAnswerItem]


class QuizResultItem(BaseModel):
    question_id: int
    correct: bool
    correct_answer: str
    user_answer: str | None = None


class QuizSubmitResponse(BaseModel):
    session_id: UUID
    score: int
    total: int
    results: list[QuizResultItem]


class QuizHistoryItem(BaseModel):
    session_id: UUID
    score: int
    total: int
    created_at: datetime

    model_config = {"from_attributes": True}


class QuizDetailQuestion(BaseModel):
    question_id: int
    question: str
    options: list[str]
    correct_answer: str
    user_answer: str | None
    correct: bool


class QuizDetailResponse(BaseModel):
    session_id: UUID
    score: int
    total: int
    created_at: datetime
    questions: list[QuizDetailQuestion]
