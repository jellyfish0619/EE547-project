"""
Worker main — drives the full PDF processing pipeline:
    PDF file → parse → embed (OpenAI) → store in DB → update status

Local mode (called by API via subprocess.Popen):
    python main.py --local <pdf_path> <document_id> [--no-summary]

SQS mode (if SQS_QUEUE_URL is set):
    python main.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time

import psycopg2
from dotenv import load_dotenv

from pdf_parser import parse_pdf
from embedder import embed_and_store
from llm import update_document_summary

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SQS_QUEUE_URL  = os.getenv("SQS_QUEUE_URL", "")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "")
AWS_REGION     = os.getenv("AWS_REGION", "us-east-1")
POLL_INTERVAL  = 5


def _normalize_dsn(url: str) -> str:
    for prefix in ("postgresql+psycopg2://", "postgresql+psycopg://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix):]
    return url


DATABASE_URL = _normalize_dsn(os.getenv("DATABASE_URL", ""))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _update_document_status(document_id: int, status: str) -> None:
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
    import boto3
    if not S3_BUCKET_NAME:
        raise ValueError("S3_BUCKET_NAME is not set")
    s3 = boto3.client("s3", region_name=AWS_REGION)
    suffix = os.path.splitext(s3_key)[-1] or ".pdf"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    s3.download_fileobj(S3_BUCKET_NAME, s3_key, tmp)
    tmp.close()
    return tmp.name


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

def process_document(document_id: int, pdf_path: str, auto_summary: bool = True) -> None:
    print(f"[doc={document_id}] Starting pipeline: {pdf_path}", flush=True)
    _update_document_status(document_id, "processing")

    try:
        chunks = parse_pdf(pdf_path)
        print(f"[doc={document_id}] Parsed {len(chunks)} chunks", flush=True)

        stored = embed_and_store(document_id, chunks, DATABASE_URL)
        print(f"[doc={document_id}] Stored {stored} chunks", flush=True)

        _update_document_status(document_id, "ready")

        if auto_summary:
            try:
                update_document_summary(document_id, DATABASE_URL)
                print(f"[doc={document_id}] Summary generated", flush=True)
            except Exception as e:
                print(f"[doc={document_id}] Summary skipped: {e}", flush=True)
        else:
            print(f"[doc={document_id}] Summary skipped (disabled)", flush=True)

        print(f"[doc={document_id}] Done ✓", flush=True)

    except Exception as e:
        print(f"[doc={document_id}] Error: {e}", flush=True)
        _update_document_status(document_id, "failed")
        raise


# ---------------------------------------------------------------------------
# SQS consumer loop
# ---------------------------------------------------------------------------

def run_worker() -> None:
    if not SQS_QUEUE_URL:
        print("SQS_QUEUE_URL not set — worker idle (API spawns local subprocesses).", flush=True)
        while True:
            time.sleep(60)

    import boto3
    sqs = boto3.client("sqs", region_name=AWS_REGION)
    print(f"Worker polling SQS: {SQS_QUEUE_URL}", flush=True)

    while True:
        response = sqs.receive_message(
            QueueUrl=SQS_QUEUE_URL,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=10,
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
            auto_summary = bool(body.get("auto_summary", True))
            if body.get("local_path"):
                pdf_path = body["local_path"]
                tmp_downloaded = False
            else:
                pdf_path = _download_from_s3(body["s3_key"])
                tmp_downloaded = True
            try:
                process_document(document_id, pdf_path, auto_summary)
            finally:
                if tmp_downloaded:
                    try:
                        os.unlink(pdf_path)
                    except OSError:
                        pass
            sqs.delete_message(QueueUrl=SQS_QUEUE_URL, ReceiptHandle=receipt)
        except Exception as e:
            print(f"Failed to process SQS message: {e}", flush=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--local":
        pdf    = sys.argv[2]
        doc_id = int(sys.argv[3])
        no_summary = "--no-summary" in sys.argv
        process_document(doc_id, pdf, auto_summary=not no_summary)
    else:
        run_worker()
