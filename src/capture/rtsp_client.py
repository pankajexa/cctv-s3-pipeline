"""
RTSP client for connecting to IP cameras.

Provides URL building and connection testing for CP Plus cameras.
"""

import subprocess
import shutil
from dataclasses import dataclass
from typing import Optional

from ..utils.config import Config
from ..utils.exceptions import RTSPConnectionError
from ..utils.logger import get_logger


logger = get_logger(__name__)


@dataclass
class StreamInfo:
    """Information about an RTSP stream."""
    width: int
    height: int
    codec: str
    fps: float
    
    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}"


class RTSPClient:
    """
    RTSP client for IP camera connections.
    
    Handles URL building and connection testing using FFprobe.
    """
    
    def __init__(self, config: Config):
        """
        Initialize RTSP client.
        
        Args:
            config: Pipeline configuration
        """
        self.config = config
        self._rtsp_url: Optional[str] = None
        
        # Verify FFprobe is available
        if not shutil.which('ffprobe'):
            logger.warning("ffprobe not found in PATH - stream info unavailable")
    
    @property
    def rtsp_url(self) -> str:
        """Get the RTSP URL for the camera."""
        if self._rtsp_url is None:
            self._rtsp_url = self.config.build_rtsp_url()
        return self._rtsp_url
    
    @property
    def safe_url(self) -> str:
        """Get RTSP URL with password masked for logging."""
        url = self.rtsp_url
        password = self.config.get('camera.password', '')
        if password:
            return url.replace(password, '****')
        return url
    
    def test_connection(self, timeout: int = 10) -> bool:
        """
        Test RTSP connection to the camera.
        
        Args:
            timeout: Connection timeout in seconds
            
        Returns:
            True if connection successful
            
        Raises:
            RTSPConnectionError: If connection fails
        """
        logger.info(f"Testing RTSP connection to {self.safe_url}")
        
        if not shutil.which('ffprobe'):
            raise RTSPConnectionError("ffprobe not found - cannot test connection")
        
        transport = self.config.get('camera.rtsp_transport', 'tcp')
        
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-rtsp_transport', transport,
            '-timeout', str(timeout * 1000000),  # microseconds (use 'timeout' for FFmpeg 8+)
            '-show_entries', 'stream=width,height',
            '-of', 'csv=p=0',
            self.rtsp_url
        ]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout + 5
            )
            
            if result.returncode != 0:
                error_msg = result.stderr.strip() or "Unknown error"
                raise RTSPConnectionError(f"RTSP connection failed: {error_msg}")
            
            logger.info("RTSP connection test successful")
            return True
            
        except subprocess.TimeoutExpired:
            raise RTSPConnectionError(f"RTSP connection timeout after {timeout}s")
        except FileNotFoundError:
            raise RTSPConnectionError("ffprobe not found")
    
    def get_stream_info(self, timeout: int = 10) -> StreamInfo:
        """
        Get information about the RTSP stream.
        
        Args:
            timeout: Connection timeout in seconds
            
        Returns:
            StreamInfo with resolution, codec, etc.
            
        Raises:
            RTSPConnectionError: If unable to get stream info
        """
        logger.info(f"Getting stream info from {self.safe_url}")
        
        if not shutil.which('ffprobe'):
            raise RTSPConnectionError("ffprobe not found")
        
        transport = self.config.get('camera.rtsp_transport', 'tcp')
        
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-rtsp_transport', transport,
            '-timeout', str(timeout * 1000000),  # FFmpeg 8+ uses 'timeout'
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height,codec_name,r_frame_rate',
            '-of', 'csv=p=0',
            self.rtsp_url
        ]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout + 5
            )
            
            if result.returncode != 0:
                error_msg = result.stderr.strip() or "Unknown error"
                raise RTSPConnectionError(f"Failed to get stream info: {error_msg}")
            
            # Parse output: width,height,codec,fps
            output = result.stdout.strip()
            if not output:
                raise RTSPConnectionError("No stream info returned")
            
            parts = output.split(',')
            if len(parts) < 4:
                raise RTSPConnectionError(f"Unexpected stream info format: {output}")
            
            # Parse frame rate (might be fraction like "25/1")
            fps_str = parts[3]
            if '/' in fps_str:
                num, den = fps_str.split('/')
                fps = float(num) / float(den) if float(den) != 0 else 0
            else:
                fps = float(fps_str)
            
            info = StreamInfo(
                width=int(parts[0]),
                height=int(parts[1]),
                codec=parts[2],
                fps=fps
            )
            
            logger.info(f"Stream info: {info.resolution} @ {info.fps:.1f}fps ({info.codec})")
            return info
            
        except subprocess.TimeoutExpired:
            raise RTSPConnectionError(f"Stream info timeout after {timeout}s")
        except (ValueError, IndexError) as e:
            raise RTSPConnectionError(f"Failed to parse stream info: {e}")


def create_rtsp_client(config: Config) -> RTSPClient:
    """
    Factory function to create RTSP client.
    
    Args:
        config: Pipeline configuration
        
    Returns:
        Configured RTSPClient instance
    """
    return RTSPClient(config)
