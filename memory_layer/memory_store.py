"""
memory_layer/memory_store.py
Read/write session memories using JSON index + Markdown files.
"""

import json
from datetime import datetime
from pathlib import Path


class MemoryStore:
    """Manages persistent session memories."""

    def __init__(self, memory_dir: Path):
        self.memory_dir = memory_dir
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.memory_dir / "index.json"
        self._index: list[dict] = []
        self._load_index()

    def _load_index(self):
        if self.index_path.exists():
            try:
                self._index = json.loads(self.index_path.read_text(encoding="utf-8"))
            except Exception:
                self._index = []

    def _save_index(self):
        self.index_path.write_text(json.dumps(self._index, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, summary: str, tags: list[str] | None = None) -> str:
        """Add a new memory. Returns the memory ID."""
        mem_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{mem_id}.md"

        entry = {
            "id": mem_id,
            "file": filename,
            "timestamp": datetime.now().isoformat(),
            "summary": summary[:100],
            "tags": tags or [],
        }
        self._index.append(entry)
        self._save_index()

        # Write full memory as Markdown
        mem_path = self.memory_dir / filename
        content = f"# Memory {mem_id}\n\n{summary}\n"
        mem_path.write_text(content, encoding="utf-8")

        return mem_id

    def get_recent(self, count: int = 3) -> list[str]:
        """Get the most recent N memory summaries."""
        recent = self._index[-count:]
        return [entry["summary"] for entry in recent]

    def get(self, mem_id: str) -> str | None:
        """Get a specific memory by ID."""
        for entry in self._index:
            if entry["id"] == mem_id:
                mem_path = self.memory_dir / entry["file"]
                if mem_path.exists():
                    return mem_path.read_text(encoding="utf-8")
                return f"[Memory file not found: {entry['file']}]"
        return None

    def list_all(self) -> list[dict]:
        """Return all memory index entries (newest first)."""
        return list(reversed(self._index))

    def count(self) -> int:
        return len(self._index)
