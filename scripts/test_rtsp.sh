#!/bin/bash
# Test RTSP connection to camera
# Usage: ./scripts/test_rtsp.sh [camera_ip] [username] [password]

set -e

# Default values (override with arguments or edit here)
CAMERA_IP="${1:-192.168.1.100}"
USERNAME="${2:-admin}"
PASSWORD="${3:-$CAMERA_PASSWORD}"
PORT="${4:-554}"
RTSP_PATH="${5:-/cam/realmonitor?channel=1&subtype=0}"

# Build RTSP URL
RTSP_URL="rtsp://${USERNAME}:${PASSWORD}@${CAMERA_IP}:${PORT}${RTSP_PATH}"
# URL for display (hide password)
RTSP_URL_DISPLAY="rtsp://${USERNAME}:****@${CAMERA_IP}:${PORT}${RTSP_PATH}"

echo "=========================================="
echo "RTSP Connection Test"
echo "=========================================="
echo ""
echo "Camera IP: ${CAMERA_IP}"
echo "Port: ${PORT}"
echo "Username: ${USERNAME}"
echo "RTSP Path: ${RTSP_PATH}"
echo ""
echo "Full URL: ${RTSP_URL_DISPLAY}"
echo ""

# Test 1: Network connectivity
echo "[1/3] Testing network connectivity..."
if ping -c 2 "${CAMERA_IP}" > /dev/null 2>&1; then
    echo "✓ Camera IP is reachable"
else
    echo "✗ Cannot reach camera at ${CAMERA_IP}"
    echo "  Check network connection and IP address"
    exit 1
fi

# Test 2: Port open
echo ""
echo "[2/3] Testing RTSP port..."
if timeout 5 bash -c "echo > /dev/tcp/${CAMERA_IP}/${PORT}" 2>/dev/null; then
    echo "✓ RTSP port ${PORT} is open"
else
    echo "✗ RTSP port ${PORT} is not accessible"
    echo "  Check camera settings and firewall"
    exit 1
fi

# Test 3: FFmpeg probe
echo ""
echo "[3/3] Testing RTSP stream with FFmpeg..."
echo "  (will capture 5 seconds of stream info)"
echo ""

if ffprobe -v error -rtsp_transport tcp -i "${RTSP_URL}" -show_streams -show_format 2>&1 | head -30; then
    echo ""
    echo "✓ RTSP stream is accessible"
else
    echo ""
    echo "✗ Cannot access RTSP stream"
    echo "  Check username/password and RTSP path"
    exit 1
fi

echo ""
echo "=========================================="
echo "All tests passed!"
echo "=========================================="
echo ""
echo "To view the stream, run:"
echo "  ffplay -rtsp_transport tcp \"${RTSP_URL_DISPLAY}\""
echo ""
