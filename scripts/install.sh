#!/usr/bin/env bash
# SWEEPERZERO Installation Script
# Installs dependencies for RF/Wi-Fi/BLE/GSM surveillance detection

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}SWEEPERZERO Installation Script${NC}"
echo "=================================="
echo ""

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}This script must be run as root (use sudo)${NC}" 
   exit 1
fi

echo "Updating package lists..."
apt-get update

echo ""
echo "Installing base dependencies..."
apt-get install -y \
  git \
  build-essential \
  cmake \
  pkg-config \
  python3 \
  python3-venv \
  python3-pip \
  python3-dev \
  libusb-1.0-0-dev \
  curl \
  wget

echo ""
echo "Installing SDR and RF tools..."

# RTL-SDR
echo "  - RTL-SDR (Software Defined Radio)"
apt-get install -y rtl-sdr

# HackRF
echo "  - HackRF"
apt-get install -y hackrf

# BladeRF (best effort - may need manual installation)
echo "  - BladeRF"
apt-get install -y bladerf || {
    echo -e "${YELLOW}    BladeRF not available in repositories.${NC}"
    echo "    Install manually from: https://github.com/Nuand/bladeRF"
}

# GNU Radio (needed for gr-gsm)
echo "  - GNU Radio"
apt-get install -y gnuradio || {
    echo -e "${YELLOW}    GNU Radio not available. GSM scanning will be limited.${NC}"
}

# gr-gsm (GSM scanner, may not be in all repositories)
echo "  - gr-gsm (GSM scanner)"
apt-get install -y gr-gsm || {
    echo -e "${YELLOW}    gr-gsm not available in repositories.${NC}"
    echo "    Install manually from: https://github.com/ptrkrysik/gr-gsm"
}

echo ""
echo "Installing Wi-Fi tools..."
apt-get install -y \
  aircrack-ng \
  wireshark \
  tshark \
  tcpdump \
  iw \
  wireless-tools

echo ""
echo "Installing BLE tools..."
apt-get install -y \
  bluez \
  bluez-hcidump

# Ubertooth (may not be in all repositories)
echo "  - Ubertooth"
apt-get install -y ubertooth || {
    echo -e "${YELLOW}    Ubertooth not available in repositories.${NC}"
    echo "    Install manually from: https://github.com/greatscottgadgets/ubertooth"
}

echo ""
echo "Installing GPS tools..."
apt-get install -y \
  gpsd \
  gpsd-clients

echo ""
echo "Installing Python dependencies..."
pip3 install --upgrade pip

# Install package from current directory or /opt/tscm
if [ -f "pyproject.toml" ]; then
    pip3 install -e .
elif [ -d "/opt/tscm" ]; then
    pip3 install -e /opt/tscm
else
    echo -e "${YELLOW}    Could not install tscm package.${NC}"
    echo "    Run 'pip3 install -e .' from the SWEEPERZERO directory"
fi

echo ""
echo -e "${GREEN}Installation complete!${NC}"
echo ""
echo "Next steps:"
echo "  1. Run 'tscm init' to create configuration file"
echo "  2. Edit config.yaml to customize settings"
echo "  3. Run 'tscm preflight' to verify device availability"
echo ""
echo "Optional: Configure udev rules for non-root access"
echo "  See: docs/DEVICE_SETUP.md"
echo ""
echo "Note: Some tools may require additional setup:"
echo "  - RTL-SDR: May need to blacklist DVB-T drivers"
echo "  - HackRF/BladeRF: May need firmware updates"
echo "  - Wi-Fi: Need monitor mode capable adapter"
echo "  - Ubertooth: May need firmware flash"
echo ""
