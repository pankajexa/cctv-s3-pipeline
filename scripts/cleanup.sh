#!/bin/bash
# Manual cleanup of local segments
# Normally handled automatically by the pipeline
# Usage: ./scripts/cleanup.sh [segments_dir] [keep_minutes]

SEGMENTS_DIR="${1:-./data/segments}"
KEEP_MINUTES="${2:-30}"

echo "=========================================="
echo "Local Segments Cleanup"
echo "=========================================="
echo ""
echo "Directory: ${SEGMENTS_DIR}"
echo "Keeping segments newer than: ${KEEP_MINUTES} minutes"
echo ""

if [ ! -d "${SEGMENTS_DIR}" ]; then
    echo "Directory does not exist: ${SEGMENTS_DIR}"
    exit 1
fi

# Count files before
BEFORE=$(find "${SEGMENTS_DIR}" -name "*.ts" -type f | wc -l)
echo "Segments before cleanup: ${BEFORE}"

# Delete old segments
DELETED=$(find "${SEGMENTS_DIR}" -name "*.ts" -type f -mmin +${KEEP_MINUTES} -delete -print | wc -l)

# Count files after
AFTER=$(find "${SEGMENTS_DIR}" -name "*.ts" -type f | wc -l)

echo "Segments deleted: ${DELETED}"
echo "Segments remaining: ${AFTER}"

# Show disk usage
echo ""
echo "Current disk usage:"
du -sh "${SEGMENTS_DIR}"
echo ""
