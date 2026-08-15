#!/bin/bash
set -e

# Start FastAPI backend in the background
cd /app/backend
uvicorn app:app --host 0.0.0.0 --port 8000 &

# Give it a moment to come up
sleep 3

# Start Streamlit frontend in the foreground on the port HF Spaces expects
cd /app/frontend
streamlit run streamlit_app.py \
    --server.port 7860 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false
