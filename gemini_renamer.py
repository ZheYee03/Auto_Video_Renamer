from video_renamer.gemini import (
    SCHEMA,
    SYSTEM_PROMPT,
    USER_PROMPT,
    extract_json_from_text,
    fallback_result,
    get_gemini_label,
    get_runtime_gemini_settings,
    normalize_result,
    resolve_api_keys,
    resolve_model_name,
    salvage_partial_result,
    test_api_key,
)
from video_renamer.labels import sanitize_label

API_KEYS = resolve_api_keys()
MODEL_NAME = resolve_model_name()
