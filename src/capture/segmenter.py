"""
FFmpeg HLS segmenter for RTSP streams.

Captures RTSP stream and outputs HLS segments (.ts) with playlist (.m3u8).
"""

import os
import shutil
import signal
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional

from ..utils.config import Config
from ..utils.exceptions import SegmentationError
from ..utils.logger import get_logger


logger = get_logger(__name__)


class Segmenter:
    """
    FFmpeg-based HLS segmenter.
    
    Captures RTSP stream and produces HLS segments with rolling playlist.
    """
    
    def __init__(
        self,
        config: Config,
        on_segment_created: Optional[Callable[[Path], None]] = None
    ):
        """
        Initialize segmenter.
        
        Args:
            config: Pipeline configuration
            on_segment_created: Callback when new segment is created
        """
        self.config = config
        self.on_segment_created = on_segment_created
        
        self._process: Optional[subprocess.Popen] = None
        self._running = False
        self._lock = threading.Lock()
        
        # Get configuration
        self.segments_dir = config.get_segments_dir()
        self.rtsp_url = config.build_rtsp_url()
        
        # Capture settings
        capture = config.get_capture_config()
        self.resolution = capture.get('resolution', '1280x720')
        self.framerate = capture.get('framerate', 15)
        self.segment_duration = capture.get('segment_duration', 10)
        self.video_codec = capture.get('video_codec', 'copy')
        self.audio_enabled = capture.get('audio_enabled', False)
        
        # Advanced settings
        advanced = config.get_advanced_config()
        self.ffmpeg_threads = advanced.get('ffmpeg_threads', 0)
        self.segment_pattern = advanced.get('segment_pattern', 'segment_%Y%m%d_%H%M%S.ts')
        self.playlist_name = advanced.get('playlist_name', 'live.m3u8')
        
        # Transport
        self.rtsp_transport = config.get('camera.rtsp_transport', 'tcp')
        
        # Verify FFmpeg is available
        if not shutil.which('ffmpeg'):
            raise SegmentationError("ffmpeg not found in PATH")
    
    @property
    def is_running(self) -> bool:
        """Check if segmenter is running."""
        with self._lock:
            return self._running and self._process is not None and self._process.poll() is None
    
    @property
    def playlist_path(self) -> Path:
        """Get path to HLS playlist."""
        return self.segments_dir / self.playlist_name
    
    def _build_ffmpeg_command(self) -> list[str]:
        """Build FFmpeg command for HLS output."""
        # Ensure segments directory exists
        self.segments_dir.mkdir(parents=True, exist_ok=True)
        
        cmd = [
            'ffmpeg',
            '-hide_banner',
            '-y',  # Overwrite output files
            
            # Input options
            '-rtsp_transport', self.rtsp_transport,
            '-timeout', '5000000',  # 5 second timeout (microseconds) - FFmpeg 8+ uses 'timeout'
            '-i', self.rtsp_url,
            
            # Video options
            '-c:v', self.video_codec,
        ]
        
        # Only add scaling if not using copy codec
        if self.video_codec != 'copy':
            width, height = self.resolution.split('x')
            cmd.extend([
                '-vf', f'scale={width}:{height}',
                '-r', str(self.framerate),
            ])
        
        # Audio handling
        if self.audio_enabled:
            cmd.extend(['-c:a', 'aac', '-b:a', '128k'])
        else:
            cmd.extend(['-an'])  # No audio
        
        # Thread count
        if self.ffmpeg_threads > 0:
            cmd.extend(['-threads', str(self.ffmpeg_threads)])
        
        # HLS output options
        cmd.extend([
            '-f', 'hls',
            '-hls_time', str(self.segment_duration),
            '-hls_list_size', '10',  # Keep 10 segments in playlist
            '-hls_flags', 'delete_segments+append_list',
            '-hls_segment_filename', str(self.segments_dir / self.segment_pattern),
            '-strftime', '1',
            str(self.playlist_path),
        ])
        
        return cmd
    
    def start(self) -> None:
        """
        Start the FFmpeg segmentation process.
        
        Raises:
            SegmentationError: If already running or FFmpeg fails to start
        """
        with self._lock:
            if self._running:
                raise SegmentationError("Segmenter already running")
            
            cmd = self._build_ffmpeg_command()
            
            # Log command (with password masked)
            safe_cmd = ' '.join(cmd).replace(
                self.config.get('camera.password', ''), 
                '****'
            )
            logger.info(f"Starting FFmpeg: {safe_cmd}")
            
            try:
                self._process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    # Use process group for clean shutdown
                    preexec_fn=os.setsid if os.name != 'nt' else None
                )
                self._running = True
                
                logger.info(f"FFmpeg started (PID: {self._process.pid})")
                
            except FileNotFoundError:
                raise SegmentationError("ffmpeg not found")
            except Exception as e:
                raise SegmentationError(f"Failed to start FFmpeg: {e}")
    
    def stop(self, timeout: int = 10) -> None:
        """
        Stop the FFmpeg process gracefully.
        
        Args:
            timeout: Seconds to wait for graceful shutdown before killing
        """
        with self._lock:
            if not self._running or self._process is None:
                return
            
            logger.info("Stopping FFmpeg...")
            
            try:
                # Send SIGINT for graceful shutdown
                if os.name != 'nt':
                    os.killpg(os.getpgid(self._process.pid), signal.SIGINT)
                else:
                    self._process.terminate()
                
                # Wait for process to exit
                try:
                    self._process.wait(timeout=timeout)
                    logger.info("FFmpeg stopped gracefully")
                except subprocess.TimeoutExpired:
                    # Force kill if not responding
                    logger.warning("FFmpeg not responding, force killing...")
                    if os.name != 'nt':
                        os.killpg(os.getpgid(self._process.pid), signal.SIGKILL)
                    else:
                        self._process.kill()
                    self._process.wait()
                    
            except ProcessLookupError:
                # Process already dead
                pass
            except Exception as e:
                logger.error(f"Error stopping FFmpeg: {e}")
            finally:
                self._running = False
                self._process = None
    
    def get_stderr(self) -> str:
        """Get FFmpeg stderr output (for debugging)."""
        if self._process and self._process.stderr:
            try:
                return self._process.stderr.read().decode('utf-8', errors='replace')
            except Exception:
                pass
        return ""
    
    def wait(self) -> int:
        """
        Wait for FFmpeg process to complete.
        
        Returns:
            Exit code of FFmpeg process
        """
        if self._process:
            return self._process.wait()
        return -1
    
    def get_exit_code(self) -> Optional[int]:
        """Get exit code if process has terminated."""
        if self._process:
            return self._process.poll()
        return None


class SegmenterManager:
    """
    Manages segmenter lifecycle with auto-restart capability.
    """
    
    def __init__(
        self,
        config: Config,
        on_segment_created: Optional[Callable[[Path], None]] = None
    ):
        """
        Initialize segmenter manager.
        
        Args:
            config: Pipeline configuration
            on_segment_created: Callback for new segments
        """
        self.config = config
        self.on_segment_created = on_segment_created
        
        self.segmenter: Optional[Segmenter] = None
        self._should_run = False
        self._restart_count = 0
        self._monitor_thread: Optional[threading.Thread] = None
    
    @property
    def is_running(self) -> bool:
        """Check if segmenter is running."""
        return self.segmenter is not None and self.segmenter.is_running
    
    @property
    def restart_count(self) -> int:
        """Get number of restarts."""
        return self._restart_count
    
    def start(self) -> None:
        """Start the segmenter with monitoring."""
        self._should_run = True
        self._restart_count = 0
        
        self.segmenter = Segmenter(self.config, self.on_segment_created)
        self.segmenter.start()
        
        # Start monitor thread
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="segmenter-monitor"
        )
        self._monitor_thread.start()
    
    def stop(self) -> None:
        """Stop the segmenter."""
        self._should_run = False
        
        if self.segmenter:
            self.segmenter.stop()
            self.segmenter = None
    
    def _monitor_loop(self) -> None:
        """Monitor FFmpeg process and restart if needed."""
        health_config = self.config.get_health_config()
        max_restarts = health_config.get('max_restarts', 10)
        restart_window = health_config.get('restart_window', 300)
        
        import time
        window_start = time.time()
        
        while self._should_run:
            time.sleep(5)  # Check every 5 seconds
            
            if not self._should_run:
                break
            
            # Reset restart counter if window passed
            if time.time() - window_start > restart_window:
                self._restart_count = 0
                window_start = time.time()
            
            # Check if process died
            if self.segmenter and not self.segmenter.is_running:
                exit_code = self.segmenter.get_exit_code()
                logger.warning(f"FFmpeg process died (exit code: {exit_code})")
                
                if self._restart_count >= max_restarts:
                    logger.error(f"Max restarts ({max_restarts}) exceeded in {restart_window}s window")
                    self._should_run = False
                    break
                
                # Restart
                self._restart_count += 1
                logger.info(f"Restarting FFmpeg (attempt {self._restart_count}/{max_restarts})")
                
                try:
                    self.segmenter = Segmenter(self.config, self.on_segment_created)
                    self.segmenter.start()
                except Exception as e:
                    logger.error(f"Failed to restart FFmpeg: {e}")
                    time.sleep(5)  # Wait before next attempt


def create_segmenter(
    config: Config,
    on_segment_created: Optional[Callable[[Path], None]] = None
) -> SegmenterManager:
    """
    Factory function to create segmenter manager.
    
    Args:
        config: Pipeline configuration
        on_segment_created: Callback for new segments
        
    Returns:
        SegmenterManager instance
    """
    return SegmenterManager(config, on_segment_created)
