#!/bin/bash

# Installation script for kismet_to_queue systemd service

set -e

# Dynamically determine project and installation directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
INSTALL_DIR="${PROJECT_ROOT}"

SERVICE_NAME="kismet_to_queue"
SERVICE_FILE="${SERVICE_NAME}.service"
SYSTEMD_DIR="/etc/systemd/system"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Installing ${SERVICE_NAME} systemd service...${NC}"

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}This script must be run as root (use sudo)${NC}"
   exit 1
fi

# Check if service file exists
if [[ ! -f "${PROJECT_ROOT}/systemd/${SERVICE_FILE}" ]]; then
    echo -e "${RED}Service file ${SERVICE_FILE} not found in ${PROJECT_ROOT}/systemd/${NC}"
    exit 1
fi

# Check if Python script exists and is executable
if [[ ! -x "${PROJECT_ROOT}/src/kismet_to_queue.py" ]]; then
    echo -e "${YELLOW}Making kismet_to_queue.py executable...${NC}"
    chmod +x "${PROJECT_ROOT}/src/kismet_to_queue.py"
fi

# Create dedicated system user
echo -e "${GREEN}Creating dedicated system user 'kismet-queuer'...${NC}"
if ! id -u kismet-queuer &> /dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin kismet-queuer
    echo -e "${GREEN}✓ User 'kismet-queuer' created${NC}"
else
    echo -e "${YELLOW}User 'kismet-queuer' already exists${NC}"
fi

# Check if config file exists
if [[ ! -f "${PROJECT_ROOT}/config/config.ini" ]]; then
    echo -e "${YELLOW}config.ini not found. Copying from config.ini.example...${NC}"
    if [[ -f "${PROJECT_ROOT}/config/config.ini.example" ]]; then
        cp "${PROJECT_ROOT}/config/config.ini.example" "${PROJECT_ROOT}/config/config.ini"
        echo -e "${YELLOW}Please edit ${PROJECT_ROOT}/config/config.ini with your settings${NC}"
    else
        echo -e "${RED}config.ini.example not found. Please create config.ini manually${NC}"
        exit 1
    fi
fi

# Set ownership and permissions
# Only the config file is owned by the service user; project source stays
# owned by root so a compromised service user cannot modify its own code.
echo -e "${GREEN}Setting ownership and permissions...${NC}"
chown root:kismet-queuer "${PROJECT_ROOT}/config/config.ini"
chmod 640 "${PROJECT_ROOT}/config/config.ini"
# Ensure source files are readable but not writable by the service user
chmod 644 "${PROJECT_ROOT}/src/kismet_to_queue.py"
echo -e "${GREEN}✓ Config file owned by root:kismet-queuer with mode 640${NC}"
echo -e "${GREEN}✓ Source files remain owned by root (read-only for service user)${NC}"

# Install dependencies
echo -e "${GREEN}Installing Python dependencies...${NC}"
if command -v pip3 &> /dev/null; then
    pip3 install -r "${PROJECT_ROOT}/src/requirements.txt"
else
    echo -e "${RED}pip3 not found. Please install Python 3 and pip3${NC}"
    exit 1
fi

# Copy service file to systemd directory with dynamic paths
echo -e "${GREEN}Installing service file...${NC}"
sed "s|/opt/kismet-queuer|${INSTALL_DIR}|g" "${PROJECT_ROOT}/systemd/${SERVICE_FILE}" > "${SYSTEMD_DIR}/${SERVICE_FILE}"
echo -e "${GREEN}✓ Service file installed with paths updated to: ${INSTALL_DIR}${NC}"

# Reload systemd daemon
echo -e "${GREEN}Reloading systemd daemon...${NC}"
systemctl daemon-reload

# Enable the service
echo -e "${GREEN}Enabling ${SERVICE_NAME} service...${NC}"
systemctl enable "${SERVICE_NAME}"

# Start the service
echo -e "${GREEN}Starting ${SERVICE_NAME} service...${NC}"
systemctl start "${SERVICE_NAME}"

# Check service status
echo -e "${GREEN}Checking service status...${NC}"
sleep 2
if systemctl is-active --quiet "${SERVICE_NAME}"; then
    echo -e "${GREEN}✓ ${SERVICE_NAME} service is running successfully!${NC}"
else
    echo -e "${RED}✗ ${SERVICE_NAME} service failed to start${NC}"
    echo -e "${YELLOW}Check status with: systemctl status ${SERVICE_NAME}${NC}"
    echo -e "${YELLOW}Check logs with: journalctl -u ${SERVICE_NAME} -f${NC}"
    exit 1
fi

echo -e "${GREEN}Installation complete!${NC}"
echo -e "${YELLOW}Useful commands:${NC}"
echo -e "  Status: systemctl status ${SERVICE_NAME}"
echo -e "  Logs:   journalctl -u ${SERVICE_NAME} -f"
echo -e "  Restart: systemctl restart ${SERVICE_NAME}"
echo -e "  Stop:   systemctl stop ${SERVICE_NAME}"
echo -e "  Disable: systemctl disable ${SERVICE_NAME}"