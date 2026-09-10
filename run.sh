#!/usr/bin/env bash
cd "$(dirname "$0")"
source backend/venv/bin/activate
export PYTHONPATH=backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
