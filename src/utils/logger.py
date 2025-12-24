"""
Logging setup for the CCTV to S3 Pipeline.

Provides structured logging with file rotation and console output.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


# Module-level logger cache
_loggers: dict[str, logging.Logger] = {}
_initialized = False


def setup_logging(
    log_file: Optional[str] = None,
    level: str = 'INFO',
    max_size_mb: int = 50,
    backup_count: int = 5,
    log_format: Optional[str] = None,
    console: bool = True
) -> None:
    """
    Initialize logging configuration.
    
    Args:
        log_file: Path to log file (None = no file logging)
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        max_size_mb: Maximum log file size in MB before rotation
        backup_count: Number of backup files to keep
        log_format: Log format string
        console: Whether to log to console
    """
    global _initialized
    
    if log_format is None:
        log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    # Get numeric log level
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    
    # Clear existing handlers
    root_logger.handlers = []
    
    # Create formatter
    formatter = logging.Formatter(log_format)
    
    # Add console handler
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(numeric_level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
    
    # Add file handler
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=max_size_mb * 1024 * 1024,
            backupCount=backup_count
        )
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    _initialized = True


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger for the specified module.
    
    Args:
        name: Logger name (usually __name__)
        
    Returns:
        Configured logger instance
    """
    global _initialized
    
    if name not in _loggers:
        # Initialize with defaults if not already done
        if not _initialized:
            setup_logging()
        
        _loggers[name] = logging.getLogger(name)
    
    return _loggers[name]


def setup_from_config(config: dict) -> None:
    """
    Setup logging from configuration dictionary.
    
    Args:
        config: Logging configuration dict with keys:
            - level: Log level
            - file: Log file path
            - max_size_mb: Max file size
            - backup_count: Backup count
            - format: Log format
            - console: Console output enabled
    """
    setup_logging(
        log_file=config.get('file'),
        level=config.get('level', 'INFO'),
        max_size_mb=config.get('max_size_mb', 50),
        backup_count=config.get('backup_count', 5),
        log_format=config.get('format'),
        console=config.get('console', True)
    )
