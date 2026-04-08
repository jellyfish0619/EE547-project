import json
import os
import subprocess
import sys
from pathlib import Path

import boto3
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.config import get_settings
from api.database import get_db
from api.deps import get_current_user
from api.models import Course, Document, User
from api.util import public_document_status
from api.schemas import (
    DocumentCreatedOut,
    DocumentListOut,
    DocumentStatusOut,
    DocumentSummaryOut,
    MessageOut,
)

router = APIRouter(tags=["documents"])


def _require_course(db: Session, course_id: int, user: User) -> Course:
    course = db.get(Course, course_id)
    if course is None or course.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    return course


def _require_document(db: Session, doc_id: int, user: User) -> Document:
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    course = db.get(Course, doc.course_id)
    if course is None or course.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return doc


def _spawn_local_worker(local_pdf: Path, doc_id: int) -> None:
    settings = get_settings()
    backend_root = Path(__file__).resolve().parents[2]
    worker_main = backend_root / "worker" / "main.py"
    env = {**os.environ, "DATABASE_URL": settings.psycopg_dsn()}
    subprocess.Popen(
        [sys.executable, str(worker_main), "--local", str(local_pdf.resolve()), str(doc_id)],
        cwd=str(backend_root),
        env=env,
    )


@router.post(
    "/courses/{course_id}/documents",
    response_model=DocumentCreatedOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    course_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    settings = get_settings()
    _require_course(db, course_id, user)

    filename = file.filename or "upload.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must be a PDF",
        )
    ct = (file.content_type or "").lower()
    if ct and "pdf" not in ct:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must be a PDF",
        )

    data = await file.read()
    if not data.startswith(b"%PDF"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must be a PDF",
        )

    doc = Document(
        course_id=course_id,
        filename=filename,
        status="pending",
        s3_key=None,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    key = f"courses/{course_id}/documents/{doc.id}.pdf"
    settings.local_upload_dir.mkdir(parents=True, exist_ok=True)
    local_path = settings.local_upload_dir / f"{doc.id}.pdf"

    if settings.s3_bucket_name:
        s3 = boto3.client("s3", region_name=settings.aws_region)
        s3.put_object(
            Bucket=settings.s3_bucket_name,
            Key=key,
            Body=data,
            ContentType="application/pdf",
        )
        doc.s3_key = key
        db.commit()
        if settings.sqs_queue_url:
            sqs = boto3.client("sqs", region_name=settings.aws_region)
            sqs.send_message(
                QueueUrl=settings.sqs_queue_url,
                MessageBody=json.dumps({"document_id": doc.id, "s3_key": key}),
            )
        else:
            local_path.write_bytes(data)
            _spawn_local_worker(local_path, doc.id)
    elif settings.sqs_queue_url:
        local_path.write_bytes(data)
        doc.s3_key = f"local/{doc.id}.pdf"
        db.commit()
        sqs = boto3.client("sqs", region_name=settings.aws_region)
        sqs.send_message(
            QueueUrl=settings.sqs_queue_url,
            MessageBody=json.dumps(
                {"document_id": doc.id, "local_path": str(local_path.resolve())}
            ),
        )
    else:
        local_path.write_bytes(data)
        doc.s3_key = str(local_path.resolve())
        db.commit()
        _spawn_local_worker(local_path, doc.id)

    return DocumentCreatedOut(
        id=doc.id, filename=doc.filename, status=public_document_status(doc.status)
    )


@router.get("/courses/{course_id}/documents", response_model=list[DocumentListOut])
def list_documents(
    course_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_course(db, course_id, user)
    docs = db.scalars(
        select(Document)
        .where(Document.course_id == course_id)
        .order_by(Document.created_at.desc())
    ).all()
    return [
        DocumentListOut(
            id=d.id,
            filename=d.filename,
            status=public_document_status(d.status),
            uploaded_at=d.created_at,
        )
        for d in docs
    ]


@router.get("/documents/{doc_id}/status", response_model=DocumentStatusOut)
def document_status(
    doc_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = _require_document(db, doc_id, user)
    return DocumentStatusOut(
        id=d.id, filename=d.filename, status=public_document_status(d.status)
    )


@router.get("/documents/{doc_id}/summary", response_model=DocumentSummaryOut)
def document_summary(
    doc_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = _require_document(db, doc_id, user)
    if d.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document is not ready yet",
        )
    if not d.summary:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Summary not available",
        )
    return DocumentSummaryOut(id=d.id, filename=d.filename, summary=d.summary)


@router.delete("/documents/{doc_id}", response_model=MessageOut)
def delete_document(
    doc_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = _require_document(db, doc_id, user)
    db.delete(d)
    db.commit()
    return MessageOut(message="文档已删除")
