"""
app.py
------
FastAPI application entrypoint.
Run with:  uvicorn app:app --reload --port 8000
Docs available at: http://localhost:8000/docs
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import init_db
from routes import router

app = FastAPI(
    title="Intelligent Document Assistant API",
    description="Authentication + RAG-powered document Q&A, built with FastAPI, LangChain and ChromaDB.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/", tags=["Health"])
def root():
    return {"status": "ok", "message": "Intelligent Document Assistant API is running"}


app.include_router(router)
