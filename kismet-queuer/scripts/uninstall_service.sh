#!/bin/bash

# Uninstallation script for kismet_to_queue systemd service

set -e

SERVICE_NAME="kismet_to_queue"
SERVICE_FILE="${SERVICE_NAME}.service"
SYSTEMD_DIR="/etc/systemd/system"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Uninstalling ${SERVICE_NAME} systemd service...${NC}"

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}This script must be run as root (use sudo)${NC}"
   exit 1
fi

# Stop the service if it's running
if systemctl is-active --quiet "${SERVICE_NAME}" 2>/dev/null; then
    echo -e "${YELLOW}Stopping ${SERVICE_NAME} service...${NC}"
    systemctl stop "${SERVICE_NAME}"
fi

# Disable the service
if systemctl is-enabled --quiet "${SERVICE_NAME}" 2>/dev/null; then
    echo -e "${YELLOW}Disabling ${SERVICE_NAME} service...${NC}"
    systemctl disable "${SERVICE_NAME}"
fi

# Remove the service file
if [[ -f "${SYSTEMD_DIR}/${SERVICE_FILE}" ]]; then
    echo -e "${GREEN}Removing service file...${NC}"
    rm "${SYSTEMD_DIR}/${SERVICE_FILE}"
else
    echo -e "${YELLOW}Service file ${SERVICE_FILE} not found in ${SYSTEMD_DIR}${NC}"
fi

# Reload systemd daemon
echo -e "${GREEN}Reloading systemd daemon...${NC}"
systemctl daemon-reload

# Reset failed units if any
systemctl reset-failed "${SERVICE_NAME}" 2>/dev/null || true

echo -e "${GREEN}✓ ${SERVICE_NAME} service has been uninstalled successfully!${NC}"
echo -e "${YELLOW}Note: The application files have not been removed.${NC}"
echo -e "${YELLOW}      To remove them completely, delete the installation directory manually.${NC}"