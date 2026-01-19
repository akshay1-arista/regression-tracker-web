#!/bin/bash
# Start with multiple workers for concurrent access

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "Starting Regression Tracker with 4 workers (supports concurrent users)..."

# Kill existing processes on port 8000
lsof -ti:8000 | xargs kill -9 2>/dev/null

# Start with Gunicorn (production-ready)
gunicorn app.main:app \
    --workers 4 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8000 \
    --timeout 300 \
    --access-logfile - \
    --error-logfile - \
    --log-level info

