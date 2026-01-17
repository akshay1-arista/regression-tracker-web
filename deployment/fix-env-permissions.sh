#!/bin/bash
# Quick fix for .env file permissions

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Error: This script must be run as root${NC}"
    echo "Please run: sudo $0"
    exit 1
fi

INSTALL_DIR="/opt/regression-tracker-web"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Fixing .env File Permissions${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if .env exists
if [ ! -f "$INSTALL_DIR/.env" ]; then
    echo -e "${RED}Error: .env file not found at $INSTALL_DIR/.env${NC}"
    echo -e "Please create the file first with your Jenkins credentials"
    exit 1
fi

cd "$INSTALL_DIR"

# Fix permissions
echo -e "${GREEN}Setting .env permissions to 644...${NC}"
chmod 644 .env

# Set ownership
echo -e "${GREEN}Setting ownership to webapp:webapp...${NC}"
chown webapp:webapp .env

# Verify
echo ""
echo -e "${BLUE}Current .env file status:${NC}"
ls -la .env

# Test if webapp can read it
echo ""
echo -e "${BLUE}Testing if webapp can read .env...${NC}"
if sudo -u webapp test -r .env; then
    echo -e "${GREEN}  ✓ webapp can read .env${NC}"
else
    echo -e "${RED}  ✗ webapp still cannot read .env${NC}"
    exit 1
fi

# Restart service
echo ""
echo -e "${GREEN}Restarting service...${NC}"
systemctl restart regression-tracker
sleep 2

# Check status
echo ""
echo -e "${BLUE}Service status:${NC}"
systemctl status regression-tracker --no-pager || true

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Fix Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
