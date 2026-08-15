FROM python:3.11-slim

# System deps some wheels need (chromadb / sentence-transformers)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# HF Spaces containers run as a non-root user with HOME=/home/user
RUN useradd -m -u 1000 user
WORKDIR /app

COPY backend/requirements.txt backend-requirements.txt
COPY frontend/requirements.txt frontend-requirements.txt
RUN pip install --no-cache-dir -r backend-requirements.txt -r frontend-requirements.txt

COPY . .

# Writable dirs for SQLite, uploads, Chroma persistence
RUN mkdir -p database uploads chroma_db backend/uploads \
    && chown -R user:user /app

USER user
ENV HOME=/home/user \
    PYTHONUNBUFFERED=1

# HF Spaces expects the app to listen on 7860 (Streamlit here);
# FastAPI runs on 8000 internally, called by the frontend at localhost:8000.
EXPOSE 7860

COPY --chown=user:user start.sh /app/start.sh
RUN chmod +x /app/start.sh

CMD ["/app/start.sh"]
