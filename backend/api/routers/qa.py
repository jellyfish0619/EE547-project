from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.config import get_settings
from api.database import get_db
from api.deps import get_current_user
from api.models import Course, Document, QAHistory, User
from api.schemas import QAAskRequest, QAAskResponse, QAHistoryItem, SourceChunk

router = APIRouter(tags=["qa"])


def _course_for_user(db: Session, course_id: int, user: User) -> Course:
    course = db.get(Course, course_id)
    if course is None or course.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    return course


def _ensure_llm_env() -> None:
    settings = get_settings()
    if settings.openai_api_key:
        os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)
    if settings.openai_chat_model:
        os.environ.setdefault("OPENAI_CHAT_MODEL", settings.openai_chat_model)
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenAI API key is not configured",
        )


@router.post("/courses/{course_id}/qa", response_model=QAAskResponse)
def ask(
    course_id: int,
    body: QAAskRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _course_for_user(db, course_id, user)
    _ensure_llm_env()

    q = select(func.count()).select_from(Document).where(
        Document.course_id == course_id,
        Document.status == "ready",
    )
    if db.scalar(q) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No processed documents in this course",
        )

    if body.document_id is not None:
        doc = db.get(Document, body.document_id)
        if doc is None or doc.course_id != course_id or doc.status != "ready":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or unready document",
            )

    from worker.llm import search_and_answer

    raw = search_and_answer(
        body.question,
        str(course_id),
        db,
        document_id=body.document_id,
    )

    sources = [
        SourceChunk(**s)
        for s in raw.get("sources", [])
        if isinstance(s, dict)
    ]
    payload = QAHistory(
        course_id=course_id,
        user_id=user.id,
        question=body.question,
        answer=raw.get("answer", ""),
        sources=[s.model_dump() for s in sources],
    )
    db.add(payload)
    db.commit()

    return QAAskResponse(answer=raw.get("answer", ""), sources=sources)


@router.get("/courses/{course_id}/qa", response_model=list[QAHistoryItem])
def qa_history(
    course_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _course_for_user(db, course_id, user)
    rows = db.scalars(
        select(QAHistory)
        .where(QAHistory.course_id == course_id, QAHistory.user_id == user.id)
        .order_by(QAHistory.created_at.desc())
    ).all()
    return rows


@router.delete("/courses/{course_id}/qa/{qa_id}")
def delete_qa(
    course_id: int,
    qa_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _course_for_user(db, course_id, user)
    row = db.get(QAHistory, qa_id)
    if row is None or row.course_id != course_id or row.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found")
    db.delete(row)
    db.commit()
    return {"message": "Deleted"}


@router.delete("/courses/{course_id}/qa")
def clear_qa_history(
    course_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _course_for_user(db, course_id, user)
    db.query(QAHistory).filter(
        QAHistory.course_id == course_id,
        QAHistory.user_id == user.id,
    ).delete()
    db.commit()
    return {"message": "Cleared"}
