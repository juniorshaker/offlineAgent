"""
prompt_layer/skill_loader.py
Discover, parse, and filter SKILL.md files from configured directories.

Supports:
- Multi-source discovery (local, Codex, OpenClaw paths)
- YAML frontmatter parsing with fallback
- Platform filtering (platforms: [macos, linux, windows])
- Directory exclusion (.git, node_modules, etc.)
- L1 index (name + 60-char description) and L2 body (full markdown)
"""

import os
import re
import sys
from pathlib import Path
from typing import Any

# Directories to skip during skill discovery
EXCLUDED_SKILL_DIRS = frozenset({
    ".git", ".github", ".hub", ".archive",
    ".venv", "venv", "node_modules", "site-packages",
    "__pycache__", ".tox", ".nox", ".pytest_cache",
    ".mypy_cache", ".ruff_cache",
})

PLATFORM_MAP = {
    "macos": "darwin",
    "linux": "linux",
    "windows": "win32",
}


class Skill:
    """Represents one loaded skill."""

    def __init__(self, name: str, description: str, body: str, path: Path, source: str):
        self.name = name
        self.description = description
        self.body = body
        self.path = path
        self.source = source  # 'local', 'codex', 'openclaw'
        self.use_count = 0

    @property
    def short_desc(self) -> str:
        """Truncated description for the index (max 60 chars)."""
        d = self.description.strip().strip("'\"")
        if len(d) > 60:
            return d[:57] + "..."
        return d


def _is_excluded_path(path: Path) -> bool:
    """Check if any path component is in the exclusion set."""
    return any(part in EXCLUDED_SKILL_DIRS for part in path.parts)


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from markdown content.

    Returns (frontmatter_dict, body_without_frontmatter).
    Falls back to simple key:value parsing if the YAML is malformed.
    """
    fm: dict[str, Any] = {}
    body = content

    if not content.startswith("---"):
        return fm, body

    end_match = re.search(r"\n---\s*\n", content[3:])
    if not end_match:
        return fm, body

    yaml_content = content[3:end_match.start() + 3]
    body = content[end_match.end() + 3:]

    # Simple line-by-line parser (no PyYAML dependency)
    for line in yaml_content.strip().split("\n"):
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            fm[key] = value

    return fm, body


def _skill_matches_platform(frontmatter: dict[str, Any]) -> bool:
    """Check if the skill is compatible with the current OS.

    Skills declare platforms via a top-level `platforms` field:
        platforms: [macos]          # macOS only
        platforms: [macos, linux]   # macOS and Linux
    If absent, the skill is compatible with all platforms.
    """
    # Handle YAML list notation on a single line: [macos, linux]
    raw = frontmatter.get("platforms", "")
    if not raw:
        return True

    # Parse list: strip brackets, split by comma
    raw_str = str(raw).strip()
    if raw_str.startswith("[") and raw_str.endswith("]"):
        platforms = [p.strip().strip("'\"") for p in raw_str[1:-1].split(",")]
    else:
        platforms = [raw_str]

    current = sys.platform
    for platform in platforms:
        normalized = str(platform).lower().strip()
        mapped = PLATFORM_MAP.get(normalized, normalized)
        if current.startswith(mapped):
            return True
    return False


def _discover_skills_in_dir(skills_dir: Path) -> list[Path]:
    """Walk a skills directory and return all SKILL.md paths."""
    matches = []
    if not skills_dir.exists():
        return matches
    for root, dirs, files in os.walk(skills_dir, followlinks=True):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_SKILL_DIRS]
        if "SKILL.md" in files:
            matches.append(Path(root) / "SKILL.md")
    return sorted(matches, key=lambda p: str(p.relative_to(skills_dir)))


def load_all_skills(config: dict, base_dir: Path) -> list[Skill]:
    """Discover and load skills from all configured paths.

    Returns a list of Skill objects (L1 index ready).
    """
    skills: list[Skill] = []
    seen_names: set[str] = set()

    skill_paths = config.get("skills", {}).get("paths", [])

    source_labels = {
        "./skills": "local",
    }

    for raw_path in skill_paths:
        expanded = os.path.expanduser(raw_path)
        p = Path(expanded)
        if not p.is_absolute():
            p = (base_dir / p).resolve()

        if not p.exists():
            continue

        # Determine source label
        source = source_labels.get(raw_path, "")
        if not source:
            if "codex" in str(p).lower():
                source = "codex"
            elif "openclaw" in str(p).lower() or "clawdbot" in str(p).lower():
                source = "openclaw"
            else:
                source = "local"

        for skill_file in _discover_skills_in_dir(p):
            if _is_excluded_path(skill_file):
                continue

            try:
                content = skill_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            frontmatter, body = _parse_frontmatter(content)
            name = frontmatter.get("name", skill_file.parent.name)

            # Deduplicate by name
            if name in seen_names:
                continue

            # Platform filter
            if not _skill_matches_platform(frontmatter):
                continue

            description = frontmatter.get("description", "")

            skill = Skill(
                name=name,
                description=description,
                body=body.strip(),
                path=skill_file,
                source=source,
            )
            skills.append(skill)
            seen_names.add(name)

    return skills


def get_skill_body(skill: Skill) -> str:
    """Return the full body content for L2 loading."""
    # Re-read in case file changed
    try:
        content = skill.path.read_text(encoding="utf-8", errors="replace")
        _, body = _parse_frontmatter(content)
        return body.strip()
    except Exception:
        return skill.body
