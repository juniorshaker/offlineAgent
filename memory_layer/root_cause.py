"""
memory_layer/root_cause.py
Analyze error clusters to identify root causes and recommend solutions.
Uses LLM to perform deep root cause analysis from accumulated error samples.
"""

import json


ROOT_CAUSE_PROMPT = """你是一个 Agent 系统诊断专家。以下对话中，同一个错误反复出现了 {count} 次。

**错误信息**：{error_msg}
**模型**：{model}

这几次错误的上下文片段：
---
{sample1}
---
{sample2}
---
{sample3}
---

请分析：
1. 根因是什么？（为什么反复出现？）
2. 解决方案类型（选一个）：
   - strip_content: 应该在发送前预剥离某种内容
   - prompt_fix: 应该在 system prompt 中增加规则/指引
   - tool_fix: 应该修改工具调用方式或新增工具
   - skill_needed: 需要一个新 skill 来覆盖这个场景
   - ignore: 这是一个偶发/外部问题，不需要自动化处理
3. 如果需要一个新 skill，这个 skill 应该叫什么名字？包含什么内容？（用 SKILL.md 格式描述，包含 name、description、触发条件、具体指令）
4. 置信度：high / medium / low

请以 JSON 格式输出，不要包含其他文字：
{{
  "root_cause": "...",
  "solution_type": "strip_content|prompt_fix|tool_fix|skill_needed|ignore",
  "skill_name": "skill-slug-here",
  "skill_content": "---\\nname: ...\\n---\\n\\n# ...",
  "confidence": "high|medium|low"
}}"""


def build_root_cause_prompt(cluster: dict) -> str:
    """Build the root cause analysis prompt from a cluster.

    Args:
        cluster: Cluster dict from error_clusterer (must have count >= 3 and samples).

    Returns:
        Formatted prompt string ready for LLM.
    """
    samples = cluster.get("samples", [])
    sample_strs = []
    for s in samples[-3:]:
        ts = s.get("timestamp", "?")
        snippet = s.get("messages_snippet", "(no snippet)")
        sample_strs.append(f"[{ts}]\n{snippet}")

    # Pad to 3 samples if fewer
    while len(sample_strs) < 3:
        sample_strs.append("(no additional sample)")

    return ROOT_CAUSE_PROMPT.format(
        count=cluster["count"],
        error_msg=cluster.get("error_type", "unknown"),
        model=cluster.get("model", "unknown"),
        sample1=sample_strs[0],
        sample2=sample_strs[1],
        sample3=sample_strs[2],
    )


def parse_root_cause_response(response: str) -> dict | None:
    """Parse the LLM's JSON response for root cause analysis.

    Returns:
        Dict with root_cause, solution_type, skill_name, skill_content, confidence.
        None if parsing fails.
    """
    if not response:
        return None

    # Try to extract JSON from response (may contain extra text)
    json_start = response.find("{")
    json_end = response.rfind("}")
    if json_start == -1 or json_end == -1:
        return None

    json_str = response[json_start:json_end + 1]

    try:
        result = json.loads(json_str)
    except json.JSONDecodeError:
        return None

    # Validate required fields
    required = ["root_cause", "solution_type", "confidence"]
    for field in required:
        if field not in result:
            return None

    # Normalize solution_type
    valid_types = ["strip_content", "prompt_fix", "tool_fix", "skill_needed", "ignore"]
    result["solution_type"] = result["solution_type"].lower().strip()
    if result["solution_type"] not in valid_types:
        # Try to find partial match
        for vt in valid_types:
            if vt in result["solution_type"]:
                result["solution_type"] = vt
                break
        else:
            result["solution_type"] = "ignore"

    return result


def analyze_root_cause(cluster: dict, llm_chat_fn) -> dict | None:
    """Perform root cause analysis on an error cluster.

    Args:
        cluster: Cluster dict with count >= 3 and samples.
        llm_chat_fn: Function to call the LLM.

    Returns:
        Parsed result dict or None if analysis fails.
    """
    prompt = build_root_cause_prompt(cluster)

    try:
        messages = [{"role": "user", "content": prompt}]
        response = llm_chat_fn(messages)
    except Exception:
        return None

    if not response:
        return None

    return parse_root_cause_response(response)
