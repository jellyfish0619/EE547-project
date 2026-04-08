from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.database import get_db
from api.deps import get_current_user
from api.models import Course, Document, User
from api.schemas import CourseCreate, CourseDetailOut, CourseOut, DocumentBrief, MessageOut
from api.util import public_document_status

router = APIRouter(prefix="/courses", tags=["courses"])


def _get_owned_course(db: Session, course_id: int, user: User) -> Course:
    course = db.get(Course, course_id)
    if course is None or course.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    return course


@router.get("", response_model=list[CourseOut])
def list_courses(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = db.scalars(
        select(Course).where(Course.owner_id == user.id).order_by(Course.created_at.desc())
    ).all()
    return rows


@router.post("", response_model=CourseOut, status_code=status.HTTP_201_CREATED)
def create_course(
    body: CourseCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    course = Course(
        owner_id=user.id,
        name=body.name,
        description=body.description or "",
    )
    db.add(course)
    db.commit()
    db.refresh(course)
    return course


@router.get("/{course_id}", response_model=CourseDetailOut)
def get_course(
    course_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    course = _get_owned_course(db, course_id, user)
    docs = db.scalars(
        select(Document)
        .where(Document.course_id == course.id)
        .order_by(Document.created_at.desc())
    ).all()
    return CourseDetailOut(
        id=course.id,
        name=course.name,
        description=course.description,
        created_at=course.created_at,
        documents=[
            DocumentBrief(
                id=d.id, filename=d.filename, status=public_document_status(d.status)
            )
            for d in docs
        ],
    )


@router.delete("/{course_id}", response_model=MessageOut)
def delete_course(
    course_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    course = _get_owned_course(db, course_id, user)
    db.delete(course)
    db.commit()
    return MessageOut(message="课程已删除")
