import json
import sys
from pathlib import Path


DEFAULT_MODEL_NAME = "gemini-2.5-flash"
DEFAULT_INPUT_FOLDER_NAME = "Videos"
DEFAULT_OUTPUT_FOLDER_NAME = "output"


def get_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


APP_DIR = get_app_dir()
CONFIG_PATH = APP_DIR / "config.json"

DEFAULT_CONFIG = {
    "gemini_api_key": "YOUR_GEMINI_API_KEY_HERE",
    "model_name": DEFAULT_MODEL_NAME,
    "default_input_folder": str(APP_DIR / DEFAULT_INPUT_FOLDER_NAME),
    "default_output_folder": str(APP_DIR / DEFAULT_OUTPUT_FOLDER_NAME),
}


def load_app_config() -> dict:
    if not CONFIG_PATH.exists():
        return DEFAULT_CONFIG.copy()

    try:
        loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return DEFAULT_CONFIG.copy()

    config = DEFAULT_CONFIG.copy()
    if isinstance(loaded, dict):
        for key in config:
            value = loaded.get(key, config[key])
            config[key] = "" if value is None else str(value)
    return config


def save_app_config(config: dict) -> Path:
    merged = DEFAULT_CONFIG.copy()
    for key in merged:
        value = config.get(key, merged[key])
        merged[key] = "" if value is None else str(value)

    CONFIG_PATH.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return CONFIG_PATH


def resolve_path_setting(value: str, fallback: Path) -> Path:
    text = (value or "").strip()
    if not text:
        return fallback

    path = Path(text)
    if not path.is_absolute():
        path = APP_DIR / path
    return path
