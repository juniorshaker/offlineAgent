"""
orchestrator/error_recovery.py
Learn-from-error system: observe model errors, record capability
limitations, and proactively strip incompatible content before retry.
"""

import json
from pathlib import Path

CAPABILITIES_FILE = "model_capabilities.json"

# Error message keywords → unsupported content type
ERROR_TYPE_MAP = {
    "image": "image",
    "multimodal": "image",
    "picture": "image",
    "photo": "image",
    "video": "video",
    "audio": "audio",
    "multipart": "multipart",
    "media": "image",
    "screenshot": "image",
}


def _infer_unsupported_type(error_message: str) -> str | None:
    """Infer what content type the model doesn't support from the error."""
    lower = error_message.lower()
    for keyword, ctype in ERROR_TYPE_MAP.items():
        if keyword in lower:
            return ctype
    # JSON parse errors (Expecting value, malformed JSON) often caused by
    # multimodal content (images) hitting a non-vision API endpoint.
    # Return None here; the caller should check for embedded images separately.
    return None


def _load_capabilities(base_dir: Path) -> dict:
    """Load the model capabilities database."""
    path = base_dir / CAPABILITIES_FILE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_capabilities(base_dir: Path, caps: dict):
    """Persist the model capabilities database."""
    path = base_dir / CAPABILITIES_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(caps, ensure_ascii=False, indent=2), encoding="utf-8")


def _has_embedded_images(messages: list[dict]) -> bool:
    """Check if any message contains image content blocks or data URLs."""
    import re
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if "image_url" in block or block.get("type", "") == "image_url":
                        return True
        elif isinstance(content, str):
            if re.search(r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+', content):
                return True
    return False


def _is_json_parse_error(error_message: str) -> bool:
    """Check if error is a JSON parsing error (empty/malformed API response)."""
    lower = error_message.lower()
    json_err_keywords = [
        "expecting value", "json", "decode", "empty response",
        "malformed", "parse error", "char 0",
    ]
    return any(kw in lower for kw in json_err_keywords)


def observe_error(model: str, error_message: str, messages_snapshot: list[dict], base_dir: Path):
    """Learn from an error: record model capability deficiency.

    Args:
        model: Model name that produced the error.
        error_message: The error text from the API.
        messages_snapshot: The messages that were sent (for reference).
        base_dir: Project base directory.
    """
    unsupported_type = _infer_unsupported_type(error_message)
    if not unsupported_type:
        return  # Can't infer anything useful

    caps = _load_capabilities(base_dir)

    if model not in caps:
        caps[model] = {}

    entry = caps[model]
    unsupported = entry.get("unsupported", [])
    if unsupported_type not in unsupported:
        unsupported.append(unsupported_type)

    from datetime import datetime
    entry["unsupported"] = unsupported
    entry["last_seen"] = datetime.now().isoformat()
    entry["error_count"] = entry.get("error_count", 0) + 1
    entry["error_snippet"] = error_message[:200]

    _save_capabilities(base_dir, caps)


def check_before_send(model: str, messages: list[dict], base_dir: Path) -> list[dict] | None:
    """Check if the model has known unsupported content types.

    If yes, proactively strip incompatible blocks from messages.
    Returns modified messages or None if no changes needed.
    """
    caps = _load_capabilities(base_dir)
    model_caps = caps.get(model, {})
    unsupported = model_caps.get("unsupported", [])

    if not unsupported:
        # Even without known capabilities, check for embedded images
        # which can cause JSON parse errors on non-vision models
        if _has_embedded_images(messages):
            return _strip_unsupported(messages, ["image"])
        return None

    return _strip_unsupported(messages, unsupported)


def repair_after_error(model: str, error_message: str, messages: list[dict], base_dir: Path) -> list[dict]:
    """After an error, learn from it and repair messages for retry."""
    observe_error(model, error_message, messages, base_dir)

    unsupported_type = _infer_unsupported_type(error_message)
    if unsupported_type:
        return _strip_unsupported(messages, [unsupported_type])

    # JSON parse errors often caused by multimodal content in non-vision models
    if _is_json_parse_error(error_message) and _has_embedded_images(messages):
        return _strip_unsupported(messages, ["image"])

    return messages



def _build_image_description(block: dict) -> str:
    """Build a text description of an image block for models that can't handle images."""
    img_url = block.get("image_url", {}).get("url", "") if isinstance(block.get("image_url"), dict) else ""
    if not img_url:
        block_type = block.get("type", "unknown")
        return f"[???????{block_type}??]"

    # Extract basic info from data URL
    import base64
    img_info = "[??]"
    if img_url.startswith("data:image/"):
        parts = img_url.split(";")
        mime = parts[0].replace("data:", "") if parts else "image/unknown"
        fmt = mime.replace("image/", "").upper()
        # Calculate approximate size from base64 data
        data_part = img_url.split(",")[-1] if "," in img_url else ""
        try:
            size_bytes = len(base64.b64decode(data_part + "===", validate=False))
            if size_bytes > 1024 * 1024:
                size_str = f"?{size_bytes / (1024*1024):.1f}MB"
            elif size_bytes > 1024:
                size_str = f"?{size_bytes / 1024:.0f}KB"
            else:
                size_str = f"{size_bytes}B"
        except Exception:
            size_str = "????"
        img_info = f"[??: ??={fmt}, ??={size_str}]"
    elif img_url.startswith("http"):
        img_info = f"[??: ??URL={img_url[:80]}...]"

    return f"{img_info}\n[??: ??????????????????????????????????????????]"

def _strip_unsupported(messages: list[dict], unsupported: list[str]) -> list[dict]:
    """Remove unsupported content blocks from messages."""
    stripped = []
    changed = False

    for msg in messages:
        content = msg.get("content")

        if isinstance(content, str):
            stripped.append(msg)
            continue

        if isinstance(content, list):
            new_content = []
            for block in content:
                if not isinstance(block, dict):
                    new_content.append(block)
                    continue

                block_type = block.get("type", "")
                should_strip = False
                for u in unsupported:
                    if u in block_type.lower():
                        should_strip = True
                        break
                    # Also check for image_url fields
                    if u == "image" and "image_url" in block:
                        should_strip = True
                        break

                if should_strip:
                    changed = True
                    img_desc = _build_image_description(block)
                    new_content.append({
                        "type": "text",
                        "text": img_desc,
                    })
                else:
                    new_content.append(block)

            stripped.append({**msg, "content": new_content})
        else:
            stripped.append(msg)

    return stripped if changed else messages
