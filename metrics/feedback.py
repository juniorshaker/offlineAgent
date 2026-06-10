"""
metrics/feedback.py
Collects user rating on exit and persists to feedback.jsonl.
"""

import json
from datetime import datetime
from pathlib import Path


FEEDBACK_FILE = "feedback.jsonl"


def collect_feedback(base_dir: Path) -> dict | None:
    """Prompt user for 1-5 rating. Returns None if skipped."""
    try:
        raw = input("\n[反馈] 请给本次对话质量评分 (1-5，直接回车跳过): ").strip()
        if not raw:
            return None
        rating = int(raw)
        if rating < 1 or rating > 5:
            print("  评分需在 1-5 之间，已跳过。")
            return None
    except (ValueError, EOFError):
        return None

    comment = input("[反馈] 有什么想说的？（可选，回车跳过）: ").strip()

    return {"rating": rating, "comment": comment if comment else None}


def save_feedback(base_dir: Path, feedback: dict):
    """Append feedback to feedback.jsonl."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "rating": feedback["rating"],
        "comment": feedback.get("comment"),
    }
    path = base_dir / FEEDBACK_FILE
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_recent_feedback(base_dir: Path, count: int = 5) -> list[dict]:
    """Load the most recent N feedback entries for injection into context."""
    path = base_dir / FEEDBACK_FILE
    if not path.exists():
        return []
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries[-count:]
