#!/bin/bash
# Installation script for Regression Tracker Web Application
# This script sets up the application as a systemd service

set -e  # Exit on error

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
BACKUP_DIR=""
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Rollback function
rollback() {
    echo -e "\n${RED}Installation failed! Rolling back...${NC}"
    if [ -n "$BACKUP_DIR" ] && [ -d "$BACKUP_DIR" ]; then
        echo -e "${YELLOW}Restoring from backup: $BACKUP_DIR${NC}"
        rm -rf "$INSTALL_DIR"
        mv "$BACKUP_DIR" "$INSTALL_DIR"
        echo -e "${GREEN}Rollback complete${NC}"
    fi
    exit 1
}

# Set trap for errors
trap rollback ERR

# Step 1: Backup existing installation if it exists
echo -e "${GREEN}[1/9] Checking for existing installation...${NC}"
if [ -d "$INSTALL_DIR" ]; then
    BACKUP_DIR="${INSTALL_DIR}.backup.$(date +%Y%m%d_%H%M%S)"
    echo -e "${YELLOW}  ! Existing installation found${NC}"
    echo -e "${YELLOW}  Creating backup: $BACKUP_DIR${NC}"
    cp -r "$INSTALL_DIR" "$BACKUP_DIR"
    echo -e "${BLUE}  ✓ Backup created${NC}"
else
    echo -e "${BLUE}  ✓ No existing installation found${NC}"
fi

# Step 2: Create installation directory
echo -e "${GREEN}[2/9] Creating installation directory...${NC}"
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR" || exit 1

# Step 3: Copy application files
echo -e "${GREEN}[3/9] Copying application files...${NC}"
if [ -d "$SCRIPT_DIR/app" ]; then
    # Check if rsync is available, otherwise fall back to cp
    if command -v rsync &> /dev/null; then
        echo -e "${BLUE}  Using rsync for efficient copy...${NC}"
        rsync -av --delete \
            --exclude='.git' \
            --exclude='__pycache__' \
            --exclude='*.pyc' \
            --exclude='*.pyo' \
            --exclude='.pytest_cache' \
            --exclude='.venv' \
            --exclude='venv' \
            --exclude='*.egg-info' \
            --exclude='.env' \
            "$SCRIPT_DIR/" "$INSTALL_DIR/"
    else
        echo -e "${YELLOW}  rsync not found, using cp (install rsync for better performance)${NC}"
        cp -r "$SCRIPT_DIR/"* "$INSTALL_DIR/"
    fi
    echo -e "${BLUE}  ✓ Files copied${NC}"
else
    echo -e "${RED}  ✗ Error: Application files not found at $SCRIPT_DIR${NC}"
    exit 1
fi

# Step 4: Create virtual environment
echo -e "${GREEN}[4/9] Creating virtual environment...${NC}"
python3 -m venv venv
source venv/bin/activate
echo -e "${BLUE}  ✓ Virtual environment created${NC}"

# Step 5: Install dependencies
echo -e "${GREEN}[5/9] Installing dependencies...${NC}"
pip install --upgrade pip
pip install -r requirements.txt
echo -e "${BLUE}  ✓ Dependencies installed${NC}"

# Step 6: Setup environment file
echo -e "${GREEN}[6/9] Setting up environment file...${NC}"
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo -e "${YELLOW}  ! Please edit /opt/regression-tracker-web/.env with your configuration${NC}"
    else
        echo -e "${RED}  ✗ Error: .env.example file not found${NC}"
        echo -e "${YELLOW}  ! Continuing without .env file (can be created manually later)${NC}"
    fi
else
    echo -e "${BLUE}  ✓ .env file already exists${NC}"
fi

# Step 7: Create data directories
echo -e "${GREEN}[7/9] Creating data directories...${NC}"
mkdir -p data logs data/backups
# Verify directories were created
if [ ! -d "data" ] || [ ! -d "logs" ]; then
    echo -e "${RED}  ✗ Error: Failed to create data directories${NC}"
    exit 1
fi
echo -e "${BLUE}  ✓ Directories created (data, logs, data/backups)${NC}"

# Step 8: Set permissions
echo -e "${GREEN}[8/9] Setting permissions...${NC}"
# Set directory permissions first
chmod 755 "$INSTALL_DIR"
chmod 755 data logs data/backups
# Then set ownership (must be done after chmod for security)
if id "$SERVICE_USER" &>/dev/null; then
    chown -R "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR"
    echo -e "${BLUE}  ✓ Ownership set to $SERVICE_USER:$SERVICE_GROUP${NC}"
    echo -e "${BLUE}  ✓ Permissions set (755 for directories)${NC}"
else
    echo -e "${YELLOW}  ! User $SERVICE_USER not found, keeping current permissions${NC}"
fi

# Step 9: Install systemd service
echo -e "${GREEN}[9/9] Installing systemd service...${NC}"
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

# Disable error trap (installation successful)
trap - ERR

# Clean up backup if installation was successful
if [ -n "$BACKUP_DIR" ] && [ -d "$BACKUP_DIR" ]; then
    echo -e "\n${GREEN}Installation successful!${NC}"
    read -p "Remove backup directory? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$BACKUP_DIR"
        echo -e "${BLUE}  ✓ Backup removed${NC}"
    else
        echo -e "${YELLOW}  Backup kept at: $BACKUP_DIR${NC}"
    fi
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
