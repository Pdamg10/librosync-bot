#!/usr/bin/env bash
cd "$(dirname "$0")"
source backend/venv/bin/activate
export PYTHONPATH=backend
export PYTHONUNBUFFERED=1
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir backend/app --loop asyncio

