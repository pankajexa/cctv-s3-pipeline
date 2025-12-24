"""
Health checking for the capture pipeline.

Monitors FFmpeg process and segment generation.
"""

import time
from datetime import datetime
from pathlib import Path
from threading import Thread, Event
from typing import Callable, Optional

from ..utils.config import Config
from ..utils.exceptions import HealthCheckError
from ..utils.logger import get_logger
from ..state.models import HealthStatus
from .segmenter import SegmenterManager


logger = get_logger(__name__)


class HealthChecker:
    """
    Monitors health of the capture pipeline.
    
    Checks for:
    - FFmpeg process status
    - Stale segments (no new files)
    - Restart rate limiting
    """
    
    def __init__(
        self,
        config: Config,
        segmenter: SegmenterManager,
        on_health_issue: Optional[Callable[[str], None]] = None
    ):
        """
        Initialize health checker.
        
        Args:
            config: Pipeline configuration
            segmenter: Segmenter manager to monitor
            on_health_issue: Callback when health issue detected
        """
        self.config = config
        self.segmenter = segmenter
        self.on_health_issue = on_health_issue
        
        self.segments_dir = config.get_segments_dir()
        
        # Health settings
        health_config = config.get_health_config()
        self.check_interval = health_config.get('check_interval', 30)
        self.stale_threshold = health_config.get('stale_threshold', 30)
        
        # Status tracking
        self.last_segment_time: Optional[datetime] = None
        self.last_segment_count = 0
        self._status = HealthStatus()
        
        # Control
        self._stop_event = Event()
        self._thread: Optional[Thread] = None
    
    @property
    def status(self) -> HealthStatus:
        """Get current health status."""
        return self._status
    
    def start(self) -> None:
        """Start health check monitoring."""
        self._stop_event.clear()
        
        self._thread = Thread(
            target=self._check_loop,
            daemon=True,
            name="health-checker"
        )
        self._thread.start()
        logger.info("Health checker started")
    
    def stop(self) -> None:
        """Stop health check monitoring."""
        self._stop_event.set()
        
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        
        logger.info("Health checker stopped")
    
    def _check_loop(self) -> None:
        """Main health check loop."""
        while not self._stop_event.is_set():
            try:
                self._perform_check()
            except Exception as e:
                logger.error(f"Health check error: {e}")
            
            # Wait for next check or stop signal
            self._stop_event.wait(self.check_interval)
    
    def _perform_check(self) -> None:
        """Perform a single health check."""
        # Check capture/segmenter status
        self._status.capture_running = self.segmenter.is_running
        self._status.ffmpeg_restarts = self.segmenter.restart_count
        
        # Check for new segments
        self._check_segments()
        
        # Log status
        if not self._status.capture_running:
            logger.warning("Capture not running")
            self._report_issue("Capture process not running")
        
        elif self._is_stale():
            logger.warning(f"No new segments in {self.stale_threshold}s")
            self._report_issue(f"Stale segments - no new files in {self.stale_threshold}s")
    
    def _check_segments(self) -> None:
        """Check for new segment files."""
        if not self.segments_dir.exists():
            return
        
        # Count .ts files
        ts_files = list(self.segments_dir.glob('*.ts'))
        current_count = len(ts_files)
        
        # Find newest segment
        if ts_files:
            newest = max(ts_files, key=lambda p: p.stat().st_mtime)
            newest_time = datetime.fromtimestamp(newest.stat().st_mtime)
            
            if self.last_segment_time is None or newest_time > self.last_segment_time:
                self.last_segment_time = newest_time
                self._status.last_segment_time = newest_time
        
        self.last_segment_count = current_count
    
    def _is_stale(self) -> bool:
        """Check if segments are stale (no new files)."""
        if self.last_segment_time is None:
            # No segments yet - allow grace period
            return False
        
        age = (datetime.now() - self.last_segment_time).total_seconds()
        return age > self.stale_threshold
    
    def _report_issue(self, message: str) -> None:
        """Report a health issue."""
        if self.on_health_issue:
            self.on_health_issue(message)
    
    def get_disk_usage(self) -> float:
        """Get disk usage of segments directory in MB."""
        if not self.segments_dir.exists():
            return 0.0
        
        total = sum(
            f.stat().st_size 
            for f in self.segments_dir.iterdir() 
            if f.is_file()
        )
        
        return total / (1024 * 1024)  # Convert to MB


def create_health_checker(
    config: Config,
    segmenter: SegmenterManager,
    on_health_issue: Optional[Callable[[str], None]] = None
) -> HealthChecker:
    """
    Factory function to create health checker.
    
    Args:
        config: Pipeline configuration
        segmenter: Segmenter manager to monitor
        on_health_issue: Callback for health issues
        
    Returns:
        HealthChecker instance
    """
    return HealthChecker(config, segmenter, on_health_issue)
