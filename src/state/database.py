"""
SQLite database operations for the CCTV to S3 Pipeline.

Provides CRUD operations for segment tracking.
"""

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

from .models import Segment, SegmentState
from ..utils.exceptions import DatabaseError
from ..utils.logger import get_logger


logger = get_logger(__name__)


class Database:
    """
    SQLite database manager for segment tracking.
    
    Thread-safe with connection pooling per thread.
    """
    
    def __init__(self, db_path: Path):
        """
        Initialize database manager.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self._local = threading.local()
        
        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize schema
        self._init_schema()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            self._local.connection = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False
            )
            self._local.connection.row_factory = sqlite3.Row
        return self._local.connection
    
    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        """Context manager for database cursor with auto-commit."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            raise DatabaseError(f"Database operation failed: {e}")
        finally:
            cursor.close()
    
    def _init_schema(self) -> None:
        """Initialize database schema."""
        with self._cursor() as cursor:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL UNIQUE,
                    filepath TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    uploaded_at TEXT,
                    state TEXT NOT NULL DEFAULT 'created',
                    upload_attempts INTEGER DEFAULT 0,
                    last_error TEXT,
                    s3_key TEXT,
                    s3_bucket TEXT,
                    file_size INTEGER DEFAULT 0
                )
            ''')
            
            # Create indexes for common queries
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_segments_state 
                ON segments(state)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_segments_created 
                ON segments(created_at)
            ''')
        
        logger.info(f"Database initialized at {self.db_path}")
    
    def add_segment(self, segment: Segment) -> Segment:
        """
        Add a new segment to the database.
        
        Args:
            segment: Segment to add
            
        Returns:
            Segment with ID set
            
        Raises:
            DatabaseError: If insert fails
        """
        with self._cursor() as cursor:
            cursor.execute('''
                INSERT INTO segments 
                (filename, filepath, created_at, state, file_size)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                segment.filename,
                str(segment.filepath),
                segment.created_at.isoformat(),
                segment.state.value,
                segment.file_size
            ))
            
            segment.id = cursor.lastrowid
            logger.debug(f"Added segment: {segment.filename} (id={segment.id})")
            
        return segment
    
    def update_segment(self, segment: Segment) -> None:
        """
        Update an existing segment.
        
        Args:
            segment: Segment to update (must have ID)
            
        Raises:
            DatabaseError: If update fails
        """
        if segment.id is None:
            raise DatabaseError("Cannot update segment without ID")
        
        with self._cursor() as cursor:
            cursor.execute('''
                UPDATE segments SET
                    state = ?,
                    upload_attempts = ?,
                    last_error = ?,
                    uploaded_at = ?,
                    s3_key = ?,
                    s3_bucket = ?
                WHERE id = ?
            ''', (
                segment.state.value,
                segment.upload_attempts,
                segment.last_error,
                segment.uploaded_at.isoformat() if segment.uploaded_at else None,
                segment.s3_key,
                segment.s3_bucket,
                segment.id
            ))
            
        logger.debug(f"Updated segment: {segment.filename} -> {segment.state.value}")
    
    def get_segment_by_filename(self, filename: str) -> Optional[Segment]:
        """
        Get segment by filename.
        
        Args:
            filename: Segment filename
            
        Returns:
            Segment if found, None otherwise
        """
        with self._cursor() as cursor:
            cursor.execute(
                'SELECT * FROM segments WHERE filename = ?',
                (filename,)
            )
            row = cursor.fetchone()
            
            if row:
                return Segment.from_dict(dict(row))
            return None
    
    def get_segment_by_id(self, segment_id: int) -> Optional[Segment]:
        """
        Get segment by ID.
        
        Args:
            segment_id: Segment ID
            
        Returns:
            Segment if found, None otherwise
        """
        with self._cursor() as cursor:
            cursor.execute(
                'SELECT * FROM segments WHERE id = ?',
                (segment_id,)
            )
            row = cursor.fetchone()
            
            if row:
                return Segment.from_dict(dict(row))
            return None
    
    def get_segments_by_state(self, state: SegmentState, limit: int = 100) -> list[Segment]:
        """
        Get all segments in a given state.
        
        Args:
            state: State to filter by
            limit: Maximum number of segments to return
            
        Returns:
            List of matching segments
        """
        with self._cursor() as cursor:
            cursor.execute(
                'SELECT * FROM segments WHERE state = ? ORDER BY created_at ASC LIMIT ?',
                (state.value, limit)
            )
            rows = cursor.fetchall()
            
        return [Segment.from_dict(dict(row)) for row in rows]
    
    def get_pending_segments(self, limit: int = 100) -> list[Segment]:
        """
        Get segments pending upload (CREATED state).
        
        Args:
            limit: Maximum number to return
            
        Returns:
            List of pending segments
        """
        return self.get_segments_by_state(SegmentState.CREATED, limit)
    
    def get_failed_segments(self, limit: int = 100) -> list[Segment]:
        """
        Get failed segments for potential retry.
        
        Args:
            limit: Maximum number to return
            
        Returns:
            List of failed segments
        """
        return self.get_segments_by_state(SegmentState.FAILED, limit)
    
    def get_uploaded_segments(self, older_than_minutes: int = 30) -> list[Segment]:
        """
        Get uploaded segments older than specified time.
        
        Used for cleanup of local files.
        
        Args:
            older_than_minutes: Minimum age in minutes
            
        Returns:
            List of uploaded segments ready for cleanup
        """
        cutoff = datetime.now()
        cutoff_str = cutoff.isoformat()
        
        with self._cursor() as cursor:
            cursor.execute('''
                SELECT * FROM segments 
                WHERE state = ? 
                AND datetime(uploaded_at) < datetime(?, ?)
                ORDER BY uploaded_at ASC
            ''', (
                SegmentState.UPLOADED.value,
                cutoff_str,
                f'-{older_than_minutes} minutes'
            ))
            rows = cursor.fetchall()
            
        return [Segment.from_dict(dict(row)) for row in rows]
    
    def count_by_state(self) -> dict[str, int]:
        """
        Get count of segments per state.
        
        Returns:
            Dictionary of state -> count
        """
        with self._cursor() as cursor:
            cursor.execute('''
                SELECT state, COUNT(*) as count 
                FROM segments 
                GROUP BY state
            ''')
            rows = cursor.fetchall()
            
        return {row['state']: row['count'] for row in rows}
    
    def get_total_pending_size(self) -> int:
        """
        Get total size of pending segments in bytes.
        
        Returns:
            Total size in bytes
        """
        with self._cursor() as cursor:
            cursor.execute('''
                SELECT COALESCE(SUM(file_size), 0) as total 
                FROM segments 
                WHERE state IN (?, ?)
            ''', (SegmentState.CREATED.value, SegmentState.UPLOADING.value))
            row = cursor.fetchone()
            
        return row['total'] if row else 0
    
    def cleanup_old_records(self, days: int = 7) -> int:
        """
        Delete cleaned records older than specified days.
        
        Args:
            days: Age threshold in days
            
        Returns:
            Number of records deleted
        """
        with self._cursor() as cursor:
            cursor.execute('''
                DELETE FROM segments 
                WHERE state = ? 
                AND datetime(created_at) < datetime('now', ?)
            ''', (SegmentState.CLEANED.value, f'-{days} days'))
            
            deleted = cursor.rowcount
            
        if deleted > 0:
            logger.info(f"Cleaned up {deleted} old segment records")
            
        return deleted
    
    def reset_uploading_segments(self) -> int:
        """
        Reset segments stuck in UPLOADING state back to CREATED.
        
        Called on startup to recover from interrupted uploads.
        
        Returns:
            Number of segments reset
        """
        with self._cursor() as cursor:
            cursor.execute('''
                UPDATE segments 
                SET state = ? 
                WHERE state = ?
            ''', (SegmentState.CREATED.value, SegmentState.UPLOADING.value))
            
            reset = cursor.rowcount
            
        if reset > 0:
            logger.info(f"Reset {reset} interrupted uploads")
            
        return reset
    
    def close(self) -> None:
        """Close database connection."""
        if hasattr(self._local, 'connection') and self._local.connection:
            self._local.connection.close()
            self._local.connection = None
