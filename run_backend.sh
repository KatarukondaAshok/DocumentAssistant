#!/bin/bash
cd backend
uvicorn app:app --reload --port 8000
