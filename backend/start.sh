#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# Install dependencies if needed
pip install -q -r requirements.txt 2>/dev/null

echo "Starting Spark Dashboard backend on port 8888 ..."
exec uvicorn app:app --host 0.0.0.0 --port 8888 --reload
