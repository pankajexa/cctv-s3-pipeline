#!/bin/bash
# Install system dependencies for CCTV Pipeline
# Run with: sudo ./scripts/install.sh

set -e

echo "=========================================="
echo "CCTV Pipeline - System Dependencies Setup"
echo "=========================================="

# Check if running as root for system packages
if [ "$EUID" -ne 0 ]; then 
    echo "Please run with sudo for system packages"
    echo "Usage: sudo ./scripts/install.sh"
    exit 1
fi

echo ""
echo "[1/4] Updating package lists..."
apt update

echo ""
echo "[2/4] Installing FFmpeg..."
apt install -y ffmpeg

echo ""
echo "[3/4] Installing Python dependencies..."
apt install -y python3-pip python3-venv

echo ""
echo "[4/4] Verifying installations..."
echo ""

echo "FFmpeg version:"
ffmpeg -version | head -1

echo ""
echo "Python version:"
python3 --version

echo ""
echo "pip version:"
pip3 --version

echo ""
echo "=========================================="
echo "System dependencies installed successfully"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. cd to project directory"
echo "  2. pip3 install -r requirements.txt"
echo "  3. cp config.example.yaml config.yaml"
echo "  4. cp .env.example .env"
echo "  5. Edit config.yaml and .env with your settings"
echo ""
