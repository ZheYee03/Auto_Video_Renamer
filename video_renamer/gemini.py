import json
import re
from typing import List

from google import genai
from google.genai import types
from PIL import Image

from video_renamer.config import DEFAULT_MODEL_NAME, load_app_config
from video_renamer.labels import sanitize_label

SYSTEM_PROMPT = """
You are a file-renaming assistant for short videos.

Look at the provided frames and return one short filename label that describes the clip.

Rules:
1. Output JSON only.
2. proposed_label must be lowercase snake_case, no extension.
3. Use only letters, numbers, and underscores.
4. Keep it short, specific, and practical.
5. Avoid vague labels like video, clip, scene, content, or short.
6. Use the visible subject, action, product, setting, or theme when possible.
7. If uncertain, still return valid JSON and set needs_review to true.
""".strip()

USER_PROMPT = """
Analyze these frames from one short video of any category.

Return JSON with:
- proposed_label
- confidence
- needs_review
""".strip()

SCHEMA = {
    "type": "object",
    "properties": {
        "proposed_label": {"type": "string"},
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
        },
        "needs_review": {"type": "boolean"},
    },
    "required": [
        "proposed_label",
        "confidence",
        "needs_review",
    ],
}


def resolve_api_keys() -> list[str]:
    config = load_app_config()
    config_key = (config.get("gemini_api_key", "") or "").strip()
    if config_key and config_key != "YOUR_GEMINI_API_KEY_HERE":
        return [config_key]
    return []


def resolve_model_name() -> str:
    config = load_app_config()
    model_name = (config.get("model_name", "") or "").strip()
    return model_name or DEFAULT_MODEL_NAME


def get_runtime_gemini_settings() -> dict:
    api_keys = resolve_api_keys()
    return {
        "api_key": api_keys[0] if api_keys else "",
        "api_keys": api_keys,
        "model_name": resolve_model_name(),
    }


def test_api_key(api_key: str | None = None, model_name: str | None = None) -> tuple[bool, str]:
    key = (api_key or "").strip() or get_runtime_gemini_settings()["api_key"]
    chosen_model = (model_name or "").strip() or resolve_model_name()

    if not key:
        return False, "Gemini API key is missing."

    client = None
    try:
        client = genai.Client(api_key=key)
        response = client.models.generate_content(
            model=chosen_model,
            contents=["Respond with the word OK."],
            config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=8,
            ),
        )

        text = (getattr(response, "text", None) or "").strip()
        if not text:
            return False, "Gemini returned an empty response."

        if "OK" not in text.upper():
            return False, f"Unexpected validation response: {text}"

        return True, f"API key is valid for model '{chosen_model}'."
    except Exception as error:
        return False, f"Gemini API validation failed: {error}"
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


def fallback_result(reason: str) -> dict:
    return {
        "proposed_label": "review_needed",
        "confidence": 0.0,
        "needs_review": True,
        "reason": reason,
    }


def extract_json_from_text(text: str) -> dict:
    """
    Try to recover JSON object from messy text.
    """
    if not text or not text.strip():
        raise ValueError("Empty response text")

    text = text.strip()

    try:
        return json.loads(text)
    except Exception:
        pass

    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))

    match = re.search(r"(\{.*\})", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))

    raise ValueError(f"Could not extract valid JSON from response: {text[:200]}")


def normalize_result(result: dict) -> dict:
    proposed_label = sanitize_label(result.get("proposed_label", "review_needed"))

    confidence = result.get("confidence", 0.0)
    try:
        confidence = float(confidence)
    except Exception:
        confidence = 0.0

    confidence = max(0.0, min(1.0, confidence))

    needs_review = result.get("needs_review", False)
    if not isinstance(needs_review, bool):
        needs_review = True

    return {
        "proposed_label": proposed_label,
        "confidence": confidence,
        "needs_review": needs_review,
        "reason": result.get("reason", ""),
    }


def salvage_partial_result(text: str) -> dict | None:
    if not text:
        return None

    label_match = re.search(r'"proposed_label"\s*:\s*"([^"]+)"', text)

    if not label_match:
        return None

    label = sanitize_label(label_match.group(1))

    return {
        "proposed_label": label,
        "confidence": 0.3,
        "needs_review": True,
    }


def get_gemini_label(frame_paths: List[str]) -> dict:
    runtime = get_runtime_gemini_settings()
    api_keys = runtime["api_keys"]
    model_name = runtime["model_name"]

    if not api_keys:
        return fallback_result("Missing Gemini API key in config.json")

    images = []

    try:
        for path in frame_paths:
            images.append(Image.open(path))

        last_error = None

        for api_key in api_keys:
            client = None
            try:
                client = genai.Client(api_key=api_key)

                for _ in range(2):
                    try:
                        response = client.models.generate_content(
                            model=model_name,
                            contents=[SYSTEM_PROMPT, USER_PROMPT, *images],
                            config=types.GenerateContentConfig(
                                response_mime_type="application/json",
                                response_schema=SCHEMA,
                                temperature=0.0,
                                max_output_tokens=512,
                            ),
                        )

                        if getattr(response, "parsed", None):
                            return normalize_result(response.parsed)

                        raw_text = getattr(response, "text", None)
                        if raw_text:
                            try:
                                parsed = extract_json_from_text(raw_text)
                                return normalize_result(parsed)
                            except Exception:
                                salvaged = salvage_partial_result(raw_text)
                                if salvaged:
                                    return normalize_result(salvaged)
                    except Exception as inner_error:
                        last_error = inner_error
            except Exception as error:
                last_error = error
                print(f"API key failed, trying next key: {error}")
            finally:
                if client is not None:
                    try:
                        client.close()
                    except Exception:
                        pass

        return fallback_result(f"All API keys failed: {last_error}")
    finally:
        for image in images:
            try:
                image.close()
            except Exception:
                pass
