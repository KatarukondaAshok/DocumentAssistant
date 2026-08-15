"""
routes.py
---------
All REST API endpoints:
  POST   /signup
  POST   /login
  POST   /upload
  POST   /chat
  GET    /history
  DELETE /history/{id}

Each route is intentionally thin -- business logic lives in auth.py / rag.py /
utils.py. This keeps the API layer readable and easy to test.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db
from auth import hash_password, verify_password, create_access_token, get_current_user
from utils import validate_file, compute_hash, save_file, logger
from rag import ingest_document, answer_question, summarize_document, collection_name_for, delete_document_vectors

router = APIRouter()


# ---------------------------------------------------------------------------
# AUTH
# ---------------------------------------------------------------------------
@router.post("/signup", response_model=schemas.TokenResponse, tags=["Auth"])
def signup(payload: schemas.SignupRequest, db: Session = Depends(get_db)):
    if db.query(models.User).filter(models.User.username == payload.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")
    if db.query(models.User).filter(models.User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = models.User(
        username=payload.username,
        email=payload.email,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": user.username})
    logger.info(f"New user signed up: {user.username}")
    return schemas.TokenResponse(access_token=token, username=user.username)


@router.post("/login", response_model=schemas.TokenResponse, tags=["Auth"])
def login(payload: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    token = create_access_token({"sub": user.username})
    return schemas.TokenResponse(access_token=token, username=user.username)


# ---------------------------------------------------------------------------
# UPLOAD
# ---------------------------------------------------------------------------
@router.post("/upload", response_model=schemas.DocumentResponse, tags=["Documents"])
def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    content = file.file.read()
    validate_file(file, content)
    file_hash = compute_hash(content)

    # Duplicate detection: same user, same content hash
    existing = (
        db.query(models.Document)
        .filter(models.Document.user_id == current_user.id, models.Document.file_hash == file_hash)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail=f"Duplicate of already-uploaded file '{existing.filename}'")

    filepath = save_file(current_user.id, file.filename, content)

    document = models.Document(
        user_id=current_user.id,
        filename=file.filename,
        filepath=filepath,
        file_hash=file_hash,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    document.collection_name = collection_name_for(current_user.id, document.id)
    db.commit()

    try:
        num_chunks = ingest_document(filepath, current_user.id, document.id)
        logger.info(f"User {current_user.username} uploaded '{file.filename}' ({num_chunks} chunks)")
    except Exception as e:
        db.delete(document)
        db.commit()
        raise HTTPException(status_code=500, detail=f"Failed to process document: {e}")

    return document


# ---------------------------------------------------------------------------
# CHAT
# ---------------------------------------------------------------------------
@router.post("/chat", response_model=schemas.ChatResponse, tags=["Chat"])
def chat(
    payload: schemas.ChatRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if payload.document_id:
        doc = (
            db.query(models.Document)
            .filter(models.Document.id == payload.document_id, models.Document.user_id == current_user.id)
            .first()
        )
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        collections = [doc.collection_name]
    else:
        docs = db.query(models.Document).filter(models.Document.user_id == current_user.id).all()
        if not docs:
            raise HTTPException(status_code=400, detail="Upload a document before chatting")
        collections = [d.collection_name for d in docs]

    try:
        if payload.mode == "summarize":
            answer = summarize_document(collections[0])
            sources = []
        else:
            answer, sources = answer_question(collections, payload.question)
    except Exception as e:
        logger.error(f"Chat generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Could not generate an answer: {e}")

    chat_row = models.ChatHistory(
        user_id=current_user.id,
        document_id=payload.document_id,
        question=payload.question,
        answer=answer,
    )
    db.add(chat_row)
    db.commit()
    db.refresh(chat_row)

    return schemas.ChatResponse(answer=answer, sources=sources, chat_id=chat_row.id)


# ---------------------------------------------------------------------------
# HISTORY
# ---------------------------------------------------------------------------
@router.get("/history", response_model=list[schemas.HistoryItem], tags=["History"])
def get_history(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    rows = (
        db.query(models.ChatHistory)
        .filter(models.ChatHistory.user_id == current_user.id)
        .order_by(models.ChatHistory.timestamp.desc())
        .all()
    )
    return rows


@router.delete("/history/{item_id}", tags=["History"])
def delete_history_item(
    item_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)
):
    row = (
        db.query(models.ChatHistory)
        .filter(models.ChatHistory.id == item_id, models.ChatHistory.user_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="History item not found")
    db.delete(row)
    db.commit()
    return {"detail": "Deleted successfully"}


# ---------------------------------------------------------------------------
# DOCUMENTS LIST (bonus, used by the frontend to populate a dropdown)
# ---------------------------------------------------------------------------
@router.get("/documents", response_model=list[schemas.DocumentResponse], tags=["Documents"])
def list_documents(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    return db.query(models.Document).filter(models.Document.user_id == current_user.id).all()


@router.delete("/documents/{doc_id}", tags=["Documents"])
def delete_document(
    doc_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)
):
    doc = (
        db.query(models.Document)
        .filter(models.Document.id == doc_id, models.Document.user_id == current_user.id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    delete_document_vectors(current_user.id, doc.id)
    db.delete(doc)
    db.commit()
    return {"detail": "Document deleted"}
