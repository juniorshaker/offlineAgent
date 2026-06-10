"""
memory_layer/skill_drafter.py
Propose and generate SKILL.md drafts from conversation topics.
"""

from pathlib import Path

DRAFT_PROMPT = """Based on the following conversation, create a SKILL.md file for OfflineAgent.

Use this format:
---
name: skill-name-here
description: A one-line description of what this skill does and when to use it
---

# Skill Title

## When to Use
- Scenario 1
- Scenario 2

## Instructions
1. Step one
2. Step two

## Related
- Related concept or tool

Conversation topic:
{topic}

Generate the SKILL.md content:"""


def detect_skill_worthy_topic(history: list[dict]) -> str | None:
    """Check if the conversation involved a focused, reusable topic.

    Returns a topic description if skill-worthy, None otherwise.
    """
    # Simple heuristic: check if conversation is long enough
    user_msgs = [m for m in history if m.get("role") == "user"]
    if len(user_msgs) < 3:
        return None

    # Check for topic consistency keywords
    all_content = " ".join(
        m.get("content", "")[:200]
        for m in history
        if m.get("role") in ("user", "assistant")
        and isinstance(m.get("content"), str)
    ).lower()

    topic_keywords = [
        ("java", "Java Development"),
        ("spring", "Spring Boot Development"),
        ("python", "Python Development"),
        ("docker", "Docker Operations"),
        ("git", "Git Workflow"),
        ("test", "Testing Practices"),
        ("code review", "Code Review"),
        ("deploy", "Deployment"),
        ("sql", "SQL & Database"),
        ("api", "API Design"),
    ]

    for keyword, topic in topic_keywords:
        if keyword in all_content:
            return topic

    return None


def generate_skill_draft(topic: str, llm_chat_fn) -> str | None:
    """Generate SKILL.md content for a topic.

    Args:
        topic: Topic description.
        llm_chat_fn: Function to call LLM.

    Returns:
        SKILL.md content or None if generation fails.
    """
    prompt = DRAFT_PROMPT.format(topic=topic)

    try:
        messages = [{"role": "user", "content": prompt}]
        result = llm_chat_fn(messages)
        if result and "---" in result:
            return result.strip()
    except Exception:
        pass

    return None


def save_skill_draft(skills_dir: Path, skill_name: str, content: str) -> Path | None:
    """Save a generated SKILL.md to the skills directory.

    Args:
        skills_dir: Path to skills/ directory.
        skill_name: Name for the skill (slug form).
        content: SKILL.md content.

    Returns:
        Path to saved file, or None on failure.
    """
    skill_dir = skills_dir / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_path = skill_dir / "SKILL.md"

    try:
        skill_path.write_text(content, encoding="utf-8")
        return skill_path
    except Exception:
        return None
