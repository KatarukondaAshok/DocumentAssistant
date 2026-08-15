"""
auth.py
-------
Handles password hashing (bcrypt) and JWT creation/verification.

NOTE: We call the `bcrypt` library directly instead of going through
`passlib.CryptContext`. Newer bcrypt releases (4.1+) removed an internal
`__about__` attribute that older passlib versions (1.7.4) rely on to detect
the backend version, which causes hashing to fail at runtime with a 500
error. Calling bcrypt directly avoids that compatibility issue entirely.

Interview note:
- We NEVER store plain-text passwords. bcrypt hashes are salted and
  computationally expensive on purpose, which slows down brute-force attacks.
- JWT (JSON Web Token) is a signed, stateless token. The server doesn't need
  to store session data -- it just verifies the signature on every request.
"""
from datetime import datetime, timedelta
import bcrypt
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
from database import get_db
import models

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


def hash_password(password: str) -> str:
    """Hashes a password with bcrypt (auto-generates a random salt)."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Compares a plain-text password against a stored bcrypt hash."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        # hashed_password isn't a valid bcrypt hash (e.g. corrupted/old data)
        return False


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> models.User:
    """FastAPI dependency: extracts + validates the JWT, returns the DB user.
    Any route that includes `Depends(get_current_user)` is protected."""
    payload = decode_access_token(token)
    username: str = payload.get("sub")
    if username is None:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    user = db.query(models.User).filter(models.User.username == username).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user
