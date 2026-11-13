#!/usr/bin/env bash
cd "$(dirname "$0")"
umask 077
source backend/venv/bin/activate
export PYTHONPATH=backend
export PYTHONUNBUFFERED=1
exec python -m app.main

