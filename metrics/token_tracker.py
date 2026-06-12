"""
metrics/token_tracker.py
Token usage tracking with JSONL storage, monthly files, 1-year retention.
Thread-safe append writes. Provides query with aggregation.
"""

import json
import os
import time
import threading
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict


class TokenTracker:
    """Tracks LLM token usage across backends and models.

    Storage: memory/token_stats/YYYY-MM.jsonl
    Each line: {"ts": "ISO8601", "backend": "primary", "model": "Qwen3",
                 "prompt_tokens": 500, "completion_tokens": 200, "total_tokens": 700}
    """

    def __init__(self, base_dir: Path):
        self._base_dir = Path(base_dir) / "token_stats"
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()

    def record(self, backend: str, model: str,
               prompt_tokens: int, completion_tokens: int, total_tokens: int):
        """Append a token usage record to the current month's JSONL file."""
        if not backend or not model:
            return

        now = datetime.now()
        record = {
            "ts": now.isoformat(),
            "backend": backend,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }

        month_key = now.strftime("%Y-%m")
        file_path = self._base_dir / f"{month_key}.jsonl"

        with self._write_lock:
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        # Garbage collect old files (>1 year)
        self._cleanup_old()

    def _cleanup_old(self):
        """Remove token stat files older than 1 year."""
        cutoff = datetime.now() - timedelta(days=365)
        with self._write_lock:
            for fpath in self._base_dir.glob("*.jsonl"):
                try:
                    month_str = fpath.stem  # YYYY-MM
                    file_month = datetime.strptime(month_str, "%Y-%m")
                    if file_month < cutoff.replace(day=1):
                        fpath.unlink()
                except (ValueError, OSError):
                    pass

    def get_backends(self) -> list[str]:
        """Return list of backend names that have records."""
        backends = set()
        for fpath in sorted(self._base_dir.glob("*.jsonl")):
            for backend in self._scan_backends_in_file(fpath):
                backends.add(backend)
        return sorted(backends)

    def get_models(self, backend: str = None) -> list[str]:
        """Return model names, optionally filtered by backend."""
        models = set()
        for fpath in sorted(self._base_dir.glob("*.jsonl")):
            for rec in self._iter_records(fpath):
                if backend and rec.get("backend") != backend:
                    continue
                models.add(rec.get("model", ""))
        return sorted(m for m in models if m)

    def _scan_backends_in_file(self, filepath: Path) -> set:
        backends = set()
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        if rec.get("backend"):
                            backends.add(rec["backend"])
                    except json.JSONDecodeError:
                        pass
        except (IOError, OSError):
            pass
        return backends

    def _iter_records(self, filepath: Path):
        """Yield records from a JSONL file."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        pass
        except (IOError, OSError):
            pass

    def query(self, backend: str = None, model: str = None,
              range: str = "week") -> list[dict]:
        """Query aggregated token usage.

        Args:
            backend: Filter by backend name (None = all).
            model: Filter by model name (None = all).
            range: Aggregation period: "hour", "day", "week", "month".

        Returns:
            List of {period, prompt_tokens, completion_tokens, total_tokens, count}.
        """
        now = datetime.now()

        # Determine time range
        if range == "hour":
            cutoff = now - timedelta(hours=24)
            fmt = "%Y-%m-%dT%H"
            delta = timedelta(hours=1)
        elif range == "month":
            cutoff = now - timedelta(days=365)
            fmt = "%Y-%m"
            delta = timedelta(days=32)  # approx
        elif range == "day":
            cutoff = now - timedelta(days=30)
            fmt = "%Y-%m-%d"
            delta = timedelta(days=1)
        else:  # week (default)
            cutoff = now - timedelta(days=7)
            fmt = "%Y-%m-%d"
            delta = timedelta(days=1)

        # Aggregate
        buckets: dict[str, dict] = defaultdict(
            lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "count": 0}
        )

        for fpath in sorted(self._base_dir.glob("*.jsonl")):
            for rec in self._iter_records(fpath):
                # Parse timestamp
                try:
                    rec_ts = datetime.fromisoformat(rec.get("ts", ""))
                except (ValueError, TypeError):
                    continue

                if rec_ts < cutoff:
                    continue

                # Filter by backend/model
                if backend and rec.get("backend") != backend:
                    continue
                if model and rec.get("model") != model:
                    continue

                key = rec_ts.strftime(fmt)
                buckets[key]["prompt_tokens"] += rec.get("prompt_tokens", 0)
                buckets[key]["completion_tokens"] += rec.get("completion_tokens", 0)
                buckets[key]["total_tokens"] += rec.get("total_tokens", 0)
                buckets[key]["count"] += 1

        # Sort by period and return
        result = []
        for period in sorted(buckets.keys()):
            entry = {"period": period}
            entry.update(buckets[period])
            result.append(entry)

        return result

    def total_summary(self, backend: str = None, model: str = None,
                      range: str = "week") -> dict:
        """Return total summary: {total_prompt, total_completion, total_tokens, total_calls}."""
        data = self.query(backend=backend, model=model, range=range)
        summary = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "total_calls": 0,
        }
        for entry in data:
            summary["prompt_tokens"] += entry.get("prompt_tokens", 0)
            summary["completion_tokens"] += entry.get("completion_tokens", 0)
            summary["total_tokens"] += entry.get("total_tokens", 0)
            summary["total_calls"] += entry.get("count", 0)
        return summary
