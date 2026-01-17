#!/bin/bash
# Diagnostic script to check configuration and environment variables

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

INSTALL_DIR="/opt/regression-tracker-web"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Configuration Diagnostic${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if .env file exists
echo -e "${GREEN}1. Checking .env file...${NC}"
if [ -f "$INSTALL_DIR/.env" ]; then
    echo -e "${BLUE}  ✓ .env file exists${NC}"
    echo -e "${YELLOW}  File permissions:${NC}"
    ls -la "$INSTALL_DIR/.env"
    echo ""
    echo -e "${YELLOW}  File contents (sanitized):${NC}"
    cat "$INSTALL_DIR/.env" | sed 's/\(JENKINS_API_TOKEN=\).*/\1***REDACTED***/' | sed 's/\(ADMIN_PIN_HASH=\).*/\1***REDACTED***/'
else
    echo -e "${RED}  ✗ .env file NOT found${NC}"
fi

echo ""
echo -e "${GREEN}2. Checking if webapp can read .env...${NC}"
if sudo -u webapp test -r "$INSTALL_DIR/.env"; then
    echo -e "${BLUE}  ✓ webapp can read .env${NC}"
else
    echo -e "${RED}  ✗ webapp CANNOT read .env${NC}"
    echo -e "${YELLOW}  Fix with: sudo chmod 644 $INSTALL_DIR/.env${NC}"
fi

echo ""
echo -e "${GREEN}3. Testing environment variable loading...${NC}"
cd "$INSTALL_DIR"
sudo -u webapp bash -c "cd $INSTALL_DIR && source venv/bin/activate && python3 -c '
from app.config import get_settings
settings = get_settings()
print(f\"  JENKINS_URL: {settings.JENKINS_URL}\")
print(f\"  JENKINS_USER: {settings.JENKINS_USER}\")
token_status = \"***SET***\" if settings.JENKINS_API_TOKEN else \"NOT SET\"
print(f\"  JENKINS_API_TOKEN: {token_status}\")
print(f\"  DATABASE_URL: {settings.DATABASE_URL}\")
print(f\"  LOGS_BASE_PATH: {settings.LOGS_BASE_PATH}\")
print(f\"  POLLING_INTERVAL_HOURS: {settings.POLLING_INTERVAL_HOURS}\")
' 2>&1"

echo ""
echo -e "${GREEN}4. Checking systemd service environment...${NC}"
if systemctl is-active --quiet regression-tracker; then
    echo -e "${BLUE}  Service is running${NC}"
    echo -e "${YELLOW}  Environment variables from systemd:${NC}"
    sudo systemctl show regression-tracker --property=Environment | grep JENKINS || echo "    No JENKINS variables found"
else
    echo -e "${YELLOW}  Service is not running${NC}"
fi

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}Diagnostic Complete${NC}"
echo -e "${BLUE}========================================${NC}"
