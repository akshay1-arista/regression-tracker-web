#!/bin/bash
# Restart the Regression Tracker Web Application

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
echo -e "${BLUE}  Regression Tracker - Restart${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Step 1: Stop the application
echo -e "${YELLOW}[1/3] Stopping application...${NC}"
./stop.sh
if [ $? -ne 0 ]; then
    echo -e "${YELLOW}No running instance found, proceeding with start...${NC}"
fi
echo ""

# Step 2: Clear Python cache (optional but good practice)
echo -e "${YELLOW}[2/3] Clearing Python cache...${NC}"
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete 2>/dev/null
echo -e "${GREEN}Cache cleared${NC}"
echo ""

# Step 3: Start the application
echo -e "${YELLOW}[3/3] Starting application...${NC}"
echo ""
./start.sh
