"""
utils.py
--------
Helper functions: file validation, safe saving to disk, duplicate detection
via SHA-256 hashing, and basic logging setup.
"""
import os
import hashlib
import logging
from fastapi import UploadFile, HTTPException

from config import UPLOAD_DIR, ALLOWED_EXTENSIONS, MAX_FILE_SIZE_MB

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("document-assistant")


def validate_file(file: UploadFile, content: bytes):
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )
    size_mb = len(content) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(status_code=400, detail=f"File too large ({size_mb:.1f} MB). Max {MAX_FILE_SIZE_MB} MB.")


def compute_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def save_file(user_id: int, filename: str, content: bytes) -> str:
    """Saves file under uploads/<user_id>/<filename> and returns the path."""
    user_dir = os.path.join(UPLOAD_DIR, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    filepath = os.path.join(user_dir, filename)

    # avoid overwriting: append counter if name already exists
    base, ext = os.path.splitext(filepath)
    counter = 1
    while os.path.exists(filepath):
        filepath = f"{base}_{counter}{ext}"
        counter += 1

    with open(filepath, "wb") as f:
        f.write(content)
    return filepath
