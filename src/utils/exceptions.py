"""
Custom exceptions for the CCTV to S3 Pipeline.
"""


class PipelineError(Exception):
    """Base exception for all pipeline errors."""
    pass


class ConfigurationError(PipelineError):
    """Raised when configuration is invalid or missing."""
    pass


class CaptureError(PipelineError):
    """Raised when RTSP capture or FFmpeg operations fail."""
    pass


class RTSPConnectionError(CaptureError):
    """Raised when RTSP connection to camera fails."""
    pass


class SegmentationError(CaptureError):
    """Raised when FFmpeg segmentation fails."""
    pass


class UploadError(PipelineError):
    """Raised when S3 upload operations fail."""
    pass


class RetryExhaustedError(UploadError):
    """Raised when all retry attempts have been exhausted."""
    
    def __init__(self, message: str, attempts: int):
        super().__init__(message)
        self.attempts = attempts


class DatabaseError(PipelineError):
    """Raised when SQLite database operations fail."""
    pass


class HealthCheckError(PipelineError):
    """Raised when health check detects critical issues."""
    pass


class DiskSpaceError(PipelineError):
    """Raised when disk space is critically low."""
    pass
