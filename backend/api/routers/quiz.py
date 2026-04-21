from __future__ import annotations

import os
import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.config import get_settings
from api.database import get_db
from api.deps import get_current_user
from api.models import Course, Document, QuizAttempt, QuizSession, User
from api.schemas import (
    QuizGenerateRequest,
    QuizGenerateResponse,
    QuizHistoryItem,
    QuizQuestionOut,
    QuizSubmitRequest,
    QuizSubmitResponse,
    QuizResultItem,
    QuizDetailResponse,
    QuizDetailQuestion,
)

router = APIRouter(tags=["quiz"])


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


def _normalize_choice(ans: str) -> str:
    m = re.search(r"[A-Da-d]", ans.strip())
    return (m.group(0).upper() if m else ans.strip().upper()[:1])


@router.post(
    "/courses/{course_id}/quiz/generate",
    response_model=QuizGenerateResponse,
    status_code=status.HTTP_201_CREATED,
)
def generate(
    course_id: int,
    body: QuizGenerateRequest,
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

    from worker.llm import generate_quiz

    raw_list = generate_quiz(
        str(course_id),
        db,
        num_questions=body.num_questions,
        document_id=body.document_id,
        difficulty=body.difficulty,
    )
    if not raw_list:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not generate quiz from course material",
        )

    session = QuizSession(
        course_id=course_id,
        user_id=user.id,
        questions=raw_list,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    questions_out = [
        QuizQuestionOut(
            id=int(item["id"]),
            type=str(item.get("type", "mcq")),
            question=item["question"],
            options=list(item.get("options", [])),
            answer=str(item["answer"]),
            explanation=str(item.get("explanation", "")),
        )
        for item in raw_list
        if isinstance(item, dict)
    ]
    return QuizGenerateResponse(session_id=session.id, questions=questions_out)


@router.post("/quiz/{session_id}/submit", response_model=QuizSubmitResponse)
def submit(
    session_id: UUID,
    body: QuizSubmitRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = db.get(QuizSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quiz session not found")

    by_id = {int(q["id"]): q for q in session.questions if isinstance(q, dict)}
    submitted = {a.question_id for a in body.answers}
    if submitted != set(by_id.keys()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must submit exactly one answer per question",
        )

    # Separate MCQ (local grading) from open questions (LLM grading)
    results: list[QuizResultItem] = []
    open_items = []
    score = 0

    for ans in body.answers:
        qrow = by_id.get(ans.question_id)
        if not qrow:
            raise HTTPException(status_code=400, detail=f"Unknown question_id {ans.question_id}")

        qtype = qrow.get("type", "mcq")
        explanation = str(qrow.get("explanation", ""))

        if qtype == "mcq":
            correct_letter = _normalize_choice(str(qrow.get("answer", "A")))
            given = _normalize_choice(ans.answer)
            ok = given == correct_letter
            if ok:
                score += 1
            results.append(QuizResultItem(
                question_id=ans.question_id,
                type=qtype,
                correct=ok,
                correct_answer=correct_letter,
                explanation=explanation,
                user_answer=ans.answer,
                feedback=None,
            ))
        else:
            # Queue for LLM grading
            open_items.append({
                "question_id": ans.question_id,
                "type": qtype,
                "question": qrow.get("question", ""),
                "reference_answer": qrow.get("answer", ""),
                "user_answer": ans.answer or "(no answer)",
            })
            # Placeholder, will be replaced after LLM grading
            results.append(QuizResultItem(
                question_id=ans.question_id,
                type=qtype,
                correct=False,
                correct_answer=str(qrow.get("answer", "")),
                explanation=explanation,
                user_answer=ans.answer,
                feedback=None,
            ))

    # LLM grade open questions
    if open_items:
        from worker.llm import grade_open_answers
        grades = grade_open_answers(open_items)
        grade_by_id = {g["question_id"]: g for g in grades}
        for r in results:
            if r.type != "mcq" and r.question_id in grade_by_id:
                g = grade_by_id[r.question_id]
                r.correct = bool(g.get("correct", False))
                r.feedback = str(g.get("feedback", ""))
                if r.correct:
                    score += 1

    total = len(by_id)
    attempt = QuizAttempt(
        session_id=session.id,
        course_id=session.course_id,
        user_id=user.id,
        score=score,
        total=total,
        results=[r.model_dump() for r in results],
    )
    db.add(attempt)
    db.commit()

    return QuizSubmitResponse(
        session_id=session.id,
        score=score,
        total=total,
        results=results,
    )


@router.get("/quiz/{session_id}/result", response_model=QuizDetailResponse)
def quiz_result(
    session_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = db.get(QuizSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quiz session not found")

    attempt = db.scalar(
        select(QuizAttempt)
        .where(QuizAttempt.session_id == session_id, QuizAttempt.user_id == user.id)
        .order_by(QuizAttempt.created_at.desc())
    )
    if attempt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No submission found for this session")

    # Build per-question detail by merging session questions with attempt results
    by_id = {int(q["id"]): q for q in session.questions if isinstance(q, dict)}
    result_by_id = {int(r["question_id"]): r for r in attempt.results if isinstance(r, dict)}

    questions = []
    for qid, q in sorted(by_id.items()):
        r = result_by_id.get(qid, {})
        questions.append(QuizDetailQuestion(
            question_id=qid,
            type=str(q.get("type", "mcq")),
            question=q.get("question", ""),
            options=list(q.get("options", [])),
            correct_answer=str(q.get("answer", "")),
            explanation=str(q.get("explanation", "")),
            user_answer=r.get("user_answer"),
            feedback=r.get("feedback"),
            correct=bool(r.get("correct", False)),
        ))

    return QuizDetailResponse(
        session_id=session.id,
        score=attempt.score,
        total=attempt.total,
        created_at=attempt.created_at,
        questions=questions,
    )


@router.get("/courses/{course_id}/quiz/history", response_model=list[QuizHistoryItem])
def history(
    course_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _course_for_user(db, course_id, user)
    rows = db.scalars(
        select(QuizAttempt)
        .where(QuizAttempt.course_id == course_id, QuizAttempt.user_id == user.id)
        .order_by(QuizAttempt.created_at.desc())
    ).all()
    return [
        QuizHistoryItem(
            session_id=r.session_id,
            score=r.score,
            total=r.total,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.delete("/courses/{course_id}/quiz/{session_id}")
def delete_quiz_attempt(
    course_id: int,
    session_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _course_for_user(db, course_id, user)
    attempt = db.scalar(
        select(QuizAttempt).where(
            QuizAttempt.session_id == session_id,
            QuizAttempt.user_id == user.id,
        )
    )
    if not attempt:
        raise HTTPException(status_code=404, detail="Quiz record not found")
    db.delete(attempt)
    db.commit()
    return {"message": "Deleted"}
