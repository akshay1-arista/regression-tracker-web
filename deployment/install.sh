#!/bin/bash
# Installation script for Regression Tracker Web Application
# This script sets up the application as a systemd service

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
echo -e "${BLUE}Regression Tracker - Installation${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Configuration
INSTALL_DIR="/opt/regression-tracker-web"
SERVICE_USER="www-data"
SERVICE_GROUP="www-data"

# Step 1: Create installation directory
echo -e "${GREEN}[1/8] Creating installation directory...${NC}"
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR" || exit 1

# Step 2: Copy application files
echo -e "${GREEN}[2/8] Copying application files...${NC}"
if [ -d "$(dirname "$0")/../app" ]; then
    cp -r "$(dirname "$0")/../"* "$INSTALL_DIR/"
    echo -e "${BLUE}  ✓ Files copied${NC}"
else
    echo -e "${RED}  ✗ Error: Application files not found${NC}"
    exit 1
fi

# Step 3: Create virtual environment
echo -e "${GREEN}[3/8] Creating virtual environment...${NC}"
python3 -m venv venv
source venv/bin/activate
echo -e "${BLUE}  ✓ Virtual environment created${NC}"

# Step 4: Install dependencies
echo -e "${GREEN}[4/8] Installing dependencies...${NC}"
pip install --upgrade pip
pip install -r requirements.txt
echo -e "${BLUE}  ✓ Dependencies installed${NC}"

# Step 5: Setup environment file
echo -e "${GREEN}[5/8] Setting up environment file...${NC}"
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo -e "${YELLOW}  ! Please edit /opt/regression-tracker-web/.env with your configuration${NC}"
else
    echo -e "${BLUE}  ✓ .env file already exists${NC}"
fi

# Step 6: Create data directories
echo -e "${GREEN}[6/8] Creating data directories...${NC}"
mkdir -p data logs
echo -e "${BLUE}  ✓ Directories created${NC}"

# Step 7: Set permissions
echo -e "${GREEN}[7/8] Setting permissions...${NC}"
# Check if user exists, if not use current user
if id "$SERVICE_USER" &>/dev/null; then
    chown -R "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR"
    echo -e "${BLUE}  ✓ Ownership set to $SERVICE_USER:$SERVICE_GROUP${NC}"
else
    echo -e "${YELLOW}  ! User $SERVICE_USER not found, keeping current permissions${NC}"
fi
chmod 755 "$INSTALL_DIR"
chmod 700 data logs

# Step 8: Install systemd service
echo -e "${GREEN}[8/8] Installing systemd service...${NC}"
if [ -f "deployment/regression-tracker.service" ]; then
    # Update service file with actual user if different
    if ! id "$SERVICE_USER" &>/dev/null; then
        echo -e "${YELLOW}  ! Updating service file to use current user${NC}"
        sed -i.bak "s/User=$SERVICE_USER/User=$(whoami)/" deployment/regression-tracker.service
        sed -i.bak "s/Group=$SERVICE_GROUP/Group=$(id -gn)/" deployment/regression-tracker.service
    fi

    cp deployment/regression-tracker.service /etc/systemd/system/
    systemctl daemon-reload
    echo -e "${BLUE}  ✓ Service installed${NC}"

    # Ask if user wants to enable and start the service
    read -p "Do you want to enable and start the service now? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        systemctl enable regression-tracker
        systemctl start regression-tracker
        echo -e "${GREEN}  ✓ Service enabled and started${NC}"
        echo ""
        echo -e "${BLUE}Service status:${NC}"
        systemctl status regression-tracker --no-pager
    else
        echo -e "${YELLOW}  To start the service manually, run:${NC}"
        echo "    sudo systemctl enable regression-tracker"
        echo "    sudo systemctl start regression-tracker"
    fi
else
    echo -e "${YELLOW}  ! Service file not found, skipping systemd installation${NC}"
fi

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}Installation Complete!${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Edit configuration: ${BLUE}$INSTALL_DIR/.env${NC}"
echo "2. Run database migration: ${BLUE}cd $INSTALL_DIR && source venv/bin/activate && alembic upgrade head${NC}"
echo "3. Manage service:"
echo "   - Start:   ${BLUE}sudo systemctl start regression-tracker${NC}"
echo "   - Stop:    ${BLUE}sudo systemctl stop regression-tracker${NC}"
echo "   - Restart: ${BLUE}sudo systemctl restart regression-tracker${NC}"
echo "   - Status:  ${BLUE}sudo systemctl status regression-tracker${NC}"
echo "   - Logs:    ${BLUE}sudo journalctl -u regression-tracker -f${NC}"
echo ""
echo -e "${GREEN}Access the application at: ${BLUE}http://localhost:8000${NC}"
echo ""
