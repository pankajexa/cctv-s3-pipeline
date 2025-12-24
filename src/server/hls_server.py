"""
HLS server for real-time video streaming.

Serves HLS segments and playlists over HTTP for browser/VLC playback.
"""

import json
import mimetypes
from pathlib import Path
from typing import Optional

from aiohttp import web

from ..utils.config import Config
from ..utils.logger import get_logger
from ..state.models import HealthStatus


logger = get_logger(__name__)


class HLSServer:
    """
    Async HTTP server for HLS streaming.
    
    Serves .ts segments and .m3u8 playlists from local segments directory.
    Also provides health endpoint for monitoring.
    """
    
    def __init__(
        self,
        config: Config,
        health_callback: Optional[callable] = None
    ):
        """
        Initialize HLS server.
        
        Args:
            config: Pipeline configuration
            health_callback: Callback to get current health status
        """
        self.config = config
        self.health_callback = health_callback
        
        # Server configuration
        server_config = config.get_server_config()
        self.enabled = server_config.get('enabled', True)
        self.host = server_config.get('host', '0.0.0.0')
        self.port = server_config.get('port', 8080)
        self.cors_enabled = server_config.get('cors_enabled', True)
        self.cors_origins = server_config.get('cors_origins', '*')
        
        # Segments directory
        self.segments_dir = config.get_segments_dir()
        
        # Advanced config
        advanced = config.get_advanced_config()
        self.playlist_name = advanced.get('playlist_name', 'live.m3u8')
        
        # Server state
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
    
    def _create_app(self) -> web.Application:
        """Create the aiohttp application."""
        app = web.Application()
        
        # Add routes
        app.router.add_get('/', self._handle_index)
        app.router.add_get('/health', self._handle_health)
        app.router.add_get('/live.m3u8', self._handle_playlist)
        app.router.add_get('/{filename}.m3u8', self._handle_playlist_generic)
        app.router.add_get('/{filename}.ts', self._handle_segment)
        
        # Add CORS middleware if enabled
        if self.cors_enabled:
            app.middlewares.append(self._cors_middleware)
        
        return app
    
    @web.middleware
    async def _cors_middleware(self, request: web.Request, handler):
        """Add CORS headers to responses."""
        response = await handler(request)
        
        response.headers['Access-Control-Allow-Origin'] = self.cors_origins
        response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        
        return response
    
    async def _handle_index(self, request: web.Request) -> web.Response:
        """Handle root index request."""
        camera_name = self.config.get('camera.name', 'camera')
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>CCTV Stream - {camera_name}</title>
    <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
    <style>
        body {{
            font-family: Arial, sans-serif;
            background: #1a1a1a;
            color: #fff;
            margin: 0;
            padding: 20px;
        }}
        h1 {{ color: #4CAF50; }}
        video {{
            max-width: 100%;
            background: #000;
        }}
        .info {{
            margin-top: 20px;
            padding: 10px;
            background: #333;
            border-radius: 5px;
        }}
        a {{ color: #4CAF50; }}
    </style>
</head>
<body>
    <h1>📹 {camera_name}</h1>
    <video id="video" controls autoplay muted></video>
    
    <div class="info">
        <h3>Stream URLs:</h3>
        <ul>
            <li>HLS: <a href="/live.m3u8">/live.m3u8</a></li>
            <li>Health: <a href="/health">/health</a></li>
        </ul>
        <p>Play in VLC: <code>http://{request.host}/live.m3u8</code></p>
    </div>
    
    <script>
        const video = document.getElementById('video');
        const src = '/live.m3u8';
        
        if (Hls.isSupported()) {{
            const hls = new Hls({{
                liveSyncDurationCount: 3,
                liveMaxLatencyDurationCount: 6
            }});
            hls.loadSource(src);
            hls.attachMedia(video);
            hls.on(Hls.Events.MANIFEST_PARSED, () => video.play());
        }} else if (video.canPlayType('application/vnd.apple.mpegurl')) {{
            video.src = src;
            video.addEventListener('loadedmetadata', () => video.play());
        }}
    </script>
</body>
</html>
"""
        return web.Response(text=html, content_type='text/html')
    
    async def _handle_health(self, request: web.Request) -> web.Response:
        """Handle health check request."""
        if self.health_callback:
            status = self.health_callback()
            if isinstance(status, HealthStatus):
                data = status.to_dict()
            else:
                data = status
        else:
            data = {
                'status': 'ok',
                'server': 'running'
            }
        
        return web.json_response(data)
    
    async def _handle_playlist(self, request: web.Request) -> web.Response:
        """Handle playlist (.m3u8) request."""
        return await self._handle_playlist_generic(request)
    
    async def _handle_playlist_generic(self, request: web.Request) -> web.Response:
        """Handle generic playlist request."""
        filename = request.match_info.get('filename', 'live')
        playlist_path = self.segments_dir / f"{filename}.m3u8"
        
        if not playlist_path.exists():
            logger.warning(f"Playlist not found: {playlist_path}")
            return web.Response(
                text="Playlist not found. Stream may not be running.",
                status=404
            )
        
        content = playlist_path.read_text()
        
        return web.Response(
            text=content,
            content_type='application/vnd.apple.mpegurl',
            headers={
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0'
            }
        )
    
    async def _handle_segment(self, request: web.Request) -> web.Response:
        """Handle segment (.ts) request."""
        filename = request.match_info['filename'] + '.ts'
        segment_path = self.segments_dir / filename
        
        if not segment_path.exists():
            logger.warning(f"Segment not found: {segment_path}")
            return web.Response(text="Segment not found", status=404)
        
        data = segment_path.read_bytes()
        
        return web.Response(
            body=data,
            content_type='video/mp2t',
            headers={
                'Cache-Control': 'max-age=31536000',  # Cache segments
            }
        )
    
    async def start(self) -> None:
        """Start the HTTP server."""
        if not self.enabled:
            logger.info("HLS server disabled in configuration")
            return
        
        self._app = self._create_app()
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()
        
        logger.info(f"HLS server started at http://{self.host}:{self.port}")
        logger.info(f"Stream URL: http://{self.host}:{self.port}/live.m3u8")
    
    async def stop(self) -> None:
        """Stop the HTTP server."""
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            self._site = None
            self._app = None
            logger.info("HLS server stopped")


def create_hls_server(
    config: Config,
    health_callback: Optional[callable] = None
) -> HLSServer:
    """
    Factory function to create HLS server.
    
    Args:
        config: Pipeline configuration
        health_callback: Callback for health status
        
    Returns:
        HLSServer instance
    """
    return HLSServer(config, health_callback)
