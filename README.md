# CCTV to S3 Streaming Pipeline

A robust, production-ready pipeline for streaming CCTV footage from CP Plus IP cameras through Raspberry Pi 5 to AWS S3, with real-time viewing capabilities.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            RASPBERRY PI 5                                   │
│                                                                              │
│  ┌──────────┐    ┌───────────────┐    ┌──────────────┐    ┌──────────────┐ │
│  │  RTSP    │    │   Capture     │    │   Segment    │    │   Upload     │ │
│  │  Input   │───▶│   Service     │───▶│   Manager    │───▶│   Service    │ │
│  │          │    │  (FFmpeg)     │    │              │    │   (boto3)    │ │
│  └──────────┘    └───────────────┘    └──────────────┘    └──────────────┘ │
│                          │                    │                    │        │
│                          ▼                    ▼                    ▼        │
│                   ┌─────────────────────────────────────────────────┐       │
│                   │              State Manager (SQLite)             │       │
│                   │         segments.db - tracks all segments       │       │
│                   └─────────────────────────────────────────────────┘       │
│                                       │                                     │
│                          ┌────────────┴────────────┐                        │
│                          ▼                         ▼                        │
│                   ┌─────────────┐           ┌─────────────┐                 │
│                   │   Local     │           │   Health    │                 │
│                   │   HLS Dir   │           │   Monitor   │                 │
│                   │  /segments  │           │             │                 │
│                   └─────────────┘           └─────────────┘                 │
│                          │                         │                        │
└──────────────────────────┼─────────────────────────┼────────────────────────┘
                           │                         │
              ┌────────────┴────────────┐            │
              ▼                         ▼            ▼
       ┌─────────────┐          ┌─────────────┐  ┌──────────┐
       │  Real-time  │          │    AWS S3   │  │  Alerts  │
       │  HLS View   │          │   Archive   │  │ (future) │
       │  (port 8080)│          │             │  │          │
       └─────────────┘          └─────────────┘  └──────────┘
```

## Hardware Setup

| Component | Details |
|-----------|---------|
| Camera | CP Plus CP-UNC-TA41PL3-Y (4MP, IP67) |
| Edge Device | Raspberry Pi 5 |
| Network | Ethernet (Camera → Switch → Pi) |
| Storage | S3 bucket in ap-south-1 |

## Target Specifications

| Parameter | Value |
|-----------|-------|
| Input Resolution | 4MP (2560×1440) |
| Output Resolution | 720p (1280×720) |
| Segment Duration | 10 seconds |
| Container Format | HLS (.ts segments + .m3u8 playlist) |
| Local Buffer | Last 30 minutes (~180 segments) |
| Upload Strategy | Immediate with retry queue |

---

## Repository Structure

```
cctv-s3-pipeline/
│
├── README.md                   # This file
├── requirements.txt            # Python dependencies
├── setup.py                    # Package installation
├── config.example.yaml         # Example configuration (copy to config.yaml)
├── .env.example                # Environment variables template
├── .gitignore                  # Git ignore rules
│
├── src/
│   ├── __init__.py
│   │
│   ├── capture/                # RTSP capture and segmentation
│   │   ├── __init__.py
│   │   ├── rtsp_client.py      # RTSP connection handler
│   │   ├── segmenter.py        # FFmpeg HLS segmentation
│   │   └── health_check.py     # Stream health monitoring
│   │
│   ├── storage/                # Local and cloud storage
│   │   ├── __init__.py
│   │   ├── local_buffer.py     # Ring buffer management
│   │   ├── s3_uploader.py      # S3 upload with retry logic
│   │   └── manifest.py         # HLS manifest management
│   │
│   ├── state/                  # State management
│   │   ├── __init__.py
│   │   ├── database.py         # SQLite operations
│   │   └── models.py           # Data models
│   │
│   ├── server/                 # Local HLS server for real-time view
│   │   ├── __init__.py
│   │   └── hls_server.py       # Simple HTTP server
│   │
│   └── utils/                  # Utilities
│       ├── __init__.py
│       ├── config.py           # Configuration loader
│       ├── logger.py           # Logging setup
│       └── exceptions.py       # Custom exceptions
│
├── scripts/
│   ├── install.sh              # System dependencies installer
│   ├── test_rtsp.sh            # RTSP connection tester
│   ├── test_s3.sh              # S3 connectivity tester
│   └── cleanup.sh              # Local segment cleanup
│
├── systemd/
│   ├── cctv-capture.service    # Capture service unit
│   ├── cctv-uploader.service   # Upload service unit
│   └── cctv-server.service     # HLS server unit
│
├── tests/
│   ├── __init__.py
│   ├── test_capture.py
│   ├── test_uploader.py
│   └── test_database.py
│
├── data/                       # Runtime data (gitignored)
│   ├── segments/               # HLS segments buffer
│   ├── logs/                   # Application logs
│   └── segments.db             # SQLite state database
│
└── docs/
    ├── SETUP.md                # Detailed setup guide
    ├── TROUBLESHOOTING.md      # Common issues and fixes
    └── API.md                  # Internal API documentation
```

---

## Implementation Plan

### Phase 1: Core Infrastructure
**Goal:** Basic capture and local storage working

| Task | File(s) | Description |
|------|---------|-------------|
| 1.1 | `src/utils/config.py` | YAML config loader with validation |
| 1.2 | `src/utils/logger.py` | Structured logging to file + stdout |
| 1.3 | `src/state/models.py` | Segment dataclass with states |
| 1.4 | `src/state/database.py` | SQLite CRUD for segment tracking |
| 1.5 | `config.example.yaml` | Configuration template |

**Deliverable:** Config loads, logging works, DB initializes

---

### Phase 2: RTSP Capture
**Goal:** Camera stream captured and segmented locally

| Task | File(s) | Description |
|------|---------|-------------|
| 2.1 | `src/capture/rtsp_client.py` | RTSP URL builder, connection test |
| 2.2 | `src/capture/segmenter.py` | FFmpeg subprocess for HLS output |
| 2.3 | `src/capture/health_check.py` | Monitor FFmpeg process, auto-restart |
| 2.4 | `scripts/test_rtsp.sh` | Manual RTSP test script |

**Deliverable:** `ffmpeg` captures RTSP → outputs `.ts` + `.m3u8` to `/data/segments/`

---

### Phase 3: S3 Upload
**Goal:** Segments reliably uploaded to S3

| Task | File(s) | Description |
|------|---------|-------------|
| 3.1 | `src/storage/s3_uploader.py` | boto3 upload with multipart support |
| 3.2 | `src/storage/local_buffer.py` | Watch for new files, queue uploads |
| 3.3 | Retry logic | Exponential backoff on failures |
| 3.4 | `scripts/test_s3.sh` | S3 connectivity test |

**Deliverable:** New segments auto-upload, failed uploads retry

---

### Phase 4: State Management
**Goal:** Track every segment from creation to upload

| Task | File(s) | Description |
|------|---------|-------------|
| 4.1 | Segment states | `CREATED → UPLOADING → UPLOADED → CLEANED` |
| 4.2 | Recovery logic | On restart, resume pending uploads |
| 4.3 | Cleanup job | Delete local files after confirmed upload |

**Deliverable:** Survive restarts, no lost segments, no duplicate uploads

---

### Phase 5: Real-time Viewing
**Goal:** Watch live stream via HLS

| Task | File(s) | Description |
|------|---------|-------------|
| 5.1 | `src/server/hls_server.py` | HTTP server on port 8080 |
| 5.2 | CORS headers | Allow browser playback |
| 5.3 | Rolling playlist | Keep last N segments in playlist |

**Deliverable:** Open `http://pi-ip:8080/live.m3u8` in VLC or browser

---

### Phase 6: Production Hardening
**Goal:** Run reliably 24/7

| Task | File(s) | Description |
|------|---------|-------------|
| 6.1 | `systemd/*.service` | Auto-start on boot |
| 6.2 | Log rotation | Prevent disk fill from logs |
| 6.3 | Disk monitoring | Alert if buffer fills up |
| 6.4 | Health endpoint | `/health` JSON status |

**Deliverable:** Survives reboots, self-heals, observable

---

## Configuration Reference

```yaml
# config.yaml

camera:
  name: "warehouse-cam-01"
  ip: "192.168.1.100"
  port: 554
  username: "admin"
  password: "${CAMERA_PASSWORD}"  # From environment
  rtsp_path: "/cam/realmonitor?channel=1&subtype=0"
  
capture:
  resolution: "1280x720"
  framerate: 15
  segment_duration: 10  # seconds
  
storage:
  local_buffer_minutes: 30
  segments_dir: "./data/segments"
  
s3:
  bucket: "your-cctv-bucket"
  region: "ap-south-1"
  prefix: "cameras/{camera_name}/{date}/{hour}/"
  # Credentials from ~/.aws/credentials or IAM role

server:
  enabled: true
  port: 8080
  playlist_segments: 6  # Segments in live playlist

logging:
  level: "INFO"
  file: "./data/logs/pipeline.log"
  max_size_mb: 50
  backup_count: 5
```

---

## S3 Object Structure

```
s3://your-cctv-bucket/
└── cameras/
    └── warehouse-cam-01/
        └── 2025/
            └── 01/
                └── 15/
                    └── 14/  # Hour (24h format)
                        ├── segment_1705326000.ts
                        ├── segment_1705326010.ts
                        ├── segment_1705326020.ts
                        └── manifest.m3u8
```

---

## Segment Lifecycle

```
┌─────────┐     ┌───────────┐     ┌──────────┐     ┌─────────┐
│ CREATED │────▶│ UPLOADING │────▶│ UPLOADED │────▶│ CLEANED │
└─────────┘     └───────────┘     └──────────┘     └─────────┘
     │                │                                  │
     │                │ (failure)                        │
     │                ▼                                  │
     │          ┌──────────┐                             │
     │          │  RETRY   │──── (max retries) ─────────▶│
     │          │  QUEUE   │                      FAILED │
     │          └──────────┘                             │
     │                                                   │
     └───────────── segment on disk ─────────────────────┘
                                                   deleted
```

---

## Quick Start (After Setup)

```bash
# 1. Clone and setup
git clone <repo>
cd cctv-s3-pipeline
cp config.example.yaml config.yaml
cp .env.example .env

# 2. Edit configuration
nano config.yaml  # Add camera IP, credentials
nano .env         # Add CAMERA_PASSWORD

# 3. Install dependencies
./scripts/install.sh
pip3 install -r requirements.txt

# 4. Test connections
./scripts/test_rtsp.sh
./scripts/test_s3.sh

# 5. Run
python3 -m src.main
```

---

## Development Commands

```bash
# Run in foreground (development)
python3 -m src.main --config config.yaml

# Run individual components
python3 -m src.capture.segmenter    # Just capture
python3 -m src.storage.s3_uploader  # Just upload daemon
python3 -m src.server.hls_server    # Just HLS server

# Run tests
pytest tests/ -v

# Check logs
tail -f data/logs/pipeline.log
```

---

## Dependencies

### System (apt)
- ffmpeg
- python3-pip
- sqlite3

### Python (pip)
- boto3 >= 1.26
- watchdog >= 3.0
- pyyaml >= 6.0
- aiohttp >= 3.8 (for HLS server)
- python-dotenv >= 1.0

---

## Future Enhancements

- [ ] Motion-triggered recording (reduce storage costs)
- [ ] Thumbnail generation for timeline scrubbing
- [ ] S3 lifecycle policies (move old footage to Glacier)
- [ ] Multi-camera support
- [ ] Prometheus metrics endpoint
- [ ] Integration with AI inference results (bounding box overlays)

---

## License

MIT License - Use freely for your commercial deployment.
