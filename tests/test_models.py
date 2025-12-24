"""
Tests for data models.
"""

from datetime import datetime
from pathlib import Path
import pytest

from src.state.models import Segment, SegmentState, HealthStatus


class TestSegmentState:
    """Test SegmentState enum."""
    
    def test_all_states_defined(self):
        """Test all expected states exist."""
        assert SegmentState.CREATED
        assert SegmentState.UPLOADING
        assert SegmentState.UPLOADED
        assert SegmentState.FAILED
        assert SegmentState.CLEANED
    
    def test_state_values(self):
        """Test state string values."""
        assert SegmentState.CREATED.value == "created"
        assert SegmentState.UPLOADED.value == "uploaded"


class TestSegment:
    """Test Segment dataclass."""
    
    @pytest.fixture
    def sample_segment(self, tmp_path):
        """Create a sample segment."""
        # Create a dummy file
        filepath = tmp_path / "segment_test.ts"
        filepath.write_bytes(b"dummy content")
        
        return Segment(
            filename="segment_test.ts",
            filepath=filepath
        )
    
    def test_segment_creation(self, sample_segment):
        """Test basic segment creation."""
        assert sample_segment.filename == "segment_test.ts"
        assert sample_segment.state == SegmentState.CREATED
        assert sample_segment.upload_attempts == 0
        assert sample_segment.file_size > 0
    
    def test_segment_from_file(self, tmp_path):
        """Test creating segment from file path."""
        filepath = tmp_path / "new_segment.ts"
        filepath.write_bytes(b"video data")
        
        segment = Segment.from_file(filepath)
        
        assert segment.filename == "new_segment.ts"
        assert segment.filepath == filepath
        assert segment.state == SegmentState.CREATED
    
    def test_mark_uploading(self, sample_segment):
        """Test marking segment as uploading."""
        sample_segment.mark_uploading()
        
        assert sample_segment.state == SegmentState.UPLOADING
        assert sample_segment.upload_attempts == 1
    
    def test_mark_uploaded(self, sample_segment):
        """Test marking segment as uploaded."""
        sample_segment.mark_uploaded("s3/key/path", "test-bucket")
        
        assert sample_segment.state == SegmentState.UPLOADED
        assert sample_segment.s3_key == "s3/key/path"
        assert sample_segment.s3_bucket == "test-bucket"
        assert sample_segment.uploaded_at is not None
    
    def test_mark_failed(self, sample_segment):
        """Test marking segment as failed."""
        sample_segment.mark_failed("Connection timeout")
        
        assert sample_segment.state == SegmentState.FAILED
        assert sample_segment.last_error == "Connection timeout"
    
    def test_can_retry(self, sample_segment):
        """Test retry logic."""
        assert sample_segment.can_retry(max_retries=3)
        
        sample_segment.upload_attempts = 3
        assert not sample_segment.can_retry(max_retries=3)
    
    def test_is_pending(self, sample_segment):
        """Test pending check."""
        assert sample_segment.is_pending()
        
        sample_segment.state = SegmentState.UPLOADED
        assert not sample_segment.is_pending()
    
    def test_to_dict(self, sample_segment):
        """Test serialization to dict."""
        data = sample_segment.to_dict()
        
        assert data['filename'] == "segment_test.ts"
        assert data['state'] == "created"
        assert 'created_at' in data
    
    def test_from_dict(self, tmp_path):
        """Test deserialization from dict."""
        data = {
            'id': 1,
            'filename': 'test.ts',
            'filepath': str(tmp_path / 'test.ts'),
            'created_at': datetime.now().isoformat(),
            'state': 'created',
            'upload_attempts': 0,
            'file_size': 1000,
        }
        
        segment = Segment.from_dict(data)
        
        assert segment.id == 1
        assert segment.filename == 'test.ts'
        assert segment.state == SegmentState.CREATED


class TestHealthStatus:
    """Test HealthStatus dataclass."""
    
    def test_default_status(self):
        """Test default health status values."""
        status = HealthStatus()
        
        assert not status.capture_running
        assert not status.upload_running
        assert status.segments_pending == 0
        assert not status.is_healthy
    
    def test_is_healthy(self):
        """Test healthy status check."""
        status = HealthStatus(
            capture_running=True,
            upload_running=True,
            disk_usage_mb=100,
            disk_limit_mb=1000
        )
        
        assert status.is_healthy
    
    def test_not_healthy_disk_full(self):
        """Test unhealthy when disk is almost full."""
        status = HealthStatus(
            capture_running=True,
            upload_running=True,
            disk_usage_mb=950,
            disk_limit_mb=1000
        )
        
        assert not status.is_healthy
    
    def test_to_dict(self):
        """Test serialization to dict."""
        status = HealthStatus(
            capture_running=True,
            segments_pending=5
        )
        
        data = status.to_dict()
        
        assert data['capture_running'] is True
        assert data['segments_pending'] == 5
        assert 'healthy' in data
