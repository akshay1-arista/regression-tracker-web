#!/bin/bash
# Start the Regression Tracker Web Application

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo -e "${GREEN}Starting Regression Tracker Web Application...${NC}"

# Check if port 8000 is already in use
if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo -e "${YELLOW}Warning: Port 8000 is already in use!${NC}"
    echo -e "${YELLOW}Please run ./stop.sh first or use ./restart.sh${NC}"
    exit 1
fi

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Virtual environment not found. Creating one...${NC}"
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

# Check if database exists
if [ ! -f "data/regression_tracker.db" ]; then
    echo -e "${YELLOW}Database not found. Please run migration first:${NC}"
    echo "  alembic upgrade head"
    exit 1
fi

# Start the application
echo -e "${GREEN}Starting FastAPI server on http://localhost:8000${NC}"
echo -e "${GREEN}Press Ctrl+C to stop${NC}"
echo ""

# Run with uvicorn (single worker for development)
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
