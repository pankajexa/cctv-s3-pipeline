"""
Tests for configuration loading.
"""

import os
import tempfile
from pathlib import Path
import pytest

from src.utils.config import Config, load_config, ConfigurationError


class TestConfig:
    """Test configuration loading and validation."""
    
    @pytest.fixture
    def valid_config_content(self):
        """Valid configuration YAML content."""
        return """
camera:
  name: "test-camera"
  ip: "192.168.1.100"
  port: 554
  username: "admin"
  password: "testpass"
  rtsp_path: "/cam/realmonitor?channel=1&subtype=0"
  rtsp_transport: "tcp"

capture:
  resolution: "1280x720"
  framerate: 15
  segment_duration: 10

storage:
  local_buffer_minutes: 30
  segments_dir: "./data/segments"
  database_path: "./data/segments.db"
  max_disk_usage_mb: 2000

s3:
  bucket: "test-bucket"
  region: "ap-south-1"
  prefix: "cameras/{camera_name}/"

server:
  enabled: true
  port: 8080

logging:
  level: "INFO"
  file: "./data/logs/test.log"
"""
    
    @pytest.fixture
    def config_file(self, valid_config_content, tmp_path):
        """Create a temporary config file."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(valid_config_content)
        return config_path
    
    def test_load_valid_config(self, config_file):
        """Test loading a valid configuration."""
        config = load_config(str(config_file))
        
        assert config.get('camera.name') == 'test-camera'
        assert config.get('camera.ip') == '192.168.1.100'
        assert config.get('s3.bucket') == 'test-bucket'
    
    def test_config_not_found(self):
        """Test error when config file not found."""
        with pytest.raises(ConfigurationError) as exc_info:
            load_config('nonexistent.yaml')
        
        assert "not found" in str(exc_info.value)
    
    def test_env_var_substitution(self, tmp_path):
        """Test environment variable substitution."""
        os.environ['TEST_CAMERA_PASS'] = 'secret123'
        
        config_content = """
camera:
  name: "test"
  ip: "192.168.1.1"
  password: "${TEST_CAMERA_PASS}"
  rtsp_path: "/test"
s3:
  bucket: "test"
  region: "us-east-1"
"""
        config_path = tmp_path / "env_config.yaml"
        config_path.write_text(config_content)
        
        config = load_config(str(config_path))
        assert config.get('camera.password') == 'secret123'
        
        # Cleanup
        del os.environ['TEST_CAMERA_PASS']
    
    def test_build_rtsp_url(self, config_file):
        """Test RTSP URL building."""
        config = load_config(str(config_file))
        
        url = config.build_rtsp_url()
        
        assert url.startswith('rtsp://')
        assert 'admin:testpass@' in url
        assert '192.168.1.100:554' in url
    
    def test_get_nested_value(self, config_file):
        """Test getting nested configuration values."""
        config = load_config(str(config_file))
        
        assert config.get('capture.segment_duration') == 10
        assert config.get('server.enabled') is True
        assert config.get('nonexistent.key', 'default') == 'default'
    
    def test_get_paths(self, config_file):
        """Test path getter methods."""
        config = load_config(str(config_file))
        
        assert isinstance(config.get_segments_dir(), Path)
        assert isinstance(config.get_database_path(), Path)
        assert isinstance(config.get_log_file(), Path)
    
    def test_invalid_yaml(self, tmp_path):
        """Test error on invalid YAML."""
        config_path = tmp_path / "invalid.yaml"
        config_path.write_text("invalid: yaml: content: [")
        
        with pytest.raises(ConfigurationError) as exc_info:
            load_config(str(config_path))
        
        assert "Invalid YAML" in str(exc_info.value)
    
    def test_missing_required_field(self, tmp_path):
        """Test validation of required fields."""
        config_content = """
camera:
  name: "test"
  # Missing ip and rtsp_path
s3:
  bucket: "test"
  region: "us-east-1"
"""
        config_path = tmp_path / "incomplete.yaml"
        config_path.write_text(config_content)
        
        with pytest.raises(ConfigurationError) as exc_info:
            load_config(str(config_path))
        
        assert "Required configuration field missing" in str(exc_info.value)
