#!/bin/bash
# Stop the Regression Tracker Web Application

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Stopping Regression Tracker Web Application...${NC}"

# Find and kill process on port 8000
PID=$(lsof -ti:8000)

if [ -z "$PID" ]; then
    echo -e "${YELLOW}No application running on port 8000${NC}"
    exit 0
fi

# Kill the process
kill -9 $PID 2>/dev/null

if [ $? -eq 0 ]; then
    echo -e "${GREEN}Application stopped successfully (PID: $PID)${NC}"
else
    echo -e "${RED}Failed to stop application${NC}"
    exit 1
fi

# Wait a moment to ensure port is released
sleep 1

# Verify port is free
if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo -e "${RED}Warning: Port 8000 is still in use!${NC}"
    exit 1
else
    echo -e "${GREEN}Port 8000 is now free${NC}"
fi
