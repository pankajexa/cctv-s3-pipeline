"""
Storage module for CCTV Pipeline.

Handles S3 uploads, local buffer management, and HLS manifests.
"""

from .s3_uploader import S3Uploader, create_s3_uploader
from .local_buffer import LocalBuffer, create_local_buffer
from .manifest import ManifestGenerator, S3ManifestManager, create_manifest_generator

__all__ = [
    'S3Uploader',
    'create_s3_uploader',
    'LocalBuffer',
    'create_local_buffer',
    'ManifestGenerator',
    'S3ManifestManager',
    'create_manifest_generator',
]
