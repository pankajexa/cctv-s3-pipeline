"""
Local buffer management for video segments.

Watches for new segments and queues them for upload.
Uses watchdog for filesystem monitoring.
"""

import time
from datetime import datetime
from pathlib import Path
from threading import Thread, Event
from typing import Callable, Optional

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent

from ..utils.config import Config
from ..utils.exceptions import DiskSpaceError
from ..utils.logger import get_logger
from ..state.models import Segment, SegmentState
from ..state.database import Database


logger = get_logger(__name__)


class SegmentEventHandler(FileSystemEventHandler):
    """
    Handles filesystem events for new segment files.
    """
    
    def __init__(
        self,
        on_segment_created: Callable[[Path], None],
        pattern: str = '*.ts'
    ):
        """
        Initialize event handler.
        
        Args:
            on_segment_created: Callback when new .ts segment is created
            pattern: File pattern to match
        """
        super().__init__()
        self.on_segment_created = on_segment_created
        self.pattern = pattern
    
    def on_created(self, event: FileCreatedEvent) -> None:
        """Handle file creation events."""
        if event.is_directory:
            return
        
        path = Path(event.src_path)
        
        # Only process .ts files
        if path.suffix.lower() != '.ts':
            return
        
        # Wait a moment for file to be fully written
        time.sleep(0.5)
        
        if path.exists():
            logger.debug(f"New segment detected: {path.name}")
            self.on_segment_created(path)


class LocalBuffer:
    """
    Manages local segment buffer with file watching and disk management.
    
    Features:
    - Watches for new .ts segments
    - Registers them in database
    - Monitors disk usage
    - Cleans up old uploaded segments
    """
    
    def __init__(
        self,
        config: Config,
        database: Database,
        on_new_segment: Optional[Callable[[Segment], None]] = None
    ):
        """
        Initialize local buffer manager.
        
        Args:
            config: Pipeline configuration
            database: Database for segment tracking
            on_new_segment: Callback when new segment is ready for upload
        """
        self.config = config
        self.database = database
        self.on_new_segment = on_new_segment
        
        # Storage configuration
        storage_config = config.get_storage_config()
        self.segments_dir = config.get_segments_dir()
        self.local_buffer_minutes = storage_config.get('local_buffer_minutes', 30)
        self.max_disk_usage_mb = storage_config.get('max_disk_usage_mb', 2000)
        
        # Watchdog observer
        self._observer: Optional[Observer] = None
        self._stop_event = Event()
        self._cleanup_thread: Optional[Thread] = None
        
        # Stats
        self._segments_processed = 0
    
    @property
    def segments_processed(self) -> int:
        """Get total segments processed."""
        return self._segments_processed
    
    def start(self) -> None:
        """Start watching for new segments."""
        # Ensure segments directory exists
        self.segments_dir.mkdir(parents=True, exist_ok=True)
        
        # Create event handler
        handler = SegmentEventHandler(self._handle_new_segment)
        
        # Create and start observer
        self._observer = Observer()
        self._observer.schedule(
            handler,
            str(self.segments_dir),
            recursive=False
        )
        self._observer.start()
        
        # Start cleanup thread
        self._stop_event.clear()
        self._cleanup_thread = Thread(
            target=self._cleanup_loop,
            daemon=True,
            name="buffer-cleanup"
        )
        self._cleanup_thread.start()
        
        logger.info(f"Local buffer watching: {self.segments_dir}")
        
        # Process any existing segments
        self._process_existing_segments()
    
    def stop(self) -> None:
        """Stop watching and cleanup."""
        self._stop_event.set()
        
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
        
        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=5)
            self._cleanup_thread = None
        
        logger.info(f"Local buffer stopped (processed: {self._segments_processed})")
    
    def _handle_new_segment(self, path: Path) -> None:
        """
        Handle a new segment file.
        
        Args:
            path: Path to new segment file
        """
        try:
            # Check if already in database
            existing = self.database.get_segment_by_filename(path.name)
            if existing:
                logger.debug(f"Segment already tracked: {path.name}")
                return
            
            # Create segment record
            segment = Segment.from_file(path)
            self.database.add_segment(segment)
            
            self._segments_processed += 1
            logger.info(f"New segment registered: {path.name} ({segment.file_size} bytes)")
            
            # Notify callback
            if self.on_new_segment:
                self.on_new_segment(segment)
                
        except Exception as e:
            logger.error(f"Error processing segment {path.name}: {e}")
    
    def _process_existing_segments(self) -> None:
        """Process any existing .ts files on startup."""
        if not self.segments_dir.exists():
            return
        
        existing_files = sorted(self.segments_dir.glob('*.ts'))
        
        for path in existing_files:
            self._handle_new_segment(path)
        
        if existing_files:
            logger.info(f"Processed {len(existing_files)} existing segments")
    
    def _cleanup_loop(self) -> None:
        """Periodic cleanup of old uploaded segments."""
        while not self._stop_event.is_set():
            try:
                self._perform_cleanup()
            except Exception as e:
                logger.error(f"Cleanup error: {e}")
            
            # Wait 60 seconds between cleanup runs
            self._stop_event.wait(60)
    
    def _perform_cleanup(self) -> None:
        """Clean up old uploaded segments."""
        # Get uploaded segments older than buffer time
        segments = self.database.get_uploaded_segments(
            older_than_minutes=self.local_buffer_minutes
        )
        
        cleaned = 0
        for segment in segments:
            try:
                # Delete local file if exists
                if segment.filepath.exists():
                    segment.filepath.unlink()
                    logger.debug(f"Deleted local file: {segment.filename}")
                
                # Mark as cleaned in database
                segment.mark_cleaned()
                self.database.update_segment(segment)
                cleaned += 1
                
            except Exception as e:
                logger.warning(f"Failed to clean segment {segment.filename}: {e}")
        
        if cleaned > 0:
            logger.info(f"Cleaned up {cleaned} old segments")
        
        # Also check disk usage
        self._check_disk_usage()
        
        # Clean old database records
        self.database.cleanup_old_records(days=7)
    
    def _check_disk_usage(self) -> None:
        """Check and handle disk usage limits."""
        usage_mb = self.get_disk_usage_mb()
        
        if usage_mb > self.max_disk_usage_mb:
            logger.warning(f"Disk usage ({usage_mb:.1f}MB) exceeds limit ({self.max_disk_usage_mb}MB)")
            self._emergency_cleanup()
    
    def _emergency_cleanup(self) -> None:
        """Emergency cleanup when disk is full."""
        # Delete oldest uploaded segments first
        segments = self.database.get_segments_by_state(
            SegmentState.UPLOADED,
            limit=50
        )
        
        for segment in segments:
            if segment.filepath.exists():
                try:
                    segment.filepath.unlink()
                    segment.mark_cleaned()
                    self.database.update_segment(segment)
                    logger.warning(f"Emergency cleanup: {segment.filename}")
                except Exception as e:
                    logger.error(f"Emergency cleanup failed for {segment.filename}: {e}")
            
            # Check if we're under limit now
            if self.get_disk_usage_mb() < self.max_disk_usage_mb * 0.9:
                break
    
    def get_disk_usage_mb(self) -> float:
        """Get current disk usage in MB."""
        if not self.segments_dir.exists():
            return 0.0
        
        total = sum(
            f.stat().st_size
            for f in self.segments_dir.iterdir()
            if f.is_file()
        )
        
        return total / (1024 * 1024)
    
    def get_pending_count(self) -> int:
        """Get number of pending segments."""
        counts = self.database.count_by_state()
        return counts.get(SegmentState.CREATED.value, 0)


def create_local_buffer(
    config: Config,
    database: Database,
    on_new_segment: Optional[Callable[[Segment], None]] = None
) -> LocalBuffer:
    """
    Factory function to create local buffer manager.
    
    Args:
        config: Pipeline configuration
        database: Database for segment tracking
        on_new_segment: Callback for new segments
        
    Returns:
        LocalBuffer instance
    """
    return LocalBuffer(config, database, on_new_segment)
