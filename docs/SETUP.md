# Detailed Setup Guide

This guide walks through the complete setup process for the CCTV to S3 pipeline on Jetson Nano.

## Prerequisites

- NVIDIA Jetson Nano with JetPack installed
- CP Plus IP camera (or compatible RTSP camera)
- Ethernet connection between camera and Jetson
- AWS account with S3 access
- Internet connection for S3 uploads

---

## Step 1: Camera Network Setup

### 1.1 Physical Connection

Connect the camera to your network switch via Ethernet. The camera and Jetson should be on the same subnet.

### 1.2 Find Camera IP

```bash
# Install arp-scan if needed
sudo apt install arp-scan -y

# Scan network for the camera
# Your camera MAC: 5C:35:48:7C:C0:0B
sudo arp-scan --localnet | grep -i "5c:35:48"
```

Alternatively, check your router's DHCP lease table.

### 1.3 Access Camera Web Interface

1. Open browser: `http://<camera-ip>`
2. Login with default credentials (usually `admin`/`admin`)
3. **Change the default password immediately**
4. Navigate to Network Settings → RTSP
5. Note the RTSP URL format

### 1.4 Recommended Camera Settings

In the camera web interface, configure:

| Setting | Recommended Value |
|---------|-------------------|
| Main Stream Resolution | 2560×1440 (4MP) |
| Sub Stream Resolution | 1280×720 (we'll use this) |
| Frame Rate | 15-25 fps |
| Bitrate | 2048 kbps |
| Codec | H.264 |
| I-Frame Interval | 30 |

Consider using the **sub-stream** for this pipeline to reduce bandwidth while keeping the main stream for local NVR recording.

---

## Step 2: Jetson Nano Setup

### 2.1 System Update

```bash
sudo apt update && sudo apt upgrade -y
```

### 2.2 Install System Dependencies

```bash
cd cctv-s3-pipeline
sudo ./scripts/install.sh
```

This installs:
- FFmpeg
- Python 3 with pip

### 2.3 Install Python Dependencies

```bash
pip3 install -r requirements.txt
```

### 2.4 Verify Installations

```bash
ffmpeg -version
python3 -c "import boto3; print('boto3 OK')"
python3 -c "import watchdog; print('watchdog OK')"
```

---

## Step 3: AWS Setup

### 3.1 Create S3 Bucket

```bash
# Using AWS CLI
aws s3 mb s3://your-cctv-bucket --region ap-south-1

# Or via AWS Console:
# 1. Go to S3
# 2. Create bucket
# 3. Region: Asia Pacific (Mumbai) ap-south-1
# 4. Block all public access: Yes (keep enabled)
# 5. Versioning: Disabled
# 6. Encryption: SSE-S3
```

### 3.2 Create IAM User

1. Go to IAM → Users → Create user
2. User name: `jetson-cctv-uploader`
3. Do NOT enable console access
4. Click "Attach policies directly"
5. Click "Create policy" and use this JSON:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "CCTVBucketAccess",
            "Effect": "Allow",
            "Action": [
                "s3:PutObject",
                "s3:GetObject",
                "s3:ListBucket",
                "s3:DeleteObject"
            ],
            "Resource": [
                "arn:aws:s3:::your-cctv-bucket",
                "arn:aws:s3:::your-cctv-bucket/*"
            ]
        }
    ]
}
```

6. Name the policy: `cctv-s3-upload-policy`
7. Attach to the user

### 3.3 Generate Access Keys

1. Go to the user → Security credentials
2. Create access key → "Application running outside AWS"
3. Download or copy the credentials

### 3.4 Configure Credentials on Jetson

```bash
mkdir -p ~/.aws

cat > ~/.aws/credentials << 'EOF'
[default]
aws_access_key_id = YOUR_ACCESS_KEY_HERE
aws_secret_access_key = YOUR_SECRET_KEY_HERE
EOF

cat > ~/.aws/config << 'EOF'
[default]
region = ap-south-1
output = json
EOF

chmod 600 ~/.aws/credentials
```

### 3.5 Test S3 Access

```bash
./scripts/test_s3.sh your-cctv-bucket
```

---

## Step 4: Pipeline Configuration

### 4.1 Create Configuration Files

```bash
cp config.example.yaml config.yaml
cp .env.example .env
```

### 4.2 Edit .env

```bash
nano .env
```

Set:
```
CAMERA_PASSWORD=your_actual_camera_password
```

### 4.3 Edit config.yaml

```bash
nano config.yaml
```

Update these critical fields:

```yaml
camera:
  ip: "192.168.1.XXX"      # Your camera's IP
  username: "admin"         # Your camera username
  password: "${CAMERA_PASSWORD}"
  rtsp_path: "/cam/realmonitor?channel=1&subtype=1"  # subtype=1 for sub-stream

s3:
  bucket: "your-actual-bucket-name"
```

---

## Step 5: Test Connections

### 5.1 Test RTSP

```bash
# Load environment variables
source .env

# Run RTSP test
./scripts/test_rtsp.sh 192.168.1.XXX admin "$CAMERA_PASSWORD"
```

You should see stream information without errors.

### 5.2 Manual FFmpeg Test

```bash
# Test segmentation (Ctrl+C to stop after a few segments)
source .env
ffmpeg -rtsp_transport tcp \
  -i "rtsp://admin:${CAMERA_PASSWORD}@192.168.1.XXX:554/cam/realmonitor?channel=1&subtype=1" \
  -c:v copy -an \
  -f hls \
  -hls_time 10 \
  -hls_list_size 6 \
  -hls_flags delete_segments \
  -hls_segment_filename "data/segments/segment_%03d.ts" \
  "data/segments/live.m3u8"
```

Check `data/segments/` for `.ts` files.

---

## Step 6: Run the Pipeline

```bash
# Development mode (foreground)
python3 -m src.main --config config.yaml

# Or after implementing systemd services:
sudo systemctl start cctv-capture
sudo systemctl start cctv-uploader
```

---

## Step 7: Verify Operation

### Check Local Segments

```bash
ls -la data/segments/
```

### Check S3 Uploads

```bash
aws s3 ls s3://your-bucket/cameras/ --recursive | head -20
```

### View Live Stream

Open in VLC or browser:
```
http://<jetson-ip>:8080/live.m3u8
```

---

## Troubleshooting

### Camera not found on network
- Check Ethernet cable
- Verify camera has power (IR LEDs should glow in dark)
- Try factory reset if IP is unknown

### RTSP connection refused
- Verify port 554 is open: `nc -zv <camera-ip> 554`
- Check credentials in camera web UI
- Try different RTSP path formats

### S3 upload fails
- Run `./scripts/test_s3.sh`
- Check IAM policy resource ARN matches bucket name
- Verify network connectivity: `curl -I https://s3.ap-south-1.amazonaws.com`

### FFmpeg high CPU usage
- Use `copy` codec (no re-encoding)
- Reduce frame rate
- Use sub-stream instead of main stream

### Disk filling up
- Check cleanup job is running
- Reduce `local_buffer_minutes`
- Verify S3 uploads are succeeding

---

## Security Recommendations

1. **Change default camera password** immediately
2. **Isolate camera network** - cameras shouldn't have internet access directly
3. **Use IAM roles** instead of access keys if running on EC2
4. **Enable S3 bucket logging** for audit trail
5. **Encrypt credentials** at rest on Jetson
6. **Regular updates** - keep JetPack and packages updated
