"""
Worker main — SQS consumer that drives the full pipeline:
    SQS message → download PDF from S3 → parse → embed → store in DB → update status

Local test mode (no SQS/S3 needed):
    python main.py --local <pdf_path> <document_id>
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time

import boto3
from dotenv import load_dotenv

from pdf_parser import parse_pdf
from embedder import embed_and_store

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SQS_QUEUE_URL  = os.getenv("SQS_QUEUE_URL", "")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "")
AWS_REGION     = os.getenv("AWS_REGION", "us-east-1")
DATABASE_URL   = os.getenv("DATABASE_URL", "")
POLL_INTERVAL  = 5   # seconds between SQS polls when queue is empty


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _update_document_status(document_id: int, status: str) -> None:
    """Update documents.status in the database."""
    import psycopg2
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE documents SET status = %s WHERE id = %s",
                    (status, document_id),
                )
    finally:
        conn.close()


def _download_from_s3(s3_key: str) -> str:
    """Download a file from S3 to a temp file. Returns local path."""
    s3 = boto3.client("s3", region_name=AWS_REGION)
    suffix = os.path.splitext(s3_key)[-1] or ".pdf"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    s3.download_fileobj(S3_BUCKET_NAME, s3_key, tmp)
    tmp.close()
    return tmp.name


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

def process_document(document_id: int, pdf_path: str) -> None:
    """Run the full pipeline for one document."""
    print(f"[doc={document_id}] Starting pipeline: {pdf_path}")

    _update_document_status(document_id, "processing")

    try:
        chunks = parse_pdf(pdf_path)
        print(f"[doc={document_id}] Parsed {len(chunks)} chunks")

        stored = embed_and_store(document_id, chunks, DATABASE_URL)
        print(f"[doc={document_id}] Stored {stored} chunks")

        _update_document_status(document_id, "ready")
        print(f"[doc={document_id}] Done")

    except Exception as e:
        print(f"[doc={document_id}] Error: {e}")
        _update_document_status(document_id, "error")
        raise


# ---------------------------------------------------------------------------
# SQS consumer loop
# ---------------------------------------------------------------------------

def run_worker() -> None:
    """Poll SQS indefinitely and process each message."""
    sqs = boto3.client("sqs", region_name=AWS_REGION)
    print(f"Worker started. Polling {SQS_QUEUE_URL} ...")

    while True:
        response = sqs.receive_message(
            QueueUrl=SQS_QUEUE_URL,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=10,   # long polling
        )

        messages = response.get("Messages", [])
        if not messages:
            time.sleep(POLL_INTERVAL)
            continue

        msg = messages[0]
        receipt = msg["ReceiptHandle"]

        try:
            body = json.loads(msg["Body"])
            document_id = int(body["document_id"])
            s3_key      = body["s3_key"]

            pdf_path = _download_from_s3(s3_key)
            try:
                process_document(document_id, pdf_path)
            finally:
                os.unlink(pdf_path)   # clean up temp file

            # Delete message only on success
            sqs.delete_message(QueueUrl=SQS_QUEUE_URL, ReceiptHandle=receipt)

        except Exception as e:
            print(f"Failed to process message: {e}")
            # Message stays in queue and will be retried after visibility timeout


# ---------------------------------------------------------------------------
# Local test mode  (no SQS / S3 needed)
# ---------------------------------------------------------------------------

def run_local(pdf_path: str, document_id: int) -> None:
    """Test the pipeline locally with a file on disk."""
    process_document(document_id, pdf_path)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--local":
        pdf  = sys.argv[2]
        doc_id = int(sys.argv[3])
        run_local(pdf, doc_id)
    else:
        run_worker()
