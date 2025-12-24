"""
HLS manifest generation and management.

Creates and updates M3U8 playlists for S3 storage.
"""

from datetime import datetime
from pathlib import Path
from typing import List, Optional

from ..utils.config import Config
from ..utils.logger import get_logger
from ..state.models import Segment


logger = get_logger(__name__)


class ManifestGenerator:
    """
    Generates HLS manifests (M3U8 playlists) for video segments.
    
    Creates both live (rolling) and VOD (archive) manifests.
    """
    
    # HLS playlist header
    PLAYLIST_HEADER = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:{target_duration}
#EXT-X-MEDIA-SEQUENCE:{media_sequence}
"""
    
    # Segment entry format
    SEGMENT_ENTRY = """#EXTINF:{duration:.3f},
{filename}
"""
    
    def __init__(self, config: Config):
        """
        Initialize manifest generator.
        
        Args:
            config: Pipeline configuration
        """
        self.config = config
        
        # Configuration
        self.segment_duration = config.get('capture.segment_duration', 10)
        self.playlist_segments = config.get('server.playlist_segments', 6)
        self.segments_dir = config.get_segments_dir()
        
        # Advanced config
        advanced = config.get_advanced_config()
        self.playlist_name = advanced.get('playlist_name', 'live.m3u8')
    
    def generate_live_playlist(
        self,
        segments: List[str],
        media_sequence: int = 0
    ) -> str:
        """
        Generate a live HLS playlist (rolling window).
        
        Args:
            segments: List of segment filenames
            media_sequence: Starting media sequence number
            
        Returns:
            M3U8 playlist content
        """
        # Use last N segments for live playlist
        live_segments = segments[-self.playlist_segments:]
        
        # Build header
        content = self.PLAYLIST_HEADER.format(
            target_duration=self.segment_duration,
            media_sequence=media_sequence
        )
        
        # Add segments
        for segment in live_segments:
            content += self.SEGMENT_ENTRY.format(
                duration=float(self.segment_duration),
                filename=segment
            )
        
        return content
    
    def generate_vod_playlist(
        self,
        segments: List[Segment],
        include_endlist: bool = True
    ) -> str:
        """
        Generate a VOD (archive) playlist for completed recordings.
        
        Args:
            segments: List of Segment objects
            include_endlist: Whether to include EXT-X-ENDLIST tag
            
        Returns:
            M3U8 playlist content
        """
        if not segments:
            return ""
        
        # Build header
        content = self.PLAYLIST_HEADER.format(
            target_duration=self.segment_duration,
            media_sequence=0
        )
        
        # Add playlist type for VOD
        content += "#EXT-X-PLAYLIST-TYPE:VOD\n"
        
        # Add segments
        for segment in segments:
            content += self.SEGMENT_ENTRY.format(
                duration=float(self.segment_duration),
                filename=segment.filename
            )
        
        # Add end tag for completed VOD
        if include_endlist:
            content += "#EXT-X-ENDLIST\n"
        
        return content
    
    def generate_hourly_manifest(
        self,
        segments: List[Segment],
        hour: datetime
    ) -> str:
        """
        Generate manifest for an hour of footage.
        
        Args:
            segments: Segments from that hour
            hour: The hour being archived
            
        Returns:
            M3U8 playlist content
        """
        # Sort by creation time
        sorted_segments = sorted(segments, key=lambda s: s.created_at)
        
        return self.generate_vod_playlist(sorted_segments, include_endlist=True)
    
    def write_local_playlist(self, segments: List[str]) -> Path:
        """
        Write live playlist to local segments directory.
        
        Args:
            segments: List of segment filenames
            
        Returns:
            Path to written playlist
        """
        playlist_path = self.segments_dir / self.playlist_name
        content = self.generate_live_playlist(segments)
        
        playlist_path.write_text(content)
        logger.debug(f"Updated playlist: {playlist_path}")
        
        return playlist_path
    
    def get_local_playlist_path(self) -> Path:
        """Get path to local live playlist."""
        return self.segments_dir / self.playlist_name


class S3ManifestManager:
    """
    Manages HLS manifests in S3 for archive playback.
    
    Creates hourly manifests that reference uploaded segments.
    """
    
    def __init__(self, config: Config, s3_client):
        """
        Initialize S3 manifest manager.
        
        Args:
            config: Pipeline configuration
            s3_client: boto3 S3 client
        """
        self.config = config
        self.s3_client = s3_client
        
        self.generator = ManifestGenerator(config)
        self.bucket = config.get('s3.bucket')
        self.camera_name = config.get('camera.name', 'camera')
        self.prefix_template = config.get('s3.prefix', 'cameras/{camera_name}/')
    
    def upload_hourly_manifest(
        self,
        segments: List[Segment],
        hour: datetime
    ) -> str:
        """
        Generate and upload manifest for an hour of footage.
        
        Args:
            segments: Segments from that hour
            hour: The hour being archived
            
        Returns:
            S3 key of uploaded manifest
        """
        # Generate manifest content
        content = self.generator.generate_hourly_manifest(segments, hour)
        
        # Build S3 key
        prefix = self.prefix_template.format(
            camera_name=self.camera_name,
            year=hour.strftime('%Y'),
            month=hour.strftime('%m'),
            day=hour.strftime('%d'),
            hour=hour.strftime('%H')
        )
        s3_key = f"{prefix}playlist.m3u8"
        
        # Upload to S3
        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=s3_key,
            Body=content.encode('utf-8'),
            ContentType='application/vnd.apple.mpegurl'
        )
        
        logger.info(f"Uploaded hourly manifest: s3://{self.bucket}/{s3_key}")
        return s3_key
    
    def build_day_manifest(self, date: datetime) -> str:
        """
        Build a master manifest for an entire day.
        
        References hourly manifests.
        
        Args:
            date: The date to build manifest for
            
        Returns:
            M3U8 master playlist content
        """
        content = "#EXTM3U\n"
        content += "#EXT-X-VERSION:3\n"
        content += f"# Daily manifest for {date.strftime('%Y-%m-%d')}\n"
        content += f"# Camera: {self.camera_name}\n\n"
        
        # Add reference to each hour's playlist
        for hour in range(24):
            hour_dt = date.replace(hour=hour)
            prefix = self.prefix_template.format(
                camera_name=self.camera_name,
                year=hour_dt.strftime('%Y'),
                month=hour_dt.strftime('%m'),
                day=hour_dt.strftime('%d'),
                hour=hour_dt.strftime('%H')
            )
            
            content += f"# Hour {hour:02d}:00\n"
            content += f"#EXT-X-DISCONTINUITY\n"
            content += f"{prefix}playlist.m3u8\n\n"
        
        return content


def create_manifest_generator(config: Config) -> ManifestGenerator:
    """
    Factory function to create manifest generator.
    
    Args:
        config: Pipeline configuration
        
    Returns:
        ManifestGenerator instance
    """
    return ManifestGenerator(config)
