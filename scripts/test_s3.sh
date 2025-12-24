#!/bin/bash
# Test S3 connectivity and permissions
# Usage: ./scripts/test_s3.sh [bucket_name]

set -e

BUCKET="${1:-your-cctv-bucket-name}"
TEST_FILE="/tmp/s3_test_$(date +%s).txt"
TEST_KEY="test/connection_test_$(date +%s).txt"

echo "=========================================="
echo "S3 Connectivity Test"
echo "=========================================="
echo ""
echo "Bucket: ${BUCKET}"
echo "Region: $(aws configure get region)"
echo ""

# Test 1: Check AWS credentials
echo "[1/4] Checking AWS credentials..."
if aws sts get-caller-identity > /dev/null 2>&1; then
    IDENTITY=$(aws sts get-caller-identity --query 'Arn' --output text)
    echo "✓ AWS credentials valid"
    echo "  Identity: ${IDENTITY}"
else
    echo "✗ AWS credentials not configured or invalid"
    echo "  Run: aws configure"
    exit 1
fi

# Test 2: List bucket
echo ""
echo "[2/4] Testing bucket access (ListBucket)..."
if aws s3 ls "s3://${BUCKET}/" > /dev/null 2>&1; then
    echo "✓ Can list bucket contents"
else
    echo "✗ Cannot list bucket"
    echo "  Check bucket name and IAM permissions"
    exit 1
fi

# Test 3: Write test file
echo ""
echo "[3/4] Testing upload (PutObject)..."
echo "CCTV Pipeline S3 Test - $(date)" > "${TEST_FILE}"
if aws s3 cp "${TEST_FILE}" "s3://${BUCKET}/${TEST_KEY}" > /dev/null 2>&1; then
    echo "✓ Can upload to bucket"
else
    echo "✗ Cannot upload to bucket"
    echo "  Check IAM permissions for s3:PutObject"
    rm -f "${TEST_FILE}"
    exit 1
fi

# Test 4: Read test file
echo ""
echo "[4/4] Testing download (GetObject)..."
if aws s3 cp "s3://${BUCKET}/${TEST_KEY}" "${TEST_FILE}.downloaded" > /dev/null 2>&1; then
    echo "✓ Can download from bucket"
else
    echo "✗ Cannot download from bucket"
    echo "  Check IAM permissions for s3:GetObject"
fi

# Cleanup
echo ""
echo "Cleaning up test files..."
aws s3 rm "s3://${BUCKET}/${TEST_KEY}" > /dev/null 2>&1 || true
rm -f "${TEST_FILE}" "${TEST_FILE}.downloaded"

echo ""
echo "=========================================="
echo "All S3 tests passed!"
echo "=========================================="
echo ""
echo "Your Raspberry Pi can upload to s3://${BUCKET}/"
echo ""
