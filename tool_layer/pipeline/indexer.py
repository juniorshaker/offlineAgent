"""
pipeline/indexer.py — Stage 1: recursive directory scan, zero LLM.

Produces a FileManifest categorised by type so Stage 2 can dispatch
the right parser per file.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

# -- File type groups (mirrors file_handler.py) ---------------------------------

TEXT_EXTENSIONS = {
    ".txt", ".sql", ".md", ".py", ".js", ".ts", ".jsx", ".tsx",
    ".json", ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".csv", ".log", ".html", ".css", ".scss", ".less",
    ".java", ".kt", ".swift", ".rs", ".go", ".c", ".cpp", ".h", ".hpp",
    ".sh", ".bat", ".ps1", ".rb", ".php", ".lua", ".r", ".m",
    ".env", ".gitignore", ".dockerfile", ".makefile",
}

OFFICE_EXTENSIONS = {".docx", ".xlsx", ".pptx"}
PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".ico", ".svg"}

SKIP_DIRS = {".git", "node_modules", "__pycache__", "vendor", ".idea", ".vscode", "target", "build", "dist"}


def _classify(ext: str) -> str:
    """Map a lowercase file extension to a human-readable type label."""
    ext = ext.lower()
    if ext in TEXT_EXTENSIONS:
        return ext.lstrip(".")   # "sql", "java", "py"  ...
    if ext in OFFICE_EXTENSIONS:
        return ext.lstrip(".")
    if ext in PDF_EXTENSIONS:
        return "pdf"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    return "other"


@dataclass
class FileEntry:
    path: str          # absolute
    name: str
    type: str          # e.g. "sql", "java", "xlsx", "pdf"
    size: int          # bytes
    dir_name: str      # immediate parent directory name


@dataclass
class FileManifest:
    target: str
    total_files: int = 0
    total_size_mb: float = 0.0
    max_depth: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    files: list[FileEntry] = field(default_factory=list)


class Indexer:
    """Recursively scan a directory and build a FileManifest."""

    def __init__(self, skip_dirs: set[str] | None = None, skip_hidden: bool = True):
        self.skip_dirs = skip_dirs or SKIP_DIRS
        self.skip_hidden = skip_hidden

    def scan(self, target: str | Path) -> FileManifest:
        target = Path(target).resolve()

        if not target.exists():
            return FileManifest(target=str(target))

        if target.is_file():
            # Single-file mode — just index the one file
            return self._scan_single(target)

        manifest = FileManifest(target=str(target))
        self._walk(target, manifest, depth=0)
        return manifest

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _scan_single(self, target: Path) -> FileManifest:
        ext = target.suffix.lower()
        entry = FileEntry(
            path=str(target),
            name=target.name,
            type=_classify(ext),
            size=target.stat().st_size,
            dir_name=target.parent.name,
        )
        m = FileManifest(target=str(target), total_files=1)
        m.files.append(entry)
        m.by_type[entry.type] = 1
        m.total_size_mb = entry.size / (1024 * 1024)
        return m

    def _walk(self, directory: Path, manifest: FileManifest, depth: int):
        manifest.max_depth = max(manifest.max_depth, depth)

        try:
            entries = sorted(directory.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except (PermissionError, OSError):
            return

        for entry in entries:
            name = entry.name

            # Skip hidden
            if self.skip_hidden and name.startswith("."):
                continue

            if entry.is_dir():
                if name in self.skip_dirs:
                    continue
                self._walk(entry, manifest, depth + 1)
            else:
                ext = entry.suffix.lower()
                ftype = _classify(ext)
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = 0

                fe = FileEntry(
                    path=str(entry),
                    name=name,
                    type=ftype,
                    size=size,
                    dir_name=directory.name,
                )
                manifest.files.append(fe)
                manifest.total_files += 1
                manifest.total_size_mb += size / (1024 * 1024)
                manifest.by_type[ftype] = manifest.by_type.get(ftype, 0) + 1
