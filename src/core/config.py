#!/usr/bin/env python3
"""
Centralized configuration for Paper Finder.

All timeouts, domains, API keys, and settings in one place.
"""

import os
from pathlib import Path
from typing import Dict, List
from dataclasses import dataclass


@dataclass
class NetworkConfig:
    """Network-related settings."""
    timeout_short: int = 15  # For API calls
    timeout_medium: int = 30  # For downloads
    timeout_long: int = 60  # For scraping/browser
    max_retries: int = 3
    retry_backoff: float = 1.0  # Seconds
    max_workers: int = 5  # Parallel execution
    user_agent: str = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


@dataclass
class ValidationConfig:
    """PDF validation settings."""
    min_size_kb: int = 50  # Minimum PDF size
    max_size_mb: int = 100  # Maximum PDF size (sanity check)
    title_similarity_threshold: float = 0.6  # For title matching


@dataclass
class CacheConfig:
    """Caching settings."""
    enabled: bool = True
    cache_file: Path = None
    max_age_hours: int = 24  # For Sci-Hub domain cache
    
    def __post_init__(self):
        if self.cache_file is None:
            self.cache_file = Path.home() / ".paper_finder_cache.json"


@dataclass
class SciHubConfig:
    """Sci-Hub specific settings."""
    domains: List[str] = None
    check_reachability: bool = True
    cache_working_domain: bool = True
    
    def __post_init__(self):
        if self.domains is None:
            self.domains = [
                "https://sci-hub.st",
                "https://sci-hub.se",
                "https://sci-hub.ru",
                "https://sci-hub.wf",
                "https://sci-hub.ee",
                "https://sci-hub.ren",
            ]


@dataclass
class APIConfig:
    """External API settings."""
    unpaywall_email: str = None
    semantic_scholar_api_key: str = None
    
    def __post_init__(self):
        # Load from environment variables
        if self.unpaywall_email is None:
            self.unpaywall_email = os.environ.get('UNPAYWALL_EMAIL', 'test@test.com')
        
        if self.semantic_scholar_api_key is None:
            self.semantic_scholar_api_key = os.environ.get('SEMANTIC_SCHOLAR_API_KEY')


@dataclass
class PipelineConfig:
    """Pipeline execution settings."""
    parallel_execution: bool = True
    method_timeout: int = 45  # Per-group timeout (all methods in tier)
    group_timeout: int = 50  # Maximum time for one tier before moving to next
    
    # Browser open detection - stop searching if OA found
    stop_on_browser: bool = True


@dataclass
class TelegramConfig:
    """Telegram settings for both bot and underground access."""
    # Bot settings (for our own bot)
    token: str = None  # Bot token from BotFather
    admin_chat_id: str = None  # Optional admin notifications
    max_file_size_mb: int = 50  # Telegram limit
    
    # Underground bot access (Telethon client)
    api_id: str = None  # Telegram API ID from my.telegram.org
    api_hash: str = None  # Telegram API hash
    phone: str = None  # Phone number for first-time auth
    underground_enabled: bool = False  # Enable underground bot access
    underground_bots: List[str] = None  # List of bots to use
    rate_limit_per_hour: int = 20  # Max requests per hour
    
    def __post_init__(self):
        # Try to load from environment if not set
        if self.token is None:
            self.token = os.getenv('TELEGRAM_BOT_TOKEN')
        
        if self.api_id is None:
            self.api_id = os.getenv('TELEGRAM_API_ID')
        
        if self.api_hash is None:
            self.api_hash = os.getenv('TELEGRAM_API_HASH')
        
        if self.phone is None:
            self.phone = os.getenv('TELEGRAM_PHONE')
        
        # Default bot list - EXPANDED
        if self.underground_bots is None:
            self.underground_bots = [
                '@scihubot',              # Best for papers
                '@libgen_scihub_bot',     # LibGen + books
                '@scihub_bot',            # Alternative
                '@nexus_search_bot',      # Nexus STC
                '@booksandpapers_bot',    # Community
                '@libgen_robot',          # LibGen alt
                '@scihubot_bot',          # Scihubot alt
                '@zlibrary_bot',          # Z-Library
                '@bookfi_bot',            # BookFi
                '@pdfdrive_bot',          # PDF Drive
                '@freebookspot_bot',      # Free Book Spot
                '@bookzz_bot',            # BookZZ
            ]


class Config:
    """
    Main configuration object.
    
    Usage:
        config = Config()
        session = requests.Session()
        session.headers.update({'User-Agent': config.network.user_agent})
    """
    
    def __init__(self):
        self.network = NetworkConfig()
        self.validation = ValidationConfig()
        self.cache = CacheConfig()
        self.scihub = SciHubConfig()
        self.api = APIConfig()
        self.pipeline = PipelineConfig()
        self.telegram = TelegramConfig()
    
    @classmethod
    def from_file(cls, config_file: Path) -> "Config":
        """
        Load configuration from YAML file.
        
        Example config.yaml:
        
        network:
          timeout_short: 10
          max_workers: 8
        
        scihub:
          domains:
            - https://sci-hub.st
            - https://sci-hub.se
        
        api:
          unpaywall_email: your.email@example.com
        """
        import yaml
        
        config = cls()
        
        if not config_file.exists():
            return config
        
        try:
            with open(config_file) as f:
                data = yaml.safe_load(f)
            
            # Update config from file
            if 'network' in data:
                for key, value in data['network'].items():
                    if hasattr(config.network, key):
                        setattr(config.network, key, value)
            
            if 'validation' in data:
                for key, value in data['validation'].items():
                    if hasattr(config.validation, key):
                        setattr(config.validation, key, value)
            
            if 'scihub' in data:
                for key, value in data['scihub'].items():
                    if hasattr(config.scihub, key):
                        setattr(config.scihub, key, value)
            
            if 'api' in data:
                for key, value in data['api'].items():
                    if hasattr(config.api, key):
                        setattr(config.api, key, value)
            
            if 'pipeline' in data:
                for key, value in data['pipeline'].items():
                    if hasattr(config.pipeline, key):
                        setattr(config.pipeline, key, value)
            
            if 'telegram' in data:
                for key, value in data['telegram'].items():
                    if hasattr(config.telegram, key):
                        setattr(config.telegram, key, value)
            
        except Exception as e:
            print(f"Warning: Could not load config from {config_file}: {e}")
        
        return config
    
    def to_dict(self) -> Dict:
        """Export configuration as dictionary."""
        return {
            'network': self.network.__dict__,
            'validation': self.validation.__dict__,
            'cache': {k: str(v) if isinstance(v, Path) else v 
                     for k, v in self.cache.__dict__.items()},
            'scihub': self.scihub.__dict__,
            'api': self.api.__dict__,
            'pipeline': self.pipeline.__dict__,
            'telegram': self.telegram.__dict__,
        }


# Global default config instance
_default_config = None


def get_config() -> Config:
    """Get global configuration instance."""
    global _default_config
    if _default_config is None:
        # Try to load from config file
        config_file = Path.home() / ".paper_finder_config.yaml"
        if not config_file.exists():
            # Try project directory
            config_file = Path(__file__).parent.parent.parent / "config.yaml"
        
        if config_file.exists():
            _default_config = Config.from_file(config_file)
        else:
            _default_config = Config()
    
    return _default_config


def load_config(config_path: str = None) -> Config:
    """
    Load configuration from a specific file path.
    
    Args:
        config_path: Path to config file (optional)
    
    Returns:
        Config object
    """
    if config_path and Path(config_path).exists():
        return Config.from_file(Path(config_path))
    else:
        return get_config()


def set_config(config: Config):
    """Set global configuration instance."""
    global _default_config
    _default_config = config
