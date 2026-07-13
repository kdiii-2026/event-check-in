import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

_file_cache = None


def _file_config():
    global _file_cache
    if _file_cache is None:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH) as f:
                _file_cache = json.load(f)
        else:
            _file_cache = {}
    return _file_cache


def get(key, default=""):
    """Environment variable (e.g. WEBAPP_URL) wins over config.json (e.g. webapp_url).

    Production hosts should set env vars instead of shipping config.json with secrets.
    """
    env_val = os.environ.get(key.upper())
    if env_val is not None:
        return env_val
    return _file_config().get(key, default)
