"""
Configuration loader for the CCTV to S3 Pipeline.

Loads YAML configuration with environment variable substitution.
"""

import os
import re
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv

from .exceptions import ConfigurationError


# Load .env file if present
load_dotenv()


class Config:
    """
    Configuration manager with environment variable substitution.
    
    Usage:
        config = Config.load('config.yaml')
        camera_ip = config.get('camera.ip')
        bucket = config.get('s3.bucket', default='my-bucket')
    """
    
    _instance: Optional['Config'] = None
    _env_pattern = re.compile(r'\$\{([^}]+)\}')
    
    def __init__(self, config_data: dict):
        self._data = config_data
    
    @classmethod
    def load(cls, config_path: str = 'config.yaml') -> 'Config':
        """
        Load configuration from YAML file.
        
        Args:
            config_path: Path to YAML configuration file
            
        Returns:
            Config instance
            
        Raises:
            ConfigurationError: If file not found or invalid YAML
        """
        path = Path(config_path)
        
        if not path.exists():
            raise ConfigurationError(f"Configuration file not found: {config_path}")
        
        try:
            with open(path, 'r') as f:
                raw_content = f.read()
            
            # Substitute environment variables
            content = cls._substitute_env_vars(raw_content)
            
            # Parse YAML
            data = yaml.safe_load(content)
            
            if not isinstance(data, dict):
                raise ConfigurationError("Configuration must be a YAML dictionary")
            
            instance = cls(data)
            instance._validate()
            
            # Store as singleton
            cls._instance = instance
            
            return instance
            
        except yaml.YAMLError as e:
            raise ConfigurationError(f"Invalid YAML in configuration: {e}")
    
    @classmethod
    def get_instance(cls) -> 'Config':
        """Get the singleton Config instance."""
        if cls._instance is None:
            raise ConfigurationError("Configuration not loaded. Call Config.load() first.")
        return cls._instance
    
    @classmethod
    def _substitute_env_vars(cls, content: str) -> str:
        """
        Substitute ${VAR} patterns with environment variable values.
        
        Args:
            content: Raw file content
            
        Returns:
            Content with environment variables substituted
        """
        def replace(match):
            var_name = match.group(1)
            value = os.environ.get(var_name)
            if value is None:
                # Keep original if not found (might be optional)
                return match.group(0)
            return value
        
        return cls._env_pattern.sub(replace, content)
    
    def _validate(self) -> None:
        """
        Validate required configuration fields.
        
        Raises:
            ConfigurationError: If required fields are missing
        """
        required_fields = [
            'camera.name',
            'camera.ip',
            'camera.rtsp_path',
            's3.bucket',
            's3.region',
        ]
        
        for field in required_fields:
            value = self.get(field)
            if value is None or value == '':
                raise ConfigurationError(f"Required configuration field missing: {field}")
        
        # Validate specific values
        resolution = self.get('capture.resolution', '1280x720')
        if not re.match(r'^\d+x\d+$', resolution):
            raise ConfigurationError(f"Invalid resolution format: {resolution}")
        
        segment_duration = self.get('capture.segment_duration', 10)
        if not isinstance(segment_duration, int) or segment_duration < 1:
            raise ConfigurationError(f"segment_duration must be a positive integer")
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value by dot-separated key.
        
        Args:
            key: Dot-separated key (e.g., 'camera.ip')
            default: Default value if key not found
            
        Returns:
            Configuration value or default
        """
        keys = key.split('.')
        value = self._data
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def get_camera_config(self) -> dict:
        """Get camera configuration section."""
        return self._data.get('camera', {})
    
    def get_capture_config(self) -> dict:
        """Get capture configuration section."""
        return self._data.get('capture', {})
    
    def get_storage_config(self) -> dict:
        """Get storage configuration section."""
        return self._data.get('storage', {})
    
    def get_s3_config(self) -> dict:
        """Get S3 configuration section."""
        return self._data.get('s3', {})
    
    def get_server_config(self) -> dict:
        """Get server configuration section."""
        return self._data.get('server', {})
    
    def get_logging_config(self) -> dict:
        """Get logging configuration section."""
        return self._data.get('logging', {})
    
    def get_health_config(self) -> dict:
        """Get health monitoring configuration section."""
        return self._data.get('health', {})
    
    def get_advanced_config(self) -> dict:
        """Get advanced configuration section."""
        return self._data.get('advanced', {})
    
    def build_rtsp_url(self) -> str:
        """
        Build complete RTSP URL from camera configuration.
        
        Returns:
            Complete RTSP URL string
        """
        camera = self.get_camera_config()
        
        username = camera.get('username', '')
        password = camera.get('password', '')
        ip = camera.get('ip')
        port = camera.get('port', 554)
        path = camera.get('rtsp_path', '')
        
        # Build auth part
        if username and password:
            auth = f"{username}:{password}@"
        elif username:
            auth = f"{username}@"
        else:
            auth = ""
        
        return f"rtsp://{auth}{ip}:{port}{path}"
    
    def get_segments_dir(self) -> Path:
        """Get segments directory as Path object."""
        segments_dir = self.get('storage.segments_dir', './data/segments')
        return Path(segments_dir)
    
    def get_database_path(self) -> Path:
        """Get database path as Path object."""
        db_path = self.get('storage.database_path', './data/segments.db')
        return Path(db_path)
    
    def get_log_file(self) -> Path:
        """Get log file path as Path object."""
        log_file = self.get('logging.file', './data/logs/pipeline.log')
        return Path(log_file)
    
    def get_s3_prefix(self, **kwargs) -> str:
        """
        Get S3 prefix with variables substituted.
        
        Args:
            **kwargs: Variables to substitute (camera_name, year, month, day, hour)
            
        Returns:
            Formatted S3 prefix
        """
        prefix = self.get('s3.prefix', 'cameras/{camera_name}/')
        
        # Default values
        defaults = {
            'camera_name': self.get('camera.name', 'camera'),
        }
        
        # Merge with provided kwargs
        vars_dict = {**defaults, **kwargs}
        
        return prefix.format(**vars_dict)
    
    def to_dict(self) -> dict:
        """Return configuration as dictionary."""
        return self._data.copy()


def load_config(config_path: str = 'config.yaml') -> Config:
    """
    Convenience function to load configuration.
    
    Args:
        config_path: Path to YAML configuration file
        
    Returns:
        Config instance
    """
    return Config.load(config_path)


def get_config() -> Config:
    """
    Get the current configuration instance.
    
    Returns:
        Config instance
        
    Raises:
        ConfigurationError: If configuration not loaded
    """
    return Config.get_instance()
