"""
tool_layer/document_tools.py
Template reading and output writing.
"""

from pathlib import Path


def read_template(path: str, base_dir: Path) -> str:
    """Read a template file from the templates/ directory."""
    p = Path(path)
    if not p.is_absolute():
        p = base_dir / "templates" / p

    if not p.exists():
        return f"[Error] Template not found: {p}"

    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        return content
    except Exception as e:
        return f"[Error] Cannot read template {p}: {e}"


def write_output(path: str, content: str, base_dir: Path) -> str:
    """Write generated content to the output/ directory."""
    p = Path(path)
    if not p.is_absolute():
        p = base_dir / "output" / p

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"[OK] Output written to {p} ({len(content)} chars)"
    except Exception as e:
        return f"[Error] Cannot write output {p}: {e}"
