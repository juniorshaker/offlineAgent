"""
evaluation/config_validator.py
Startup self-check: validates config.yaml, skills paths, and optional deps.
"""

import os
import sys
from pathlib import Path


def _expand_path(path_str: str, base_dir: Path) -> Path:
    """Expand ~ and resolve relative paths."""
    s = os.path.expanduser(path_str)
    p = Path(s)
    if not p.is_absolute():
        p = (base_dir / p).resolve()
    return p


def run_self_check(config: dict, base_dir: Path) -> list[str]:
    """Run all startup checks. Returns list of [PASS]/[WARN]/[FAIL] lines."""
    results = []

    # --- LLM config (supports both multi-backend and legacy flat format) ---
    llm = config.get("llm", {})
    
    if "primary" in llm:
        # Multi-backend format
        active = llm.get("active", "primary")
        backend = llm.get(active, llm.get("primary", {}))
        url = backend.get("url", "")
        model = backend.get("model", "")
    else:
        # Legacy flat format
        url = llm.get("url", "")
        model = llm.get("model", "")

    if not url or url == "http://your-internal-api/v1/chat/completions":
        results.append("[WARN] LLM URL not configured. Edit config.yaml → llm.primary.url")
    else:
        results.append(f"[PASS] LLM endpoint: {url} ({active if 'primary' in llm else 'default'})")

    if model:
        results.append(f"[PASS] Model: {model}")
    else:
        results.append("[FAIL] Model not set in config.yaml → llm.primary.model")

    # --- Skills paths ---
    skill_paths = config.get("skills", {}).get("paths", [])
    found_any = False
    for sp in skill_paths:
        p = _expand_path(sp, base_dir)
        if p.exists():
            results.append(f"[PASS] Skills path found: {p}")
            found_any = True
        else:
            results.append(f"[WARN] Skills path not found: {p}")
    if not found_any:
        results.append("[WARN] No skills directories found. Put SKILL.md files in ./skills/")

    # --- Python version ---
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 8):
        results.append(f"[PASS] Python {py_ver}")
    else:
        results.append(f"[FAIL] Python {py_ver} — need 3.8+")

    # --- Playwright check ---
    browser_cfg = config.get("tools", {}).get("browser", {})
    if browser_cfg.get("enabled", False):
        browsers_dir = base_dir / "browsers"
        pw_env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
        if pw_env:
            pw_path = Path(pw_env)
        else:
            pw_path = browsers_dir
        if pw_path.exists() and any(pw_path.iterdir()):
            results.append(f"[PASS] Playwright browsers: {pw_path}")
        else:
            results.append(
                f"[WARN] Playwright enabled but no browsers found at {pw_path}. "
                "Copy pre-downloaded browsers or see MANUAL.md"
            )

    # --- Output directory ---
    output_dir = base_dir / "output"
    if output_dir.exists():
        results.append(f"[PASS] Output directory: {output_dir}")
    else:
        results.append(f"[WARN] Output directory missing: {output_dir}")

    return results
