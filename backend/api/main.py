from fastapi import FastAPI

app = FastAPI(title="CourseMate API")

@app.get("/health")
def health():
    return {"status": "ok"}