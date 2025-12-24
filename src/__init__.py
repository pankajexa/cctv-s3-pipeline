"""
CCTV to S3 Pipeline

A production-ready pipeline for streaming CCTV footage from IP cameras
to AWS S3, with real-time HLS viewing capabilities.
"""

__version__ = "1.0.0"
__author__ = "CCTV Pipeline Team"

from .utils.config import load_config, get_config, Config
from .utils.logger import setup_logging, get_logger
from .main import Pipeline, main

__all__ = [
    'load_config',
    'get_config', 
    'Config',
    'setup_logging',
    'get_logger',
    'Pipeline',
    'main',
]
