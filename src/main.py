"""
Main entry point for the CCTV to S3 Pipeline.

Orchestrates all components: capture, upload, and HLS server.
"""

import asyncio
import signal
import sys
from pathlib import Path
from typing import Optional

import click

from .utils.config import Config, load_config
from .utils.logger import setup_from_config, get_logger
from .utils.exceptions import PipelineError, ConfigurationError
from .state.database import Database
from .state.models import HealthStatus
from .capture.rtsp_client import RTSPClient
from .capture.segmenter import SegmenterManager, create_segmenter
from .capture.health_check import HealthChecker
from .storage.s3_uploader import S3Uploader
from .storage.local_buffer import LocalBuffer
from .server.hls_server import HLSServer


logger = None  # Initialize after config


class Pipeline:
    """
    Main pipeline orchestrator.
    
    Manages lifecycle of all components:
    - RTSP capture and segmentation (FFmpeg)
    - Local buffer management
    - S3 uploading
    - HLS server for real-time viewing
    - Health monitoring
    """
    
    def __init__(self, config: Config):
        """
        Initialize pipeline with configuration.
        
        Args:
            config: Pipeline configuration
        """
        self.config = config
        
        # Initialize logger
        global logger
        setup_from_config(config.get_logging_config())
        logger = get_logger(__name__)
        
        # Initialize components
        self.database = Database(config.get_database_path())
        self.rtsp_client = RTSPClient(config)
        self.segmenter: Optional[SegmenterManager] = None
        self.uploader: Optional[S3Uploader] = None
        self.local_buffer: Optional[LocalBuffer] = None
        self.hls_server: Optional[HLSServer] = None
        self.health_checker: Optional[HealthChecker] = None
        
        # Status
        self._running = False
        self._health_status = HealthStatus()
        
        # Set up signal handlers
        self._setup_signals()
    
    def _setup_signals(self) -> None:
        """Set up signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            signame = signal.Signals(signum).name
            logger.info(f"Received {signame}, initiating shutdown...")
            self._running = False
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    def _on_new_segment(self, segment) -> None:
        """Callback when new segment is ready."""
        if self.uploader:
            self.uploader.queue_segment(segment)
    
    def _get_health_status(self) -> HealthStatus:
        """Get current health status."""
        status = HealthStatus()
        
        # Check component states
        status.capture_running = self.segmenter.is_running if self.segmenter else False
        status.upload_running = self.uploader is not None
        status.server_running = self.hls_server is not None
        
        # Get health checker stats
        if self.health_checker:
            status.last_segment_time = self.health_checker.last_segment_time
            status.ffmpeg_restarts = self.segmenter.restart_count if self.segmenter else 0
        
        # Get upload stats
        if self.uploader:
            status.upload_errors = self.uploader.error_count
        
        # Get buffer stats
        if self.local_buffer:
            status.segments_pending = self.local_buffer.get_pending_count()
            status.disk_usage_mb = self.local_buffer.get_disk_usage_mb()
        
        status.disk_limit_mb = self.config.get('storage.max_disk_usage_mb', 2000)
        
        return status
    
    def test_connections(self) -> bool:
        """
        Test camera and S3 connections.
        
        Returns:
            True if all connections successful
        """
        logger.info("Testing connections...")
        
        # Test RTSP connection
        try:
            self.rtsp_client.test_connection()
            stream_info = self.rtsp_client.get_stream_info()
            logger.info(f"Camera stream: {stream_info.resolution} @ {stream_info.fps}fps")
        except PipelineError as e:
            logger.error(f"Camera connection failed: {e}")
            return False
        
        # Test S3 connection
        try:
            temp_uploader = S3Uploader(self.config, self.database)
            temp_uploader.test_connection()
        except PipelineError as e:
            logger.error(f"S3 connection failed: {e}")
            return False
        
        logger.info("All connections successful!")
        return True
    
    def start(self) -> None:
        """Start all pipeline components."""
        logger.info("=" * 50)
        logger.info("Starting CCTV to S3 Pipeline")
        logger.info("=" * 50)
        
        camera_name = self.config.get('camera.name', 'camera')
        logger.info(f"Camera: {camera_name}")
        
        # Reset any interrupted uploads from previous run
        self.database.reset_uploading_segments()
        
        # Start S3 uploader
        logger.info("Starting S3 uploader...")
        self.uploader = S3Uploader(self.config, self.database)
        self.uploader.start()
        
        # Start local buffer (watchdog)
        logger.info("Starting local buffer...")
        self.local_buffer = LocalBuffer(
            self.config, 
            self.database,
            on_new_segment=self._on_new_segment
        )
        self.local_buffer.start()
        
        # Start FFmpeg segmenter
        logger.info("Starting capture...")
        self.segmenter = create_segmenter(self.config)
        self.segmenter.start()
        
        # Start health checker
        logger.info("Starting health monitor...")
        self.health_checker = HealthChecker(
            self.config,
            self.segmenter,
            on_health_issue=lambda msg: logger.warning(f"Health issue: {msg}")
        )
        self.health_checker.start()
        
        self._running = True
        logger.info("Pipeline started successfully!")
    
    async def start_server(self) -> None:
        """Start HLS server (async)."""
        if self.config.get('server.enabled', True):
            logger.info("Starting HLS server...")
            self.hls_server = HLSServer(
                self.config,
                health_callback=self._get_health_status
            )
            await self.hls_server.start()
    
    async def stop_server(self) -> None:
        """Stop HLS server (async)."""
        if self.hls_server:
            await self.hls_server.stop()
    
    def stop(self) -> None:
        """Stop all pipeline components."""
        logger.info("Stopping pipeline...")
        
        if self.health_checker:
            self.health_checker.stop()
        
        if self.segmenter:
            self.segmenter.stop()
        
        if self.local_buffer:
            self.local_buffer.stop()
        
        if self.uploader:
            self.uploader.stop()
        
        if self.database:
            self.database.close()
        
        logger.info("Pipeline stopped")
    
    async def run(self) -> None:
        """Main run loop."""
        self.start()
        await self.start_server()
        
        try:
            # Main loop - just wait for shutdown signal
            while self._running:
                await asyncio.sleep(1)
        finally:
            await self.stop_server()
            self.stop()


@click.command()
@click.option(
    '--config', '-c',
    default='config.yaml',
    help='Path to configuration file'
)
@click.option(
    '--test',
    is_flag=True,
    help='Test connections and exit'
)
def main(config: str, test: bool):
    """
    CCTV to S3 Streaming Pipeline
    
    Captures video from IP cameras and streams to AWS S3.
    """
    # Load configuration
    try:
        cfg = load_config(config)
    except ConfigurationError as e:
        click.echo(f"Configuration error: {e}", err=True)
        sys.exit(1)
    
    # Initialize logging early
    setup_from_config(cfg.get_logging_config())
    global logger
    logger = get_logger(__name__)
    
    # Create pipeline
    pipeline = Pipeline(cfg)
    
    if test:
        # Test mode - just check connections
        success = pipeline.test_connections()
        sys.exit(0 if success else 1)
    
    # Run pipeline
    try:
        asyncio.run(pipeline.run())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.exception(f"Pipeline error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
