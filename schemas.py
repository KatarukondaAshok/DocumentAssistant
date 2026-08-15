"""
schemas.py
----------
Pydantic models used for request validation and response serialization.
Keeping these separate from SQLAlchemy models (models.py) is a deliberate
design choice: it decouples the API contract from the DB schema.
"""
from pydantic import BaseModel, EmailStr, field_validator
from datetime import datetime
from typing import Optional


# ---------- Auth ----------
class SignupRequest(BaseModel):
    username: str
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v):
        if len(v) < 6:
            raise ValueError("Password must be at least 6 characters long")
        return v


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


# ---------- Documents ----------
class DocumentResponse(BaseModel):
    id: int
    filename: str
    uploaded_at: datetime

    class Config:
        from_attributes = True


# ---------- Chat ----------
class ChatRequest(BaseModel):
    document_id: Optional[int] = None  # None => search across all of the user's documents
    question: str
    mode: str = "qa"  # "qa" or "summarize"


class ChatResponse(BaseModel):
    answer: str
    sources: list[str] = []
    chat_id: int


class HistoryItem(BaseModel):
    id: int
    document_id: Optional[int]
    question: str
    answer: str
    timestamp: datetime

    class Config:
        from_attributes = True
