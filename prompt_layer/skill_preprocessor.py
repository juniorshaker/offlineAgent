"""
prompt_layer/skill_preprocessor.py
Apply template variable substitution to skill content.
Supports ${SKILL_DIR} placeholder expansion.
"""

import re
from pathlib import Path

_SKILL_TEMPLATE_RE = re.compile(r"\$\{SKILL_DIR\}")


def preprocess_skill_content(content: str, skill_dir: Path, config: dict) -> str:
    """Apply configured preprocessing transformations.

    Currently supports:
    - template_vars: replace ${SKILL_DIR} with the skill's directory path
    - inline_shell (future): execute !`cmd` snippets (disabled by default)
    """
    if not content:
        return content

    preprocessing = config.get("skills", {}).get("preprocessing", {})

    if preprocessing.get("template_vars", True):
        content = _SKILL_TEMPLATE_RE.sub(str(skill_dir), content)

    # inline_shell is disabled by default for security in offline environments
    # Keeping the hook here for future implementation

    return content
