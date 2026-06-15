"""
pipeline/checkpoint.py — on-disk checkpoint for resumable batch processing.

Stores pipeline progress at the target directory root as
`.offlineagent_checkpoint.json`.  Users can delete this file to
force a full re-run.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CHECKPOINT_FILENAME = ".offlineagent_checkpoint.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Checkpoint:
    """Read / write pipeline checkpoints."""

    def __init__(self, target_dir: Path):
        self.target_dir = Path(target_dir)
        self._path = self.target_dir / CHECKPOINT_FILENAME

    # ------------------------------------------------------------------
    # public helpers
    # ------------------------------------------------------------------

    def exists(self) -> bool:
        return self._path.exists()

    def delete(self):
        self._path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # stage helpers
    # ------------------------------------------------------------------

    def is_stage_done(self, stage: str) -> bool:
        data = self.load()
        return data.get("stages", {}).get(stage, {}).get("done", False)

    def mark_stage_done(self, stage: str, **extra):
        data = self.load()
        data.setdefault("stages", {})
        data["stages"][stage] = {"done": True, "timestamp": _now_iso(), **extra}
        self.save(data)

    # ------------------------------------------------------------------
    # group helpers
    # ------------------------------------------------------------------

    def get_groups(self) -> list[dict]:
        return self.load().get("groups", [])

    def set_groups(self, groups: list[dict]):
        data = self.load()
        data["groups"] = groups
        self.save(data)

    def mark_group_done(self, group_id: str, conclusion: str):
        data = self.load()
        for g in data.get("groups", []):
            if g.get("id") == group_id:
                g["done"] = True
                g["conclusion"] = conclusion
        self.save(data)

    def done_group_ids(self) -> set[str]:
        return {g["id"] for g in self.get_groups() if g.get("done")}

    # ------------------------------------------------------------------
    # error helpers
    # ------------------------------------------------------------------

    def record_error(self, file_path: str, error: str):
        data = self.load()
        data.setdefault("errors", [])
        data["errors"].append({"file": file_path, "error": error, "ts": _now_iso()})
        self.save(data)

    # ------------------------------------------------------------------
    # raw I/O
    # ------------------------------------------------------------------

    def load(self) -> dict[str, Any]:
        if not self._path.exists():
            return self._empty()
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return self._empty()

    def save(self, data: dict[str, Any]):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {
            "target": "",
            "stage": "index",
            "stages": {},
            "groups": [],
            "errors": [],
        }
