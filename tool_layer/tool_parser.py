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


def has_tool_calls(text: str) -> bool:
    """Quick check if text contains any tool_call blocks."""
    return "<tool_call>" in text


def extract_text_without_tools(text: str) -> str:
    """Return the text with all tool_call blocks removed."""
    return TOOL_CALL_RE.sub("", text).strip()
