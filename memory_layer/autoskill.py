"""
memory_layer/autoskill.py
Autoskill orchestration engine.

Ties together error_clusterer, root_cause, skill_drafter, and memory_store
into an automated pipeline that:
1. Records errors into clusters
2. When a cluster reaches threshold (>=3), triggers root cause analysis
3. Generates SKILL.md drafts for skill_needed solutions
4. Saves to skills/_autogen/ and records in memory
5. On startup, informs user of auto-generated skills
"""

import json
from pathlib import Path
from datetime import datetime

from .error_clusterer import (
    record_error,
    mark_cluster_generated,
    get_pending_clusters,
)
from .root_cause import analyze_root_cause
from .skill_drafter import save_skill_draft


def on_error(
    model: str,
    error_msg: str,
    messages_snippet: str,
    base_dir: Path,
    llm_chat_fn,
    memory_store=None,
    logger=None,
    threshold: int = 3,
) -> bool:
    """Called on every error. Records error and triggers Autoskill if threshold reached.

    Args:
        model: Model name.
        error_msg: Error message text.
        messages_snippet: First ~300 chars of messages sent.
        base_dir: Project base directory.
        llm_chat_fn: LLM call function.
        memory_store: Optional MemoryStore instance.
        logger: Optional logger.
        threshold: Cluster size threshold (default 3).

    Returns:
        True if a new auto-skill was generated during this call.
    """
    # Step 1: Record error, get cluster if threshold reached
    cluster = record_error(model, error_msg, messages_snippet, base_dir, threshold)
    if cluster is None:
        return False

    if logger:
        logger.log("autoskill", "trigger",
                   f"cluster={cluster['cluster_id']} count={cluster['count']}")

    # Step 2: Root cause analysis
    if logger:
        logger.log("autoskill", "root_cause_start", cluster["cluster_id"])

    analysis = analyze_root_cause(cluster, llm_chat_fn)

    if not analysis:
        if logger:
            logger.log("autoskill", "root_cause_failed", "LLM analysis returned None")
        return False

    if logger:
        logger.log("autoskill", "root_cause_done",
                   f"type={analysis['solution_type']} conf={analysis['confidence']}")

    # Step 3: Handle based on solution type
    if analysis["solution_type"] == "ignore":
        mark_cluster_generated(base_dir, cluster["cluster_id"], "ignored")
        if logger:
            logger.log("autoskill", "ignored", analysis.get("root_cause", "")[:100])
        return False

    if analysis["solution_type"] == "strip_content":
        # Record the finding in model_capabilities.json
        _record_capability(base_dir, model, analysis)
        mark_cluster_generated(base_dir, cluster["cluster_id"], "model_capabilities.json")
        if logger:
            logger.log("autoskill", "capability_recorded",
                       f"model={model} cause={analysis['root_cause'][:100]}")
        return True

    if analysis["solution_type"] == "prompt_fix":
        # Save as a prompt fix note in _autogen
        skill_name = analysis.get("skill_name", f"prompt-fix-{cluster['cluster_id']}")
        content = f"# Auto-generated Prompt Fix\n\n"
        content += f"**Root Cause**: {analysis['root_cause']}\n\n"
        content += f"**Confidence**: {analysis['confidence']}\n\n"
        content += f"**Suggested Fix**: {analysis.get('skill_content', 'Review the error pattern and adjust system prompt.')}\n"
        saved = _save_autoskill(base_dir, skill_name, content)
        mark_cluster_generated(base_dir, cluster["cluster_id"], str(saved or "prompt_fix"))
        if logger:
            logger.log("autoskill", "prompt_fix_saved", str(saved))
        return saved is not None

    if analysis["solution_type"] == "tool_fix":
        skill_name = analysis.get("skill_name", f"tool-fix-{cluster['cluster_id']}")
        content = f"# Auto-generated Tool Fix\n\n"
        content += f"**Root Cause**: {analysis['root_cause']}\n\n"
        content += f"**Confidence**: {analysis['confidence']}\n\n"
        content += f"**Suggested Fix**: {analysis.get('skill_content', 'Review tool implementation.')}\n"
        saved = _save_autoskill(base_dir, skill_name, content)
        mark_cluster_generated(base_dir, cluster["cluster_id"], str(saved or "tool_fix"))
        if logger:
            logger.log("autoskill", "tool_fix_saved", str(saved))
        return saved is not None

    if analysis["solution_type"] == "skill_needed":
        skill_name = analysis.get("skill_name", f"autogen-{cluster['cluster_id']}")
        skill_content = analysis.get("skill_content", "")

        if not skill_content:
            # Fallback: generate basic content
            skill_content = f"---\nname: {skill_name}\n"
            skill_content += f"description: Auto-generated skill: {analysis['root_cause'][:80]}\n"
            skill_content += "---\n\n"
            skill_content += f"# {skill_name}\n\n"
            skill_content += f"**Root Cause**: {analysis['root_cause']}\n\n"
            skill_content += f"**Confidence**: {analysis['confidence']}\n"

        saved = _save_autoskill(base_dir, skill_name, skill_content)
        mark_cluster_generated(base_dir, cluster["cluster_id"], str(saved or skill_name))

        # Record in memory
        if memory_store:
            memory_store.add(
                f"Autoskill generated: {skill_name} — {analysis['root_cause'][:80]}",
                tags=["autoskill", cluster["error_type"]],
            )

        if logger:
            logger.log("autoskill", "skill_saved", str(saved))
        return saved is not None

    return False


def check_generated_skills(base_dir: Path, logger=None) -> list[dict]:
    """Scan skills/_autogen/ for auto-generated skills.

    Called at startup to inform user of new auto-skills.

    Returns:
        List of dicts with {name, path, snippet} for each generated skill.
    """
    autogen_dir = base_dir / "skills" / "_autogen"
    if not autogen_dir.exists():
        return []

    skills = []
    for skill_dir in sorted(autogen_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue

        try:
            content = skill_file.read_text(encoding="utf-8")[:500]
        except Exception:
            content = "(unreadable)"

        skills.append({
            "name": skill_dir.name,
            "path": str(skill_file),
            "snippet": content[:120],
        })

    if skills and logger:
        logger.log("autoskill", "startup_scan", f"{len(skills)} generated skills found")

    return skills


def _save_autoskill(base_dir: Path, name: str, content: str) -> Path | None:
    """Save an auto-generated skill to skills/_autogen/."""
    autogen_dir = base_dir / "skills" / "_autogen"
    autogen_dir.mkdir(parents=True, exist_ok=True)

    skill_dir = autogen_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)

    try:
        skill_path = skill_dir / "SKILL.md"
        skill_path.write_text(content, encoding="utf-8")
        return skill_path
    except Exception:
        return None


def _record_capability(base_dir: Path, model: str, analysis: dict):
    """Record a model capability deficiency based on root cause analysis."""
    caps_file = base_dir / "memory" / "model_capabilities.json"
    caps = {}
    if caps_file.exists():
        try:
            caps = json.loads(caps_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    if model not in caps:
        caps[model] = {}

    entry = caps[model]
    unsupported = entry.get("unsupported", [])

    # Infer unsupported type from root cause
    root_cause = analysis.get("root_cause", "").lower()
    for content_type in ["image", "video", "audio"]:
        if content_type in root_cause and content_type not in unsupported:
            unsupported.append(content_type)

    entry["unsupported"] = unsupported
    entry["autoskill_source"] = True
    entry["autoskill_time"] = datetime.now().isoformat()

    caps[model] = entry
    caps_file.parent.mkdir(parents=True, exist_ok=True)
    caps_file.write_text(json.dumps(caps, ensure_ascii=False, indent=2), encoding="utf-8")
