"""
Tests for database operations.
"""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path
import pytest

from src.state.database import Database
from src.state.models import Segment, SegmentState


class TestDatabase:
    """Test SQLite database operations."""
    
    @pytest.fixture
    def db(self, tmp_path):
        """Create a temporary database."""
        db_path = tmp_path / "test.db"
        database = Database(db_path)
        yield database
        database.close()
    
    @pytest.fixture
    def sample_segment(self, tmp_path):
        """Create a sample segment for testing."""
        filepath = tmp_path / "segment_001.ts"
        filepath.write_bytes(b"test video content")
        
        return Segment(
            filename="segment_001.ts",
            filepath=filepath
        )
    
    def test_database_creation(self, db):
        """Test database is created successfully."""
        assert db.db_path.exists()
    
    def test_add_segment(self, db, sample_segment):
        """Test adding a segment."""
        db.add_segment(sample_segment)
        
        assert sample_segment.id is not None
        assert sample_segment.id > 0
    
    def test_get_segment_by_filename(self, db, sample_segment):
        """Test retrieving segment by filename."""
        db.add_segment(sample_segment)
        
        retrieved = db.get_segment_by_filename("segment_001.ts")
        
        assert retrieved is not None
        assert retrieved.filename == sample_segment.filename
        assert retrieved.id == sample_segment.id
    
    def test_get_segment_by_id(self, db, sample_segment):
        """Test retrieving segment by ID."""
        db.add_segment(sample_segment)
        
        retrieved = db.get_segment_by_id(sample_segment.id)
        
        assert retrieved is not None
        assert retrieved.id == sample_segment.id
    
    def test_update_segment(self, db, sample_segment):
        """Test updating a segment."""
        db.add_segment(sample_segment)
        
        sample_segment.mark_uploading()
        db.update_segment(sample_segment)
        
        retrieved = db.get_segment_by_id(sample_segment.id)
        assert retrieved.state == SegmentState.UPLOADING
        assert retrieved.upload_attempts == 1
    
    def test_get_segments_by_state(self, db, tmp_path):
        """Test filtering segments by state."""
        # Create multiple segments with different states
        for i in range(5):
            filepath = tmp_path / f"segment_{i:03d}.ts"
            filepath.write_bytes(b"content")
            segment = Segment(filename=f"segment_{i:03d}.ts", filepath=filepath)
            
            if i < 3:
                segment.state = SegmentState.CREATED
            else:
                segment.state = SegmentState.UPLOADED
            
            db.add_segment(segment)
        
        created = db.get_segments_by_state(SegmentState.CREATED)
        uploaded = db.get_segments_by_state(SegmentState.UPLOADED)
        
        assert len(created) == 3
        assert len(uploaded) == 2
    
    def test_get_pending_segments(self, db, sample_segment):
        """Test getting pending segments."""
        db.add_segment(sample_segment)
        
        pending = db.get_pending_segments()
        
        assert len(pending) == 1
        assert pending[0].filename == sample_segment.filename
    
    def test_count_by_state(self, db, tmp_path):
        """Test counting segments by state."""
        for i in range(3):
            filepath = tmp_path / f"seg_{i}.ts"
            filepath.write_bytes(b"x")
            segment = Segment(filename=f"seg_{i}.ts", filepath=filepath)
            db.add_segment(segment)
        
        counts = db.count_by_state()
        
        assert counts.get('created', 0) == 3
    
    def test_reset_uploading_segments(self, db, sample_segment):
        """Test resetting stuck uploading segments."""
        sample_segment.state = SegmentState.UPLOADING
        db.add_segment(sample_segment)
        
        reset_count = db.reset_uploading_segments()
        
        assert reset_count == 1
        
        retrieved = db.get_segment_by_id(sample_segment.id)
        assert retrieved.state == SegmentState.CREATED
    
    def test_get_total_pending_size(self, db, tmp_path):
        """Test calculating total pending size."""
        for i in range(3):
            filepath = tmp_path / f"size_{i}.ts"
            filepath.write_bytes(b"x" * 1000)  # 1000 bytes each
            segment = Segment(filename=f"size_{i}.ts", filepath=filepath)
            db.add_segment(segment)
        
        total = db.get_total_pending_size()
        
        assert total == 3000
    
    def test_segment_not_found(self, db):
        """Test behavior when segment not found."""
        result = db.get_segment_by_filename("nonexistent.ts")
        assert result is None
        
        result = db.get_segment_by_id(99999)
        assert result is None
    
    def test_unique_filename_constraint(self, db, sample_segment):
        """Test that duplicate filenames raise error."""
        from src.utils.exceptions import DatabaseError
        
        db.add_segment(sample_segment)
        
        # Try to add same filename again
        duplicate = Segment(
            filename=sample_segment.filename,
            filepath=sample_segment.filepath
        )
        
        with pytest.raises(DatabaseError):
            db.add_segment(duplicate)
