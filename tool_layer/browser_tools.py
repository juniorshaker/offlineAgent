"""
tool_layer/browser_tools.py
HTTP request tools + Playwright browser automation tools.

Designed for OFFLINE environments:
- Playwright Python package: copy to vendor/playwright/
- Browser binaries: copy to Offlineagent/browsers/
- Set PLAYWRIGHT_BROWSERS_PATH to Offlineagent/browsers/

If Playwright is not available, tools degrade gracefully with clear error messages.
"""

import sys
import os
import json as _json
import threading
from pathlib import Path

# Import the vendored requests
_vendor_path = Path(__file__).resolve().parent.parent / "vendor"
if str(_vendor_path) not in sys.path:
    sys.path.insert(0, str(_vendor_path))

import requests as _requests

# ---------------------------------------------------------------------------
# Playwright availability detection
# ---------------------------------------------------------------------------

_playwright_available = False
_playwright_import_error = ""
_PW = None  # playwright module

_BROWSER_INSTANCE = None
_BROWSER_CONTEXT = None
_BROWSER_PAGE = None
_BROWSER_LOCK = threading.Lock()

_BROWSERS_PATH = None


def _detect_browsers_path(base_dir: Path | None = None) -> str:
    """Detect the browsers directory path, in priority order."""
    # 1. Environment variable
    env_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    if env_path and Path(env_path).exists():
        return env_path

    # 2. Project-local browsers/ directory
    if base_dir is None:
        base_dir = Path(__file__).resolve().parent.parent
    local = base_dir / "browsers"
    if local.exists() and any(local.iterdir()):
        return str(local.resolve())

    # 3. Default Playwright cache
    default = Path.home() / "AppData" / "Local" / "ms-playwright"
    if default.exists():
        return str(default)

    return ""


def _try_import_playwright(base_dir: Path | None = None):
    """Try to import Playwright. Sets module-level flags."""
    global _playwright_available, _playwright_import_error, _PW, _BROWSERS_PATH

    try:
        import playwright
        from playwright.sync_api import sync_playwright
        _PW = playwright
        _playwright_available = True
        _BROWSERS_PATH = _detect_browsers_path(base_dir)
        return True
    except ImportError as e:
        _playwright_import_error = str(e)
        _playwright_available = False
        return False


def _ensure_browser(base_dir: Path | None = None) -> tuple:
    """Ensure a browser page is available. Returns (page, error_message).

    This must be called AFTER init_browser() has been called in the main thread.
    It only creates new Page objects from the existing BrowserContext - no new
    Playwright/event-loop initialization, so it is safe to call from any thread.
    """
    global _BROWSER_INSTANCE, _BROWSER_CONTEXT, _BROWSER_PAGE

    with _BROWSER_LOCK:
        # Reuse existing live page if available
        if _BROWSER_PAGE is not None:
            try:
                _BROWSER_PAGE.title()
                return (_BROWSER_PAGE, "")
            except Exception:
                # Page died, close it and create new below
                try:
                    _BROWSER_PAGE.close()
                except Exception:
                    pass
                _BROWSER_PAGE = None

        if not _playwright_available:
            return (None, f"Playwright not installed. Copy playwright package to vendor/ and browser binaries to browsers/\nImport error: {_playwright_import_error}")

        # Browser must already be initialized (init_browser called in main thread)
        if _BROWSER_CONTEXT is None:
            return (None, "Browser not initialized. The server must call init_browser() at startup in the main thread.")

        # Create a new page from the existing browser context (thread-safe)
        try:
            _BROWSER_PAGE = _BROWSER_CONTEXT.new_page()
            return (_BROWSER_PAGE, "")
        except Exception as e:
            return (None, f"Failed to create browser page: {e}")


def _close_browser():
    """Close browser and clean up globals."""
    global _BROWSER_INSTANCE, _BROWSER_CONTEXT, _BROWSER_PAGE
    try:
        if _BROWSER_PAGE:
            try:
                _BROWSER_PAGE.close()
            except Exception:
                pass
    finally:
        _BROWSER_PAGE = None

    try:
        if _BROWSER_CONTEXT:
            try:
                _BROWSER_CONTEXT.close()
            except Exception:
                pass
    finally:
        _BROWSER_CONTEXT = None

    try:
        if _BROWSER_INSTANCE:
            try:
                _BROWSER_INSTANCE.stop()
            except Exception:
                pass
    finally:
        _BROWSER_INSTANCE = None


# ---------------------------------------------------------------------------
# HTTP tool (always available)
# ---------------------------------------------------------------------------

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
    method = method.upper().strip()
    if method not in ("GET", "POST"):
        return f"[Error] Unsupported method: {method}. Use GET or POST."

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
            text = resp.text() if callable(resp.text) else resp.text
        except Exception:
            text = str(resp.content)[:5000]

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


# ---------------------------------------------------------------------------
# Browser automation tools (Playwright required)
# ---------------------------------------------------------------------------

def browser_status(base_dir: Path | None = None) -> str:
    """Check if browser automation (Playwright) is available.

    Always callable; reports the current status.
    """
    if base_dir is None:
        base_dir = Path(__file__).resolve().parent.parent

    # Try import if not done yet
    if not _playwright_available and not _playwright_import_error:
        _try_import_playwright(base_dir)

    parts = []

    # Playwright package status
    if _playwright_available:
        parts.append("[OK] Playwright Python package available")
    else:
        parts.append(f"[WARN] Playwright Python package not found: {_playwright_import_error}")
        parts.append("  -> Copy 'playwright' folder to Offlineagent/vendor/playwright/")

    # Browser binaries status
    browsers_path = _detect_browsers_path(base_dir)
    if browsers_path:
        bp = Path(browsers_path)
        if bp.exists():
            # Count browser types available
            subdirs = [d.name for d in bp.iterdir() if d.is_dir()]
            parts.append(f"[OK] Browser binaries found at: {browsers_path}")
            parts.append(f"  Available: {', '.join(subdirs) if subdirs else 'none'}")
        else:
            parts.append(f"[WARN] Browsers path set but does not exist: {browsers_path}")
            parts.append("  -> Download browser binaries and place in Offlineagent/browsers/")
    else:
        parts.append("[WARN] No browser binaries found")
        parts.append("  -> Set PLAYWRIGHT_BROWSERS_PATH or place browsers in Offlineagent/browsers/")

    return "\n".join(parts)


def browser_navigate(url: str, base_dir: Path | None = None) -> str:
    """Navigate to a URL in the browser.

    Args:
        url: The URL to navigate to (e.g. http://localhost:8080).
        base_dir: Optional base directory for resolving paths.

    Returns:
        Status and page title.
    """
    if not url:
        return "[Error] URL is required."

    if not url.startswith(("http://", "https://", "file://", "about:", "data:", "blob:")):
        url = "https://" + url

    page, err = _ensure_browser(base_dir)
    if err:
        return f"[Error] {err}"

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        title = page.title()
        url_current = page.url
        return f"[OK] Navigated to: {url_current}\nTitle: {title}"
    except Exception as e:
        return f"[Error] Navigation failed: {e}"


def browser_screenshot(name: str = "screenshot", base_dir: Path | None = None) -> str:
    """Take a screenshot of the current browser page.

    Args:
        name: Screenshot file name (without extension). Saved to output/.
        base_dir: Optional base directory.

    Returns:
        Path to saved screenshot.
    """
    page, err = _ensure_browser(base_dir)
    if err:
        return f"[Error] {err}"

    if base_dir is None:
        base_dir = Path(__file__).resolve().parent.parent

    output_dir = base_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_name = name.replace("/", "_").replace("\\", "_").replace(" ", "_")
    filepath = output_dir / f"{safe_name}.png"

    try:
        page.screenshot(path=str(filepath), full_page=False)
        return f"[OK] Screenshot saved: {filepath}"
    except Exception as e:
        return f"[Error] Screenshot failed: {e}"


def browser_click(selector: str, base_dir: Path | None = None) -> str:
    """Click an element on the page by CSS selector.

    Args:
        selector: CSS selector of the element to click.
        base_dir: Optional base directory.

    Returns:
        Confirmation of click action.
    """
    if not selector:
        return "[Error] CSS selector is required."

    page, err = _ensure_browser(base_dir)
    if err:
        return f"[Error] {err}"

    try:
        element = page.locator(selector).first
        if not element.is_visible(timeout=5000):
            return f"[Error] Element not visible: {selector}"
        element.click()
        return f"[OK] Clicked: {selector}"
    except Exception as e:
        return f"[Error] Click failed on '{selector}': {e}"


def browser_type(selector: str, text: str, base_dir: Path | None = None) -> str:
    """Type text into an input element.

    Args:
        selector: CSS selector of the input element.
        text: Text to type.
        base_dir: Optional base directory.

    Returns:
        Confirmation.
    """
    if not selector:
        return "[Error] CSS selector is required."

    page, err = _ensure_browser(base_dir)
    if err:
        return f"[Error] {err}"

    try:
        element = page.locator(selector).first
        if not element.is_visible(timeout=5000):
            return f"[Error] Element not visible: {selector}"
        element.fill(text)
        return f"[OK] Typed '{text}' into: {selector}"
    except Exception as e:
        return f"[Error] Type failed on '{selector}': {e}"


def browser_get_content(selector: str = "", max_length: int = 8000, base_dir: Path | None = None) -> str:
    """Get the text content of the current page or a specific element.

    Args:
        selector: Optional CSS selector. If empty, gets full page text.
        max_length: Maximum characters to return.
        base_dir: Optional base directory.

    Returns:
        Text content.
    """
    page, err = _ensure_browser(base_dir)
    if err:
        return f"[Error] {err}"

    try:
        if selector:
            element = page.locator(selector).first
            if not element.is_visible(timeout=3000):
                return f"[Error] Element not visible: {selector}"
            text = element.inner_text()
        else:
            text = page.inner_text("body")

        if len(text) > max_length:
            text = text[:max_length] + f"\n\n[...truncated {len(text) - max_length} chars...]"
        return text
    except Exception as e:
        return f"[Error] Failed to get content: {e}"


def browser_get_html(selector: str = "", base_dir: Path | None = None) -> str:
    """Get the HTML of the current page or a specific element.

    Args:
        selector: Optional CSS selector. If empty, gets full page HTML.
        base_dir: Optional base directory.

    Returns:
        HTML content (truncated at 10000 chars).
    """
    page, err = _ensure_browser(base_dir)
    if err:
        return f"[Error] {err}"

    try:
        if selector:
            element = page.locator(selector).first
            html = element.inner_html()
        else:
            html = page.content()

        max_len = 10000
        if len(html) > max_len:
            html = html[:max_len] + f"\n\n[...truncated {len(html) - max_len} chars...]"
        return html
    except Exception as e:
        return f"[Error] Failed to get HTML: {e}"


def browser_exec(js: str, base_dir: Path | None = None) -> str:
    """Execute JavaScript in the browser page context.

    Args:
        js: JavaScript code to execute.
        base_dir: Optional base directory.

    Returns:
        Result of the JavaScript execution.
    """
    if not js:
        return "[Error] JavaScript code is required."

    page, err = _ensure_browser(base_dir)
    if err:
        return f"[Error] {err}"

    try:
        result = page.evaluate(js)
        result_str = str(result)
        if len(result_str) > 3000:
            result_str = result_str[:3000] + "\n\n[...truncated]"
        return f"[OK] JS executed. Result: {result_str}"
    except Exception as e:
        return f"[Error] JS execution failed: {e}"


def browser_close() -> str:
    """Close the browser instance. Called automatically on /exit, or manually.

    Returns:
        Status message.
    """
    with _BROWSER_LOCK:
        _close_browser()
    return "[OK] Browser closed."


# ---------------------------------------------------------------------------
# Startup initialization
# ---------------------------------------------------------------------------

def init_browser(base_dir: Path | None = None):
    """Initialize Playwright AND launch the browser in the CURRENT thread.

    IMPORTANT: Must be called from the MAIN thread (e.g. server startup).
    Playwright's sync API uses asyncio/greenlet internally and cannot be
    initialized from a worker thread created by threading.Thread.

    After this call, _ensure_browser() can safely create pages from any thread.
    """
    global _BROWSER_INSTANCE, _BROWSER_CONTEXT, _BROWSER_PAGE, _playwright_available, _BROWSERS_PATH

    if base_dir is None:
        base_dir = Path(__file__).resolve().parent.parent

    # Step 1: Import Playwright (in current thread = main thread)
    if not _try_import_playwright(base_dir):
        return f"[WARN] Playwright not available: {_playwright_import_error}"

    # Step 2: Check browser binaries
    browsers_path = _detect_browsers_path(base_dir)
    if not browsers_path:
        candidate_paths = [
            base_dir / "browsers",
            Path.home() / "AppData" / "Local" / "ms-playwright",
        ]
        for cp in candidate_paths:
            if cp.exists() and any(cp.iterdir()):
                browsers_path = str(cp.resolve())
                _BROWSERS_PATH = browsers_path
                break

    if not browsers_path:
        return "[WARN] No browser binaries found. Place chromium in Offlineagent/browsers/ or set PLAYWRIGHT_BROWSERS_PATH."

    # Step 3: Launch Playwright and browser (ALL in main thread)
    try:
        from playwright.sync_api import sync_playwright

        # CRITICAL: Set env var BEFORE .start() so the driver picks up our path
        _BROWSERS_PATH = browsers_path
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = browsers_path
        # Correct idiom: chain .start() after construction
        playwright = sync_playwright().start()
        _BROWSER_INSTANCE = playwright


        # Try to launch available browsers
        launch_errors = []
        for bt in ["chromium", "firefox", "webkit"]:
            try:
                browser_obj = getattr(playwright, bt, None)
                if browser_obj is None:
                    continue
                browser = browser_obj.launch(headless=True)
                context = browser.new_context(
                    viewport={"width": 1280, "height": 720},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 OfflineAgent/1.0",
                )
                _BROWSER_CONTEXT = context
                _BROWSER_PAGE = context.new_page()
                return f"[OK] Playwright ready ({bt}). Browsers: {browsers_path}"
            except Exception as launch_e:
                launch_errors.append(f"{bt}: {launch_e}")
                continue

        # No browser launched
        _playwright_available = False
        _close_browser()
        err_detail = "; ".join(launch_errors) if launch_errors else "unknown"
        return f"[WARN] Could not launch any browser from {browsers_path}. Errors: {err_detail}"

    except Exception as e:
        _playwright_available = False
        _close_browser()
        return f"[WARN] Failed to launch browser: {e}"
