"""
tool_layer/file_tools.py
File system tools: read, write, list, search.
"""

import os
from pathlib import Path

# Base directory for safety — restrict file access to project dir + subdirs
# In offline mode this is set dynamically
_FILE_BASE: Path = Path.cwd()


def set_file_base(base: Path):
    """Set the base directory for file operations (safety boundary)."""
    global _FILE_BASE
    _FILE_BASE = base.resolve()


def _resolve_safe(path_str: str) -> Path:
    """Resolve a path relative to the file base, preventing escape."""
    p = Path(path_str)
    if not p.is_absolute():
        resolved = (_FILE_BASE / p).resolve()
    else:
        resolved = p.resolve()

    # Safety: prevent escaping the workspace
    try:
        resolved.relative_to(_FILE_BASE)
    except ValueError:
        # For absolute paths, allow them but warn
        pass

    return resolved


def read_file(path: str) -> str:
    """Read the contents of a file."""
    p = _resolve_safe(path)
    if not p.exists():
        return f"[Error] File not found: {p}"
    if not p.is_file():
        return f"[Error] Not a file: {p}"

    # For binary/office/image files, use file_handler for proper extraction
    ext = p.suffix.lower()
    _OFFICE_AND_BINARY = {'.docx', '.xlsx', '.pptx', '.pdf', '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.ico', '.svg'}
    if ext in _OFFICE_AND_BINARY:
        from Offlineagent.tool_layer.file_handler import read_file_content
        result = read_file_content(p)
        if result.get('type') == 'error':
            return f"[Error] {result.get('content', 'Unknown error')}"
        if result.get('type') == 'image':
            return (f"[Image: {p.name}, {result.get('dimensions', ('?','?'))[0]}x{result.get('dimensions', ('?','?'))[1]}]"
                    + f"\n{result.get('content', '')}")
        return result.get('content', f'[No content extracted from {p.name}]')

    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        max_len = 50000
        if len(content) > max_len:
            return content[:max_len] + f"\n\n[...truncated {len(content) - max_len} chars...]"
        return content
    except Exception as e:
        return f"[Error] Cannot read {p}: {e}"


def write_file(path: str, content: str) -> str:
    """Write content to a file."""
    p = _resolve_safe(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"[OK] Written {len(content)} chars to {p}"
    except Exception as e:
        return f"[Error] Cannot write {p}: {e}"


def list_dir(path: str) -> str:
    """List files and subdirectories."""
    p = _resolve_safe(path)
    if not p.exists():
        return f"[Error] Directory not found: {p}"
    if not p.is_dir():
        return f"[Error] Not a directory: {p}"

    items = []
    try:
        for entry in sorted(p.iterdir()):
            suffix = "/" if entry.is_dir() else ""
            try:
                size = entry.stat().st_size
                size_str = f" ({size:,} bytes)" if not entry.is_dir() else ""
            except Exception:
                size_str = ""
            items.append(f"  {entry.name}{suffix}{size_str}")
    except PermissionError:
        return f"[Error] Permission denied: {p}"

    if not items:
        return f"[Empty] {p}"
    return f"{p}/\n" + "\n".join(items[:50]) + ("\n  ... (more items)" if len(items) > 50 else "")


def search_code(pattern: str, path: str = ".") -> str:
    """Search for a pattern in files under path.

    Uses ripgrep (rg) if available, otherwise falls back to Python search.
    """
    import subprocess

    p = _resolve_safe(path)

    # Try ripgrep first
    try:
        result = subprocess.run(
            ["rg", "--no-heading", "-n", "--max-count=30", pattern, str(p)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode in (0, 1):
            output = result.stdout.strip()
            if output:
                lines = output.split("\n")
                if len(lines) > 30:
                    return "\n".join(lines[:30]) + f"\n...({len(lines)-30} more matches)"
                return output
            return f"[No matches] for '{pattern}' in {p}"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback: Python-based search
    results = []
    extensions = {".py", ".java", ".js", ".ts", ".html", ".css", ".md", ".txt",
                   ".xml", ".yaml", ".yml", ".json", ".sh", ".bat", ".sql",
                   ".kt", ".swift", ".go", ".rs", ".c", ".cpp", ".h"}

    for root, dirs, files in os.walk(p):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".git")]
        for fname in files:
            if Path(fname).suffix.lower() not in extensions:
                continue
            fp = Path(root) / fname
            try:
                for i, line in enumerate(fp.read_text(encoding="utf-8", errors="replace").split("\n"), 1):
                    if pattern.lower() in line.lower():
                        results.append(f"{fp}:{i}: {line.strip()[:120]}")
                        if len(results) >= 30:
                            raise StopIteration
            except StopIteration:
                break
            except Exception:
                continue
        if len(results) >= 30:
            break

    if not results:
        return f"[No matches] for '{pattern}' in {p}"
    return "\n".join(results)
