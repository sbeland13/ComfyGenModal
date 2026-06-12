"""Read/write persistent configuration at ~/.comfy-gen/config.json."""

import json
import os
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".comfy-gen"
CONFIG_FILE = CONFIG_DIR / "config.json"
INIT_FILE = CONFIG_DIR / "init.json"

DEFAULTS: dict[str, Any] = {
    "modal_app_name": "comfy-gen",
    "modal_volume_name": "comfy-gen-comfyui",
    "modal_secret_name": "comfy-gen-storage",
    "modal_jobs_name": "comfy-gen-jobs",
    "modal_function_name": "run_job",
    # Storage (S3-compatible)
    "aws_access_key_id": "",
    "aws_secret_access_key": "",
    "s3_region": "eu-west-2",
    "s3_bucket": "",
    "s3_endpoint_url": "",
    "civitai_token": "",
    "timeout_seconds": 1200,
    "poll_interval_seconds": 3,
}

# Mapping: env var name -> config key
ENV_MAP = {
    "COMFY_GEN_MODAL_APP_NAME": "modal_app_name",
    "COMFY_GEN_MODAL_VOLUME_NAME": "modal_volume_name",
    "COMFY_GEN_MODAL_SECRET_NAME": "modal_secret_name",
    "COMFY_GEN_MODAL_JOBS_NAME": "modal_jobs_name",
    "COMFY_GEN_MODAL_FUNCTION_NAME": "modal_function_name",
    "AWS_ACCESS_KEY_ID": "aws_access_key_id",
    "AWS_SECRET_ACCESS_KEY": "aws_secret_access_key",
    "S3_REGION": "s3_region",
    "S3_BUCKET": "s3_bucket",
    "S3_ENDPOINT_URL": "s3_endpoint_url",
    "CIVITAI_TOKEN": "civitai_token",
    "COMFY_GEN_TIMEOUT": "timeout_seconds",
    "COMFY_GEN_POLL_INTERVAL": "poll_interval_seconds",
}

PASSTHROUGH_ENV_VARS = {
    "MODAL_TOKEN_ID",
    "MODAL_TOKEN_SECRET",
    "MODAL_PROFILE",
}


def _load_dotenv() -> dict[str, str]:
    """Load .env file from the project directory if it exists."""
    env_vals: dict[str, str] = {}
    cwd = Path.cwd()
    for d in [cwd, *cwd.parents]:
        env_file = d / ".env"
        if env_file.exists():
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    key, _, value = line.partition("=")
                    env_key = key.strip()
                    env_value = value.strip()
                    if env_key in ENV_MAP:
                        env_vals[ENV_MAP[env_key]] = env_value
                    if env_key in PASSTHROUGH_ENV_VARS and env_value and env_key not in os.environ:
                        os.environ[env_key] = env_value
            break
    return env_vals


def load() -> dict[str, Any]:
    """Load config with priority: config.json > .env > env vars > defaults."""
    config = dict(DEFAULTS)

    # Layer 1: environment variables
    for env_key, config_key in ENV_MAP.items():
        val = os.environ.get(env_key)
        if val:
            config[config_key] = val

    # Layer 2: .env file (overrides env vars)
    dotenv = _load_dotenv()
    for key, val in dotenv.items():
        if val:
            config[key] = val

    # Layer 3: config.json (highest priority)
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            config.update(json.load(f))

    # Coerce numeric fields
    for key in ("timeout_seconds", "poll_interval_seconds"):
        if isinstance(config[key], str):
            try:
                config[key] = int(config[key])
            except ValueError:
                pass

    return config


def save(config: dict[str, Any]) -> None:
    """Write config to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def get(key: str) -> Any:
    """Get a single config value."""
    config = load()
    if key not in config:
        return None
    return config[key]


def set_value(key: str, value: str) -> dict[str, Any]:
    """Set a single config value. Coerces numeric strings to int."""
    config = load()
    if key in ("timeout_seconds", "poll_interval_seconds"):
        try:
            value = int(value)
        except ValueError:
            pass
    config[key] = value
    save(config)
    return config


def is_initialized() -> bool:
    """Check if comfy-gen has been initialized."""
    return INIT_FILE.exists()


def load_init() -> dict[str, Any]:
    """Load the init marker data."""
    if not INIT_FILE.exists():
        return {}
    with open(INIT_FILE) as f:
        return json.load(f)


def save_init(data: dict[str, Any]) -> None:
    """Write the init marker to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(INIT_FILE, "w") as f:
        json.dump(data, f, indent=2)
