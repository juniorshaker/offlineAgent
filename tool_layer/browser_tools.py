"""
tool_layer/browser_tools.py
HTTP request tools using vendor/requests. Optional Playwright support.
"""

import sys
from pathlib import Path

# Import the vendored requests
_vendor_path = Path(__file__).resolve().parent.parent / "vendor"
if str(_vendor_path) not in sys.path:
    sys.path.insert(0, str(_vendor_path))

import requests as _requests


def web_fetch(url: str, method: str = "GET", body: str = "", headers: str = "", timeout: int = 30) -> str:
    """Make an HTTP request.

    Args:
        url: Target URL.
        method: HTTP method (GET or POST).
        body: Request body for POST (JSON string).
        headers: Extra headers as JSON string.
        timeout: Seconds before giving up.

    Returns:
        Response body as text.
    """
    import json as _json

    method = method.upper().strip()
    if method not in ("GET", "POST"):
        return f"[Error] Unsupported method: {method}. Use GET or POST."

    # Parse optional headers
    req_headers = {}
    if headers:
        try:
            req_headers = _json.loads(headers)
        except _json.JSONDecodeError:
            return f"[Error] Invalid headers JSON: {headers}"

    try:
        if method == "GET":
            resp = _requests.get(url, headers=req_headers or None, timeout=timeout)
        else:
            body_data = None
            if body:
                try:
                    body_data = _json.loads(body)
                except _json.JSONDecodeError:
                    body_data = body
            resp = _requests.post(url, headers=req_headers or None, json=body_data, timeout=timeout)

        status = resp.status_code
        try:
            text = resp.text()
        except Exception:
            text = ""

        if status >= 400:
            return f"[HTTP {status}] {text[:500]}"

        max_len = 5000
        if len(text) > max_len:
            return text[:max_len] + f"\n\n[...truncated {len(text) - max_len} chars...]"
        return text if text else f"[HTTP {status}] (empty body)"

    except _requests.ConnectionError as e:
        return f"[Error] Connection failed: {e}"
    except Exception as e:
        return f"[Error] {e}"


def browser_status(base_dir: Path) -> str:
    """Check if browser automation (Playwright) is available."""
    browsers_dir = base_dir / "browsers"
    import os
    pw_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")

    if pw_path:
        if Path(pw_path).exists():
            return f"[OK] Playwright browsers found at: {pw_path}"
        else:
            return f"[WARN] PLAYWRIGHT_BROWSERS_PATH set but path not found: {pw_path}"

    if browsers_dir.exists() and any(browsers_dir.iterdir()):
        return f"[OK] Playwright browsers found at: {browsers_dir}"

    return "[WARN] Playwright not available. Install browser binaries to ./browsers/ or set PLAYWRIGHT_BROWSERS_PATH."
