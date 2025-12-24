"""
Data models for the CCTV to S3 Pipeline.

Defines segment states and data structures.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


class SegmentState(Enum):
    """States a segment can be in during its lifecycle."""
    
    CREATED = "created"       # Segment file created, not yet uploaded
    UPLOADING = "uploading"   # Upload in progress
    UPLOADED = "uploaded"     # Successfully uploaded to S3
    FAILED = "failed"         # Upload failed after max retries
    CLEANED = "cleaned"       # Local file deleted after successful upload


@dataclass
class Segment:
    """
    Represents a video segment file.
    
    Tracks the segment through its lifecycle from creation to cleanup.
    """
    
    # File identification
    filename: str
    filepath: Path
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    uploaded_at: Optional[datetime] = None
    
    # State tracking
    state: SegmentState = SegmentState.CREATED
    upload_attempts: int = 0
    last_error: Optional[str] = None
    
    # S3 information
    s3_key: Optional[str] = None
    s3_bucket: Optional[str] = None
    file_size: int = 0
    
    # Database ID (set when loaded from DB)
    id: Optional[int] = None
    
    def __post_init__(self):
        """Initialize computed fields."""
        if isinstance(self.filepath, str):
            self.filepath = Path(self.filepath)
        
        if isinstance(self.state, str):
            self.state = SegmentState(self.state)
        
        # Get file size if file exists
        if self.filepath.exists() and self.file_size == 0:
            self.file_size = self.filepath.stat().st_size
    
    def to_dict(self) -> dict:
        """Convert to dictionary for database storage."""
        return {
            'filename': self.filename,
            'filepath': str(self.filepath),
            'created_at': self.created_at.isoformat(),
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
            'state': self.state.value,
            'upload_attempts': self.upload_attempts,
            'last_error': self.last_error,
            's3_key': self.s3_key,
            's3_bucket': self.s3_bucket,
            'file_size': self.file_size,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Segment':
        """Create Segment from dictionary (database row)."""
        return cls(
            id=data.get('id'),
            filename=data['filename'],
            filepath=Path(data['filepath']),
            created_at=datetime.fromisoformat(data['created_at']),
            uploaded_at=datetime.fromisoformat(data['uploaded_at']) if data.get('uploaded_at') else None,
            state=SegmentState(data['state']),
            upload_attempts=data.get('upload_attempts', 0),
            last_error=data.get('last_error'),
            s3_key=data.get('s3_key'),
            s3_bucket=data.get('s3_bucket'),
            file_size=data.get('file_size', 0),
        )
    
    @classmethod
    def from_file(cls, filepath: Path) -> 'Segment':
        """Create Segment from an existing file."""
        return cls(
            filename=filepath.name,
            filepath=filepath,
            created_at=datetime.now(),
        )
    
    def mark_uploading(self) -> None:
        """Mark segment as currently uploading."""
        self.state = SegmentState.UPLOADING
        self.upload_attempts += 1
    
    def mark_uploaded(self, s3_key: str, s3_bucket: str) -> None:
        """Mark segment as successfully uploaded."""
        self.state = SegmentState.UPLOADED
        self.uploaded_at = datetime.now()
        self.s3_key = s3_key
        self.s3_bucket = s3_bucket
        self.last_error = None
    
    def mark_failed(self, error: str) -> None:
        """Mark segment as failed with error message."""
        self.state = SegmentState.FAILED
        self.last_error = error
    
    def mark_cleaned(self) -> None:
        """Mark segment as cleaned (local file deleted)."""
        self.state = SegmentState.CLEANED
    
    def can_retry(self, max_retries: int) -> bool:
        """Check if segment can be retried for upload."""
        return self.upload_attempts < max_retries
    
    def is_pending(self) -> bool:
        """Check if segment is pending upload."""
        return self.state in (SegmentState.CREATED, SegmentState.UPLOADING)
    
    @property
    def age_seconds(self) -> float:
        """Get age of segment in seconds."""
        return (datetime.now() - self.created_at).total_seconds()


@dataclass
class HealthStatus:
    """Health status of the pipeline components."""
    
    capture_running: bool = False
    upload_running: bool = False
    server_running: bool = False
    
    last_segment_time: Optional[datetime] = None
    segments_pending: int = 0
    segments_failed: int = 0
    
    disk_usage_mb: float = 0.0
    disk_limit_mb: float = 0.0
    
    ffmpeg_restarts: int = 0
    upload_errors: int = 0
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON response."""
        return {
            'capture_running': self.capture_running,
            'upload_running': self.upload_running,
            'server_running': self.server_running,
            'last_segment_time': self.last_segment_time.isoformat() if self.last_segment_time else None,
            'segments_pending': self.segments_pending,
            'segments_failed': self.segments_failed,
            'disk_usage_mb': round(self.disk_usage_mb, 2),
            'disk_limit_mb': self.disk_limit_mb,
            'ffmpeg_restarts': self.ffmpeg_restarts,
            'upload_errors': self.upload_errors,
            'healthy': self.is_healthy,
        }
    
    @property
    def is_healthy(self) -> bool:
        """Check if pipeline is healthy."""
        return (
            self.capture_running and
            self.upload_running and
            self.disk_usage_mb < self.disk_limit_mb * 0.9  # <90% disk usage
        )
