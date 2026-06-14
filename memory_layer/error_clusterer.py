"""
memory_layer/error_clusterer.py
Cluster errors by model+error_type+keywords.
When a cluster reaches threshold (default 3), trigger Autoskill.
"""

import json
from datetime import datetime
from pathlib import Path

CLUSTERS_FILE = "error_clusters.json"

# Known error type classifiers
_ERROR_TYPE_KEYWORDS = {
    "image": ["image", "multimodal", "picture", "photo", "screenshot", "image_url"],
    "video": ["video"],
    "audio": ["audio"],
    "json_parse": ["expecting value", "json", "malformed", "parse error", "char 0"],
    "timeout": ["timeout", "timed out", "did not respond"],
    "connection": ["connection", "refused", "unreachable", "network"],
    "auth": ["401", "403", "unauthorized", "authentication", "api key"],
    "rate_limit": ["429", "rate limit", "too many requests"],
    "content_filter": ["content filter", "safety", "blocked"],
    "unknown_tool": ["unknown tool", "tool not found", "not available"],
}


def _classify_error(error_msg: str) -> str:
    """Classify an error message into a type."""
    lower = error_msg.lower()
    for etype, keywords in _ERROR_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in lower:
                return etype
    return "unknown"


def _extract_keywords(error_msg: str) -> str:
    """Extract stable keywords for clustering."""
    lower = error_msg.lower()
    found = []
    for etype, keywords in _ERROR_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in lower:
                found.append(kw)
                break  # one per type
    if not found:
        # Use first 3 significant words
        words = [w for w in lower.split() if len(w) > 2 and w not in ("the", "and", "for", "was")]
        found = words[:3] or ["unknown"]
    return "_".join(sorted(set(found)))


def _load_clusters(base_dir: Path) -> dict:
    """Load error clusters from disk."""
    path = base_dir / "memory" / CLUSTERS_FILE
    if not path.exists():
        return {"clusters": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"clusters": []}


def _save_clusters(base_dir: Path, data: dict):
    """Save error clusters to disk."""
    path = base_dir / "memory" / CLUSTERS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def record_error(
    model: str,
    error_msg: str,
    messages_snippet: str,
    base_dir: Path,
    threshold: int = 3,
) -> dict | None:
    """Record an error in the cluster database.

    Args:
        model: Model name that produced the error.
        error_msg: The error message or response text.
        messages_snippet: First ~300 chars of the messages that were sent.
        base_dir: Project base directory.
        threshold: How many occurrences before triggering Autoskill.

    Returns:
        The cluster dict if threshold reached and status is 'pending', else None.
    """
    error_type = _classify_error(error_msg)
    keywords = _extract_keywords(error_msg)
    cluster_id = f"{model}__{error_type}__{keywords}"

    clusters_data = _load_clusters(base_dir)
    clusters = clusters_data.get("clusters", [])

    # Find or create cluster
    cluster = None
    for c in clusters:
        if c.get("cluster_id") == cluster_id:
            cluster = c
            break

    now = datetime.now().isoformat()

    if cluster is None:
        cluster = {
            "cluster_id": cluster_id,
            "model": model,
            "error_type": error_type,
            "keywords": keywords.replace("_", " "),
            "count": 0,
            "first_seen": now,
            "last_seen": now,
            "samples": [],
            "status": "pending",
            "generated_skill": "",
        }
        clusters.append(cluster)

    cluster["count"] += 1
    cluster["last_seen"] = now
    cluster["samples"].append({
        "timestamp": now,
        "messages_snippet": messages_snippet[:300],
    })
    # Keep only last 3 samples
    if len(cluster["samples"]) > 3:
        cluster["samples"] = cluster["samples"][-3:]

    clusters_data["clusters"] = clusters
    _save_clusters(base_dir, clusters_data)

    if cluster["count"] >= threshold and cluster["status"] == "pending":
        return cluster

    return None


def mark_cluster_generated(base_dir: Path, cluster_id: str, skill_path: str):
    """Mark a cluster as having generated an auto-skill."""
    clusters_data = _load_clusters(base_dir)
    for c in clusters_data.get("clusters", []):
        if c.get("cluster_id") == cluster_id:
            c["status"] = "auto_skill_generated"
            c["generated_skill"] = skill_path
            break
    _save_clusters(base_dir, clusters_data)


def get_all_clusters(base_dir: Path) -> list[dict]:
    """Return all clusters, newest first."""
    data = _load_clusters(base_dir)
    return list(reversed(data.get("clusters", [])))


def get_pending_clusters(base_dir: Path) -> list[dict]:
    """Return clusters that are still pending (below threshold)."""
    data = _load_clusters(base_dir)
    return [c for c in data.get("clusters", []) if c.get("status") == "pending"]
