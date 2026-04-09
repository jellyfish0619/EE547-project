from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://postgres:password@localhost:5432/coursemate"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7

    aws_region: str = "us-east-1"
    s3_bucket_name: str = ""
    sqs_queue_url: str = ""

    local_upload_dir: Path = Path("/tmp/coursemate_uploads")
    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4o-mini"

    class Config:
        env_file = [".env", "../.env"]
        env_file_encoding = "utf-8"
        extra = "ignore"

    def psycopg_dsn(self) -> str:
        u = self.database_url
        for prefix in ("postgresql+psycopg2://", "postgresql+psycopg://"):
            if u.startswith(prefix):
                return "postgresql://" + u[len(prefix) :]
        return u


@lru_cache
def get_settings() -> Settings:
    return Settings()
