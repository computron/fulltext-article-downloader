import os
import logging
import sys

__version__ = "0.1.0"

# Load API keys from configuration file if present
def _load_api_keys():
    """Load API keys from configuration file into environment variables, if not already set."""
    config_path = os.path.expanduser("~/.fulltext_keys")
    try:
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    if key and value and key not in os.environ:
                        os.environ[key] = value
    except Exception as e:
        # If any error occurs, we simply don't load keys (user can still set them manually)
        logging.warning(f"Could not load API keys from config file: {e}")

_load_api_keys()

from .downloader import download_article, bulk_download_articles, get_publisher_from_doi, PUBLISHER_TOOL_MAP
