"""
Server module for CCTV Pipeline.

Provides HLS streaming server for real-time viewing.
"""

from .hls_server import HLSServer, create_hls_server

__all__ = [
    'HLSServer',
    'create_hls_server',
]
