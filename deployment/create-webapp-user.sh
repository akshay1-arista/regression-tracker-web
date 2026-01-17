#!/bin/bash
# Create webapp user for running the Regression Tracker service

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Error: This script must be run as root${NC}"
    echo "Please run: sudo $0"
    exit 1
fi

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Creating webapp User${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if webapp user already exists
if id "webapp" &>/dev/null; then
    echo -e "${YELLOW}User 'webapp' already exists${NC}"
    id webapp
    exit 0
fi

# Create webapp user
echo -e "${GREEN}Creating webapp user...${NC}"
useradd --system --no-create-home --shell /bin/false webapp

# Verify user was created
if id "webapp" &>/dev/null; then
    echo -e "${BLUE}  ✓ User 'webapp' created successfully${NC}"
    echo ""
    echo -e "${BLUE}User details:${NC}"
    id webapp
else
    echo -e "${RED}  ✗ Failed to create user 'webapp'${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}User Creation Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Run the installation script: ${BLUE}sudo deployment/install.sh${NC}"
echo "2. Or fix ownership of existing installation: ${BLUE}sudo chown -R webapp:webapp /opt/regression-tracker-web${NC}"
