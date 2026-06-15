"""
tool_layer/tool_parser.py
Parse XML-format tool calls from LLM output.

Format:
  <tool_call>
  <name>tool_name</name>
  <param1>value1</param1>
  <param2>value2</param2>
  </tool_call>
"""

import re

# Match complete tool_call blocks (non-greedy, across lines)
TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*"
    r"(.*?)"
    r"</tool_call>",
    re.DOTALL,
)

# Fallback: alternate tool-call wrapper tags that LLMs sometimes output
FUZZY_WRAPPER_RE = re.compile(
    r"<(?:tool_call|function_call|tool|invoke)>\s*"
    r"(.*?)"
    r"</(?:tool_call|function_call|tool|invoke)>",
    re.DOTALL,
)

# Common parameter-name aliases LLMs use instead of the canonical names
PARAM_ALIASES: dict[str, str] = {
    # file/path aliases
    "file": "path",
    "filepath": "path",
    "file_path": "path",
    "filename": "path",
    "dir": "path",
    "directory": "path",
    "folder": "path",
    # search aliases
    "query": "pattern",
    "keyword": "pattern",
    "search": "pattern",
    # shell aliases
    "cmd": "command",
    "exec": "command",
    # content aliases
    "text": "content",
    "data": "content",
    # template aliases
    "template": "template_path",
    "tmpl": "template_path",
    "values": "fields",
    # selector aliases
    "css": "selector",
    "element": "selector",
}

# Match individual elements within a tool_call
ELEMENT_RE = re.compile(r"<(\w+)>(.*?)</\1>", re.DOTALL)


class ParsedToolCall:
    """A parsed tool call from LLM output."""

    def __init__(self, name: str, params: dict[str, str]):
        self.name = name
        self.params = params

    def __repr__(self):
        return f"ToolCall({self.name}, {self.params})"


def parse_tool_calls(text: str) -> list[ParsedToolCall]:
    """Extract all <tool_call> blocks from LLM output text."""
    results = []

    for match in TOOL_CALL_RE.finditer(text):
        block = match.group(1)
        elements = ELEMENT_RE.findall(block)

        name = None
        params = {}

        for tag, value in elements:
            value = value.strip()
            if tag == "name":
                name = value
            else:
                params[tag] = value

        if name:
            results.append(ParsedToolCall(name, params))

    return results


def _strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences that LLMs often wrap around tool calls."""
    fence_re = re.compile(r'```(?:xml|html)?\s*\n?(.*?)\n?```', re.DOTALL)
    m = fence_re.search(text)
    if m:
        return m.group(1).strip()
    return text


def _fuzzy_parse_tool_calls(text: str) -> list[ParsedToolCall]:
    """Fallback parser for malformed / non-standard tool call formats.

    Handles:
    1. Markdown code fences wrapping the XML
    2. Alternate wrapper tags: function_call, tool, invoke
    3. Standalone tool name as wrapper: <read_file><path>x</path></read_file>
    4. Parameter name aliases: file→path, query→pattern, etc.
    """
    # 0. Repair common LLM XML typos before any parsing
    #    e.g. <name=read_file</name> -> <name>read_file</name> (= instead of >)
    text = re.sub(r'<(\w+)\s*=\s*([^<]*)</\1>', r'<\1>\2</\1>', text)

    # 1. Strip markdown fences first
    cleaned = _strip_markdown_fences(text)
    if cleaned != text:
        strict = parse_tool_calls(cleaned)
        if strict:
            return strict

    # 2. Try fuzzy wrapper tags (function_call, tool, invoke)
    results = []
    for match in FUZZY_WRAPPER_RE.finditer(cleaned):
        block = match.group(1)
        elements = ELEMENT_RE.findall(block)

        name = None
        params = {}
        for tag, value in elements:
            value = value.strip()
            if tag == "name":
                name = value
            else:
                canonical = PARAM_ALIASES.get(tag, tag)
                params[canonical] = value
        if name:
            results.append(ParsedToolCall(name, params))
    if results:
        return results

    # 3. Ultra-fuzzy: standalone tool name as wrapper
    #    e.g. <read_file><path>foo</path></read_file> (no outer wrapper)
    known_tools = (
        "read_file|write_file|list_dir|search_code|find_files|"
        "shell|read_template|write_output|web_fetch|"
        "browser_navigate|browser_screenshot|browser_click|"
        "browser_type|browser_get_content|browser_get_html|"
        "browser_exec|browser_status|"
        "write_docx|write_xlsx|write_pptx|"
        "db_connect|db_list_tables|db_query|db_exec"
    )
    standalone_re = re.compile(
        r"<(" + known_tools + r")"
        r"(?:>(.*?)</\1|\s+/>)",
        re.DOTALL,
    )
    for match in standalone_re.finditer(cleaned):
        tool_name = match.group(1)
        body = match.group(2) or ""
        elements = ELEMENT_RE.findall(body)
        params = {}
        for tag, value in elements:
            canonical = PARAM_ALIASES.get(tag.strip(), tag.strip())
            params[canonical] = value.strip()
        results.append(ParsedToolCall(tool_name, params))

    return results


def has_tool_calls(text: str) -> bool:
    """Quick check if text contains any tool_call blocks."""
    if "<tool_call>" in text or "<function_call>" in text:
        return True
    # Standalone tool name checks (LLMs sometimes skip outer wrapper)
    _all_tools = [
        "read_file", "write_file", "list_dir", "search_code", "find_files",
        "shell", "read_template", "write_output", "web_fetch",
        "browser_navigate", "browser_screenshot", "browser_click",
        "browser_type", "browser_get_content", "browser_get_html",
        "browser_exec", "browser_status",
        "write_docx", "write_xlsx", "write_pptx",
        "db_connect", "db_list_tables", "db_query", "db_exec",
    ]
    for t in _all_tools:
        if f"<{t}>" in text or f"<{t} " in text:
            return True
    return False


def extract_text_without_tools(text: str) -> str:
    """Return the text with all tool_call blocks removed."""
    return TOOL_CALL_RE.sub("", text).strip()


def parse_tool_calls_full(text: str) -> list[ParsedToolCall]:
    """Parse tool calls: strict first, fuzzy fallback.

    Use this as the primary entry point for parsing LLM output.
    """
    results = parse_tool_calls(text)
    if results:
        for tc in results:
            tc.params = {PARAM_ALIASES.get(k, k): v for k, v in tc.params.items()}
        return results
    return _fuzzy_parse_tool_calls(text)
