#!/bin/bash
# Quick fix script for missing directories issue
# This script ensures the data and logs directories exist with correct permissions

set -e

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
SERVICE_USER="www-data"
SERVICE_GROUP="www-data"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Fixing Regression Tracker Directories${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if installation directory exists
if [ ! -d "$INSTALL_DIR" ]; then
    echo -e "${RED}Error: Installation directory not found: $INSTALL_DIR${NC}"
    exit 1
fi

cd "$INSTALL_DIR"

# Create directories
echo -e "${GREEN}Creating directories...${NC}"
mkdir -p data logs data/backups

# Verify directories were created
if [ ! -d "data" ] || [ ! -d "logs" ]; then
    echo -e "${RED}Error: Failed to create directories${NC}"
    exit 1
fi
echo -e "${BLUE}  ✓ Directories created${NC}"

# Set permissions
echo -e "${GREEN}Setting permissions...${NC}"
chmod 755 data logs data/backups
echo -e "${BLUE}  ✓ Permissions set (755)${NC}"

# Set ownership
if id "$SERVICE_USER" &>/dev/null; then
    chown -R "$SERVICE_USER:$SERVICE_GROUP" data logs
    echo -e "${BLUE}  ✓ Ownership set to $SERVICE_USER:$SERVICE_GROUP${NC}"
else
    echo -e "${RED}Warning: User $SERVICE_USER not found${NC}"
fi

# Restart service
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
echo ""
echo -e "If the service is still failing, check logs with:"
echo -e "  ${BLUE}sudo journalctl -u regression-tracker -n 50${NC}"
