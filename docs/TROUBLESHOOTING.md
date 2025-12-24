# Troubleshooting Guide

Common issues and their solutions for the CCTV to S3 pipeline.

---

## Camera Issues

### Camera not responding to ping

**Symptoms:**
- `ping <camera-ip>` times out
- Cannot access web interface

**Solutions:**
1. Check physical Ethernet connection
2. Verify camera has power (look for LED indicators)
3. Connect camera directly to laptop to verify it works
4. Try factory reset (check manual for reset button location)
5. Check if camera and Raspberry Pi are on same subnet

### RTSP stream not accessible

**Symptoms:**
- `ffprobe` hangs or times out
- "Connection refused" errors

**Solutions:**
1. Verify RTSP is enabled in camera settings
2. Check port 554 is open:
   ```bash
   nc -zv <camera-ip> 554
   ```
3. Try different RTSP URL formats:
   ```
   rtsp://user:pass@ip:554/cam/realmonitor?channel=1&subtype=0
   rtsp://user:pass@ip:554/Streaming/Channels/101
   rtsp://user:pass@ip:554/h264/ch1/main/av_stream
   ```
4. Use TCP transport instead of UDP:
   ```bash
   ffplay -rtsp_transport tcp "rtsp://..."
   ```
5. Check camera concurrent connection limits

### Stream quality issues

**Symptoms:**
- Choppy video
- Artifacts or corruption
- High latency

**Solutions:**
1. Use TCP transport (more reliable than UDP)
2. Reduce resolution or bitrate in camera settings
3. Check network bandwidth:
   ```bash
   iperf3 -c <camera-ip>
   ```
4. Use wired Ethernet (not WiFi)
5. Check for packet loss:
   ```bash
   ping -c 100 <camera-ip> | grep loss
   ```

---

## FFmpeg Issues

### High CPU usage

**Symptoms:**
- CPU at 100%
- System becomes unresponsive
- Dropped frames

**Solutions:**
1. Use `-c:v copy` to avoid re-encoding:
   ```bash
   ffmpeg -i rtsp://... -c:v copy -c:a copy output.ts
   ```
2. Use camera's sub-stream (lower resolution)
3. Reduce frame rate:
   ```bash
   ffmpeg -i rtsp://... -r 15 output.ts
   ```
4. Disable audio:
   ```bash
   ffmpeg -i rtsp://... -an output.ts
   ```

### FFmpeg crashes or exits

**Symptoms:**
- Process terminates unexpectedly
- "Connection reset by peer"
- Segmentation fault

**Solutions:**
1. Add reconnect options:
   ```bash
   ffmpeg -rtsp_transport tcp \
     -rtsp_flags prefer_tcp \
     -stimeout 5000000 \
     -i "rtsp://..." \
     ...
   ```
2. Check available disk space:
   ```bash
   df -h
   ```
3. Check memory usage:
   ```bash
   free -h
   ```
4. Review FFmpeg logs for specific errors
5. Update FFmpeg to latest version

### Segments not creating

**Symptoms:**
- Empty segments directory
- Only playlist file, no .ts files

**Solutions:**
1. Verify write permissions:
   ```bash
   touch data/segments/test.txt && rm data/segments/test.txt
   ```
2. Check FFmpeg command output for errors
3. Verify input stream is valid:
   ```bash
   ffprobe -v error rtsp://...
   ```

---

## S3 Issues

### Upload failures

**Symptoms:**
- "Access Denied" errors
- Segments accumulating locally

**Solutions:**
1. Verify credentials:
   ```bash
   aws sts get-caller-identity
   ```
2. Check IAM policy has correct bucket ARN
3. Test basic upload:
   ```bash
   echo "test" > /tmp/test.txt
   aws s3 cp /tmp/test.txt s3://your-bucket/test.txt
   ```
4. Check network connectivity:
   ```bash
   curl -I https://s3.ap-south-1.amazonaws.com
   ```
5. Verify bucket exists and region is correct

### Slow uploads

**Symptoms:**
- Upload queue growing
- High latency to S3

**Solutions:**
1. Check internet bandwidth:
   ```bash
   speedtest-cli
   ```
2. Use S3 Transfer Acceleration (additional cost)
3. Consider regional endpoint if closer
4. Reduce segment quality/size
5. Use multipart upload for large segments

### "NoSuchBucket" error

**Solutions:**
1. Verify bucket name (exact spelling, no typos)
2. Check region matches:
   ```bash
   aws s3api get-bucket-location --bucket your-bucket
   ```
3. Ensure bucket was created successfully

---

## Disk Space Issues

### Disk filling up

**Symptoms:**
- "No space left on device"
- System slowdown

**Solutions:**
1. Check current usage:
   ```bash
   df -h
   du -sh data/segments/
   ```
2. Manual cleanup:
   ```bash
   ./scripts/cleanup.sh ./data/segments 10
   ```
3. Reduce `local_buffer_minutes` in config
4. Check if uploads are succeeding (segments should be deleted after upload)
5. Clear old logs:
   ```bash
   > data/logs/pipeline.log
   ```

### SD card performance degradation

**Symptoms:**
- Slow write speeds over time
- I/O errors in logs

**Solutions:**
1. Use high-endurance SD card (designed for continuous write)
2. Consider USB SSD for data directory
3. Monitor SD card health
4. Reduce write frequency (longer segments)

---

## Network Issues

### Intermittent connectivity

**Symptoms:**
- Uploads fail randomly
- Stream disconnects periodically

**Solutions:**
1. Check for network congestion
2. Use static IP for camera (avoid DHCP lease expiry)
3. Implement connection retry logic
4. Monitor network quality:
   ```bash
   mtr <camera-ip>
   ```

### DNS resolution failures

**Symptoms:**
- "Could not resolve host"
- S3 uploads fail intermittently

**Solutions:**
1. Use IP addresses instead of hostnames for camera
2. Configure reliable DNS:
   ```bash
   sudo nano /etc/resolv.conf
   # Add: nameserver 8.8.8.8
   ```
3. Check DNS resolution:
   ```bash
   nslookup s3.ap-south-1.amazonaws.com
   ```

---

## Service/Systemd Issues

### Service won't start

**Symptoms:**
- `systemctl status` shows failed
- Service exits immediately

**Solutions:**
1. Check logs:
   ```bash
   journalctl -u cctv-capture -n 50
   ```
2. Verify paths in service file are absolute
3. Check user permissions
4. Run manually first to see errors:
   ```bash
   python3 -m src.main
   ```

### Service not starting on boot

**Solutions:**
1. Enable the service:
   ```bash
   sudo systemctl enable cctv-capture
   ```
2. Check for dependency issues:
   ```bash
   systemctl list-dependencies cctv-capture
   ```
3. Add network dependency to service file:
   ```ini
   After=network-online.target
   Wants=network-online.target
   ```

---

## Getting Help

If you can't resolve an issue:

1. **Collect logs:**
   ```bash
   journalctl -u cctv-capture --since "1 hour ago" > capture.log
   cat data/logs/pipeline.log > pipeline.log
   ```

2. **System info:**
   ```bash
   uname -a
   ffmpeg -version
   python3 --version
   df -h
   free -h
   ```

3. **Test components individually:**
   - RTSP: `./scripts/test_rtsp.sh`
   - S3: `./scripts/test_s3.sh`
   - FFmpeg: manual command

4. **Check for similar issues** in project issues/discussions
