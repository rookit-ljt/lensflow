#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=${0:A:h}
cd "$SCRIPT_DIR"
exec ./.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
