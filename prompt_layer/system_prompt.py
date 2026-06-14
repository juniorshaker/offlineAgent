"""
prompt_layer/system_prompt.py
Assemble the three-tier system prompt (stable / context / volatile).

Stable:  agent identity + skills index + tools definitions
Context: user-supplied extra prompt
Volatile: memory snapshot + feedback reference + timestamp

The stable layer is cached to disk to avoid re-scanning on every startup.
"""

import json
from datetime import datetime
from pathlib import Path

from .skill_loader import Skill
from ..metrics.feedback import load_recent_feedback

CACHE_FILE = ".prompt_cache.json"

AGENT_IDENTITY = """You are OfflineAgent, a portable AI assistant running on an intranet.

## Core Rules
- Use the tools provided to help the user: read files, write documents, search code, run shell commands.
- When you need to use a tool, output it as an XML block:
  <tool_call>
  <name>tool_name</name>
  <param_name>value</param_name>
  </tool_call>
- You can call MULTIPLE tools in ONE response by placing multiple <tool_call> blocks together.
- **CRITICAL - File Creation Rule**: To create or modify any file (documents, code, spreadsheets, etc.), you MUST use the <tool_call> format with write_file, write_output, write_docx, write_xlsx, or write_pptx. Simply saying "I've created the file" in plain text does NOT actually create anything. The user will NOT receive the file unless you actually call the tool.
- Think step by step. Break complex tasks into smaller tool calls.
- **Path access rule**: When the user gives a specific file or directory path, access it directly first. Do not explore layer by layer. Only fall back to step-by-step traversal if the direct access fails.
- Be concise. Prefer actionable answers over long explanations.
- Default language: Chinese, but follow the user's language.

## Pending Issues (CRITICAL)
When a discussion reaches any of these states, you MUST save the issue:
1. User says '先不做' / '等等' / '暂时不处理' / '改天再说'
2. A solution was discussed but user hasn't ordered implementation
3. A tool/feature is missing and can't be fixed in this session
4. Before context compression, proactively save key unresolved items

To save: use write_file to create 'pending/YYYY-MM-DD_{short_desc}.md' with:
- Date, topic, and who raised it
- Current state of the discussion
- What needs to be done next
- Why it was paused

At the START of every conversation, scan the 'pending/' directory and tell the user:
'You have N pending issues: [list]. Would you like to address any?'

The user can also type /pending to review pending issues at any time.

## Code Exploration Pattern (CRITICAL)
When the user asks about code (a method, class, file, or project behavior), follow this exact workflow:
1. If the user gave a specific file path: use **read_file** directly on that path. Do NOT list_dir first.
2. If the user gave only a class/method name (no path): use **search_code** to locate it, then read_file.
3. If the user asked about a Java project: read pom.xml or build.gradle first to understand the structure.
4. When reading code, always read the FULL file or at least the complete method body. Never stop at listing.
5. NEVER end a turn with just a list_dir result. After listing, immediately follow up with read_file or search_code.
6. If you are unsure where to look, use search_code with the class/method name rather than exploring directories one by one.

## Directory Exploration Pattern (CRITICAL)
When the user asks you to find a file or explore a directory structure, follow this workflow:
1. If you know the file name or pattern: use **find_files** (e.g., find_files(pattern="*.yml")). This searches recursively.
2. If you don't know the file name: use **list_dir** to see what's inside. If there are subdirectories, you MUST continue exploring them with more list_dir calls -- do NOT stop just because you see a subdirectory or archive.
3. Archive files (.zip, .tar.gz, .jar) are NOT the answer. They are containers. Tell the user what you found inside the directory structure, not just the archive name.
4. When searching for something specific (like a config file), always prefer find_files over manual list_dir recursion -- it's faster and uses fewer tool calls.
5. NEVER report "found a folder" and stop. Either list the folder's contents or explain why you cannot proceed."""


def _build_skills_index(skills: list[Skill]) -> str:
    """Build the L1 skills index section."""
    if not skills:
        return ""

    lines = ["## Available Skills"]

    # Group by source
    by_source: dict[str, list[Skill]] = {}
    for s in skills:
        by_source.setdefault(s.source, []).append(s)

    for source in ["local", "codex", "openclaw"]:
        group = by_source.get(source, [])
        if not group:
            continue
        source_label = {"local": "Local", "codex": "Codex", "openclaw": "OpenClaw"}.get(source, source)
        lines.append(f"\n### {source_label}")
        for s in group:
            use_hint = f" [used {s.use_count}x]" if s.use_count > 0 else ""
            lines.append(f"- **{s.name}**{use_hint}: {s.short_desc}")

    lines.append("\n## Skills vs Tools (IMPORTANT)")
    lines.append("- **Skills** listed above provide guidance and workflow instructions. They are NOT tools -- do NOT invoke them via <tool_call>.")
    lines.append("- To get a skill's full instructions, output: /skill <name> as a normal text command.")
    lines.append("- **Tools** (read_file, write_file, shell, search_code, etc.) are invoked via <tool_call> XML blocks.")
    lines.append("- Skills that match the user's request are AUTO-INJECTED as `[Skill Context: name]` messages. Look for them in the conversation history -- no need to type /skill manually unless you want a different one.")
    lines.append("- When you see `[Skill Context: xxx]` in the conversation, follow that skill's instructions as your primary workflow guide.")
    lines.append("- If you receive a DIFFERENT skill than what you need, use /skill <name> to manually activate the correct one.")
    return "\n".join(lines)


def _build_tools_section(config: dict) -> str:
    """Build tool definitions for the system prompt."""
    enabled = config.get("tools", {}).get("enabled", [])
    if not enabled:
        return ""

    lines = ["\n## Available Tools", "", "Use the XML format below to call tools:"]
    lines.append("```")
    lines.append("<tool_call>")
    lines.append("<name>tool_name</name>")
    lines.append("<param>value</param>")
    lines.append("</tool_call>")
    lines.append("```")

    tool_defs = {
        "read_file": "- **read_file** (path): Read the contents of a file.",
        "write_file": "- **write_file** (path, content): Create or overwrite a file. Requires confirmation.",
        "list_dir": "- **list_dir** (path): List files and subdirectories.",
        "search_code": "- **search_code** (pattern, path): Search for a pattern in files under path.",
        "find_files": "- **find_files** (pattern, path): Recursively find files by name pattern (e.g., '*.yml', 'Dockerfile').",
        "shell": "- **shell** (command): Execute a shell command. Requires confirmation for destructive ops.",
        "read_template": "- **read_template** (path): Read a template file from templates/.",
        "write_output": "- **write_output** (path, content): Write output to the output/ directory.",
        "web_fetch": "- **web_fetch** (url, method): Make an HTTP request (GET or POST).",
        "browser_navigate": "- **browser_navigate** (url): Navigate the browser to a URL and return page title.",
        "browser_screenshot": "- **browser_screenshot** (name): Take a screenshot and save to output/.",
        "browser_click": "- **browser_click** (selector): Click a page element by CSS selector.",
        "browser_type": "- **browser_type** (selector, text): Type text into an input element.",
        "browser_get_content": "- **browser_get_content** (selector?, max_length?): Get text content of page or element.",
        "browser_get_html": "- **browser_get_html** (selector?): Get HTML of page or element.",
        "browser_exec": "- **browser_exec** (js): Execute JavaScript in the browser.",
        "browser_status": "- **browser_status**: Check if browser automation is available.",
        "write_docx": "- **write_docx** (path, fields, template_path): Fill a Word template and save.",
        "write_xlsx": "- **write_xlsx** (path, fields, template_path): Fill an Excel template and save.",
        "write_pptx": "- **write_pptx** (path, fields, template_path): Fill a PowerPoint template and save.",
    }

    for tool_name in enabled:
        if tool_name in tool_defs:
            lines.append(tool_defs[tool_name])

    shell_allowed = config.get("tools", {}).get("shell", {}).get("allowed", [])
    if shell_allowed:
        lines.append(f"\nAllowed shell commands: {', '.join(shell_allowed)}")

    return "\n".join(lines)


def _load_prompt_cache(base_dir: Path, skills: list[Skill]) -> str | None:
    """Try to load cached stable prompt. Returns None if cache is stale."""
    cache_path = base_dir / CACHE_FILE
    if not cache_path.exists():
        return None

    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    # Check if any skill file's mtime changed
    for s in skills:
        cached_mtime = cache.get("skill_mtimes", {}).get(str(s.path))
        try:
            actual_mtime = s.path.stat().st_mtime
        except OSError:
            return None  # File gone, invalidate cache
        if cached_mtime != actual_mtime:
            return None

    return cache.get("prompt")


def _save_prompt_cache(base_dir: Path, skills: list[Skill], prompt: str):
    """Save the stable prompt to disk cache."""
    cache_path = base_dir / CACHE_FILE
    mtimes = {}
    for s in skills:
        try:
            mtimes[str(s.path)] = s.path.stat().st_mtime
        except OSError:
            pass

    cache = {
        "prompt": prompt,
        "skill_mtimes": mtimes,
    }
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def build_system_prompt(
    config: dict,
    skills: list[Skill],
    base_dir: Path,
    recent_memories: list[str] | None = None,
    force_rebuild: bool = False,
) -> tuple[str, bool]:
    """Build the full system prompt.

    Returns (prompt_string, cache_hit).
    """
    # --- Stable layer ---
    stable_parts = [AGENT_IDENTITY, _build_skills_index(skills), _build_tools_section(config)]
    stable = "\n\n".join(p for p in stable_parts if p)

    # Try cache
    if not force_rebuild:
        cached = _load_prompt_cache(base_dir, skills)
        if cached and len(cached) > 100:  # Sanity check
            # Still need to add context + volatile layers
            pass

    _save_prompt_cache(base_dir, skills, stable)

    # --- Context layer ---
    extra = config.get("agent", {}).get("system_prompt_extra", "")
    context_parts = []
    if extra:
        context_parts.append(extra)
    context = "\n\n".join(context_parts) if context_parts else ""

    # --- Volatile layer ---
    volatile_parts = []

    # Recent memories
    if recent_memories:
        volatile_parts.append("## Recent Session Memories\n" + "\n".join(f"- {m}" for m in recent_memories))

    # Recent feedback
    if config.get("agent", {}).get("feedback", {}).get("enabled", True):
        feedback_entries = load_recent_feedback(base_dir, count=3)
        if feedback_entries:
            fb_lines = ["## Recent User Feedback"]
            for fb in feedback_entries:
                rating = fb.get("rating", "?")
                comment = fb.get("comment", "")
                fb_lines.append(f"- Rating {rating}/5" + (f": {comment}" if comment else ""))
            volatile_parts.append("\n".join(fb_lines))

    # Timestamp / session info
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    model = config.get("llm", {}).get("model", "unknown")
    volatile_parts.append(f"Current time: {now}\nModel: {model}")

    volatile = "\n\n".join(volatile_parts) if volatile_parts else ""

    # --- Assemble ---
    parts = [stable]
    if context:
        parts.append(context)
    if volatile:
        parts.append(volatile)

    return "\n\n---\n\n".join(parts), False
