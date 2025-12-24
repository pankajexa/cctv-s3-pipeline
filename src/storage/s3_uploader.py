"""
S3 uploader for video segments.

Uploads HLS segments to AWS S3 with retry logic and exponential backoff.
"""

import time
from datetime import datetime
from pathlib import Path
from threading import Thread, Event
from typing import Optional
from queue import Queue, Empty

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError, BotoCoreError

from ..utils.config import Config
from ..utils.exceptions import UploadError, RetryExhaustedError
from ..utils.logger import get_logger
from ..state.models import Segment, SegmentState
from ..state.database import Database


logger = get_logger(__name__)


class S3Uploader:
    """
    S3 uploader with retry logic and exponential backoff.
    
    Uploads segments to S3 and updates database state.
    """
    
    def __init__(self, config: Config, database: Database):
        """
        Initialize S3 uploader.
        
        Args:
            config: Pipeline configuration
            database: Database for state tracking
        """
        self.config = config
        self.database = database
        
        # S3 configuration
        s3_config = config.get_s3_config()
        self.bucket = s3_config.get('bucket')
        self.region = s3_config.get('region', 'ap-south-1')
        self.prefix_template = s3_config.get('prefix', 'cameras/{camera_name}/')
        self.storage_class = s3_config.get('storage_class', 'STANDARD')
        self.upload_timeout = s3_config.get('upload_timeout', 30)
        self.max_retries = s3_config.get('max_retries', 5)
        self.retry_delay = s3_config.get('retry_delay', 5)
        self.multipart_threshold = s3_config.get('multipart_threshold', 8 * 1024 * 1024)
        
        # Camera name for S3 path
        self.camera_name = config.get('camera.name', 'camera')
        
        # Initialize S3 client
        boto_config = BotoConfig(
            region_name=self.region,
            retries={'max_attempts': 0}  # We handle retries ourselves
        )
        self._client = boto3.client('s3', config=boto_config)
        
        # Upload queue and control
        self._queue: Queue[Segment] = Queue()
        self._stop_event = Event()
        self._thread: Optional[Thread] = None
        self._upload_count = 0
        self._error_count = 0
    
    @property
    def upload_count(self) -> int:
        """Get total successful uploads."""
        return self._upload_count
    
    @property
    def error_count(self) -> int:
        """Get total upload errors."""
        return self._error_count
    
    def start(self) -> None:
        """Start the upload worker thread."""
        self._stop_event.clear()
        
        self._thread = Thread(
            target=self._upload_loop,
            daemon=True,
            name="s3-uploader"
        )
        self._thread.start()
        logger.info(f"S3 uploader started (bucket: {self.bucket})")
    
    def stop(self) -> None:
        """Stop the upload worker thread."""
        self._stop_event.set()
        
        if self._thread:
            self._thread.join(timeout=10)
            self._thread = None
        
        logger.info(f"S3 uploader stopped (uploads: {self._upload_count}, errors: {self._error_count})")
    
    def queue_segment(self, segment: Segment) -> None:
        """
        Add a segment to the upload queue.
        
        Args:
            segment: Segment to upload
        """
        self._queue.put(segment)
        logger.debug(f"Queued segment for upload: {segment.filename}")
    
    def queue_size(self) -> int:
        """Get number of segments in upload queue."""
        return self._queue.qsize()
    
    def _upload_loop(self) -> None:
        """Main upload worker loop."""
        while not self._stop_event.is_set():
            try:
                # Get segment from queue with timeout
                segment = self._queue.get(timeout=1.0)
            except Empty:
                continue
            
            try:
                self._upload_with_retry(segment)
            except RetryExhaustedError as e:
                logger.error(f"Upload failed after {e.attempts} attempts: {segment.filename}")
                segment.mark_failed(str(e))
                self.database.update_segment(segment)
                self._error_count += 1
            except Exception as e:
                logger.error(f"Unexpected upload error for {segment.filename}: {e}")
                segment.mark_failed(str(e))
                self.database.update_segment(segment)
                self._error_count += 1
    
    def _upload_with_retry(self, segment: Segment) -> None:
        """
        Upload segment with exponential backoff retry.
        
        Args:
            segment: Segment to upload
            
        Raises:
            RetryExhaustedError: If all retries failed
        """
        delay = self.retry_delay
        
        while segment.upload_attempts < self.max_retries:
            try:
                # Mark as uploading
                segment.mark_uploading()
                self.database.update_segment(segment)
                
                # Build S3 key
                s3_key = self._build_s3_key(segment)
                
                # Upload to S3
                self._upload_file(segment.filepath, s3_key)
                
                # Mark as uploaded
                segment.mark_uploaded(s3_key, self.bucket)
                self.database.update_segment(segment)
                
                self._upload_count += 1
                logger.info(f"Uploaded: {segment.filename} -> s3://{self.bucket}/{s3_key}")
                return
                
            except (ClientError, BotoCoreError) as e:
                error_msg = str(e)
                logger.warning(f"Upload attempt {segment.upload_attempts} failed: {error_msg}")
                
                if segment.upload_attempts < self.max_retries:
                    logger.info(f"Retrying in {delay}s...")
                    time.sleep(delay)
                    delay = min(delay * 2, 60)  # Exponential backoff, max 60s
        
        raise RetryExhaustedError(
            f"Failed to upload {segment.filename}",
            segment.upload_attempts
        )
    
    def _build_s3_key(self, segment: Segment) -> str:
        """Build S3 object key for segment."""
        now = segment.created_at or datetime.now()
        
        prefix = self.prefix_template.format(
            camera_name=self.camera_name,
            year=now.strftime('%Y'),
            month=now.strftime('%m'),
            day=now.strftime('%d'),
            hour=now.strftime('%H')
        )
        
        return f"{prefix}{segment.filename}"
    
    def _upload_file(self, filepath: Path, s3_key: str) -> None:
        """
        Upload a file to S3.
        
        Args:
            filepath: Local file path
            s3_key: S3 object key
            
        Raises:
            ClientError: If upload fails
        """
        file_size = filepath.stat().st_size
        
        extra_args = {
            'StorageClass': self.storage_class
        }
        
        if file_size > self.multipart_threshold:
            # Use multipart upload for large files
            self._multipart_upload(filepath, s3_key, extra_args)
        else:
            # Simple upload
            self._client.upload_file(
                str(filepath),
                self.bucket,
                s3_key,
                ExtraArgs=extra_args
            )
    
    def _multipart_upload(self, filepath: Path, s3_key: str, extra_args: dict) -> None:
        """
        Perform multipart upload for large files.
        
        Args:
            filepath: Local file path
            s3_key: S3 object key
            extra_args: Extra S3 arguments
        """
        from boto3.s3.transfer import TransferConfig
        
        config = TransferConfig(
            multipart_threshold=self.multipart_threshold,
            multipart_chunksize=8 * 1024 * 1024,  # 8MB chunks
            use_threads=True,
            max_concurrency=4
        )
        
        self._client.upload_file(
            str(filepath),
            self.bucket,
            s3_key,
            ExtraArgs=extra_args,
            Config=config
        )
    
    def test_connection(self) -> bool:
        """
        Test S3 connection and permissions.
        
        Returns:
            True if connection successful
            
        Raises:
            UploadError: If connection fails
        """
        logger.info(f"Testing S3 connection to bucket: {self.bucket}")
        
        try:
            # Try to list objects (head bucket requires different permission)
            self._client.list_objects_v2(
                Bucket=self.bucket,
                MaxKeys=1
            )
            logger.info("S3 connection test successful")
            return True
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            
            if error_code == 'AccessDenied':
                raise UploadError(f"S3 access denied to bucket {self.bucket}")
            elif error_code == 'NoSuchBucket':
                raise UploadError(f"S3 bucket not found: {self.bucket}")
            else:
                raise UploadError(f"S3 connection failed: {error_code} - {error_msg}")
        except BotoCoreError as e:
            raise UploadError(f"S3 connection error: {e}")


def create_s3_uploader(config: Config, database: Database) -> S3Uploader:
    """
    Factory function to create S3 uploader.
    
    Args:
        config: Pipeline configuration
        database: Database for state tracking
        
    Returns:
        S3Uploader instance
    """
    return S3Uploader(config, database)
