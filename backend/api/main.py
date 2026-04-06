from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.config import get_settings
from api.routers import auth, courses, documents, qa, quiz


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings()
    yield


app = FastAPI(title="CourseMate API", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(courses.router)
app.include_router(documents.router)
app.include_router(qa.router)
app.include_router(quiz.router)


@app.get("/health")
def health():
    return {"status": "ok"}
