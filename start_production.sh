#!/bin/bash
# Start the Regression Tracker Web Application in Production Mode
# Uses Gunicorn with multiple workers for high performance

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Regression Tracker - Production Start${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if port 8000 is already in use
if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo -e "${RED}Error: Port 8000 is already in use!${NC}"
    echo -e "${YELLOW}Please run ./stop.sh first or use ./restart.sh${NC}"
    exit 1
fi

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Virtual environment not found. Creating one...${NC}"
    python3 -m venv venv
    source venv/bin/activate
    echo -e "${YELLOW}Installing dependencies...${NC}"
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

# Verify gunicorn is installed
if ! command -v gunicorn &> /dev/null; then
    echo -e "${RED}Error: Gunicorn not found in virtual environment${NC}"
    echo -e "${YELLOW}Installing gunicorn...${NC}"
    pip install gunicorn
fi

# Check if database exists
if [ ! -f "data/regression_tracker.db" ]; then
    echo -e "${RED}Error: Database not found${NC}"
    echo -e "${YELLOW}Please run database migration first:${NC}"
    echo "  alembic upgrade head"
    exit 1
fi

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}Warning: .env file not found${NC}"
    echo -e "${YELLOW}Copying from .env.example...${NC}"
    cp .env.example .env
    echo -e "${YELLOW}Please edit .env with your configuration${NC}"
    exit 1
fi

# Source environment variables
set -a
source .env
set +a

# Get number of CPU cores for worker calculation
CPU_CORES=$(python3 -c "import multiprocessing; print(multiprocessing.cpu_count())")
WORKERS=${GUNICORN_WORKERS:-$((CPU_CORES * 2 + 1))}

echo -e "${GREEN}Starting production server with:${NC}"
echo -e "  Workers: ${BLUE}${WORKERS}${NC}"
echo -e "  Port: ${BLUE}${PORT:-8000}${NC}"
echo -e "  Host: ${BLUE}${HOST:-0.0.0.0}${NC}"
echo -e "  Config: ${BLUE}gunicorn.conf.py${NC}"
echo ""
echo -e "${GREEN}Server will be available at:${NC}"
echo -e "  ${BLUE}http://localhost:${PORT:-8000}${NC}"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Start the application with Gunicorn
exec gunicorn app.main:app -c gunicorn.conf.py
