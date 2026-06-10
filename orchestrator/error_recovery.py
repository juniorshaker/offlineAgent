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
        return None

    return _strip_unsupported(messages, unsupported)


def repair_after_error(model: str, error_message: str, messages: list[dict], base_dir: Path) -> list[dict]:
    """After an error, learn from it and repair messages for retry."""
    observe_error(model, error_message, messages, base_dir)

    unsupported_type = _infer_unsupported_type(error_message)
    if unsupported_type:
        return _strip_unsupported(messages, [unsupported_type])
    return messages


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
                    new_content.append({
                        "type": "text",
                        "text": f"[Content removed: {block_type} not supported by this model]",
                    })
                else:
                    new_content.append(block)

            stripped.append({**msg, "content": new_content})
        else:
            stripped.append(msg)

    return stripped if changed else messages
