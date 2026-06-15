"""
pipeline/refiner.py — Stage 4: LLM-based 3-layer dialogue refiner.

Layer 1 — Per-group multi-round (max 3 concurrent, 5 rounds each)
Layer 2 — Cross-group synthesis (1 LLM call)
Layer 3 — Final report (1 LLM call)

The refiner does NOT own the LLM client; it receives a chat_fn
and delegates all LLM interaction to it.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from .relations import FileGroup
from .parser import ParsedFile

# LLM chat function signature: async or sync callable returning str
ChatFn = Callable[[list[dict]], str]

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class GroupResult:
    group_id: str
    conclusion: str
    rounds: int = 0
    error: str = ""


@dataclass
class RefineReport:
    groups: list[GroupResult] = field(default_factory=list)
    cross_links: str = ""
    final_report: str = ""
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_LAYER1_SYSTEM = """你是一个数据分析助手。你正在分析一组文件的**结构化摘要**（不是全文）。

请根据摘要内容回答用户的问题。你可以：
1. 直接给出分析结论
2. 如果信息不够，提出1-2个追问，让用户补充

每次回复控制在300字以内。只基于给出的摘要回答问题，不要编造信息。"""

_LAYER1_USER_TEMPLATE = """## 用户问题
{question}

## 文件摘要（共{count}个文件）

{summaries}

请根据以上摘要回答用户的问题。"""

_LAYER2_SYSTEM = """你是一个系统分析专家。你已完成了多个文件分组的独立分析。

现在需要：
1. 识别各组之间的跨组关联（表名/类名/字段名/String 引用等）
2. 确认端到端链路的完整性
3. 标注信息缺口或矛盾之处

输出结构：
- 跨组关联: [...]
- 链路完整性: [...]
- 信息缺口: [...]"""

_LAYER3_SYSTEM = """你是一个技术报告撰写专家。请将以下所有分析整合成一份完整报告。

格式要求：
- 使用 Markdown 格式
- 先给总览（1-2段），再分章节展开
- 标注信息来源（文件路径）
- 如有不确定的部分，明确标注"[待确认]"
- 语言简洁专业"""


# ---------------------------------------------------------------------------
# Refiner
# ---------------------------------------------------------------------------


class Refiner:
    """3-layer dialogue refiner for batch analysis."""

    def __init__(
        self,
        chat_fn: ChatFn,
        max_rounds_per_group: int = 5,
        max_concurrent: int = 3,
    ):
        self.chat_fn = chat_fn
        self.max_rounds_per_group = max_rounds_per_group
        self.max_concurrent = max_concurrent

    # ------------------------------------------------------------------
    # Layer 1 — Per-group multi-round
    # ------------------------------------------------------------------

    def refine_groups(
        self,
        groups: list[FileGroup],
        parsed_files: list[ParsedFile],
        question: str,
        on_progress: Callable[[str], None] | None = None,
    ) -> list[GroupResult]:
        """Run multi-round refinement on each group (sequentially)."""
        results: list[GroupResult] = []

        # Build path→summary lookup
        summary_map: dict[str, str] = {
            pf.path: pf.summary for pf in parsed_files
        }

        for group in groups:
            if on_progress:
                on_progress(f"正在分析 {group.id} ({group.description})...")

            result = self._refine_one_group(group, summary_map, question)
            results.append(result)

            if on_progress:
                status = "完成" if not result.error else f"失败: {result.error}"
                on_progress(f"  {group.id} {status} ({result.rounds}轮)")

        return results

    def _refine_one_group(
        self,
        group: FileGroup,
        summary_map: dict[str, str],
        question: str,
    ) -> GroupResult:
        # Build summaries for this group
        summaries: list[str] = []
        for path in group.files:
            s = summary_map.get(path, f"[摘要不可用: {path}]")
            summaries.append(s)

        user_content = _LAYER1_USER_TEMPLATE.format(
            question=question,
            count=len(summaries),
            summaries="\n\n---\n".join(summaries),
        )

        messages: list[dict] = [
            {"role": "system", "content": _LAYER1_SYSTEM},
            {"role": "user", "content": user_content},
        ]

        conclusion = ""
        rounds = 0

        for rnd in range(self.max_rounds_per_group):
            rounds = rnd + 1
            try:
                resp = self.chat_fn(messages)
                messages.append({"role": "assistant", "content": resp})

                # Check if the assistant asked a question (contains "?")
                if "?" in resp:
                    # Simulate a follow-up by asking for more detail
                    messages.append({
                        "role": "user",
                        "content": "请根据已有摘要尽可能详细地回答。如果确实信息不足，请说明具体缺少什么。",
                    })
                else:
                    conclusion = resp
                    break
            except Exception as e:
                return GroupResult(
                    group_id=group.id,
                    conclusion=conclusion or f"[Layer1 错误: {e}]",
                    rounds=rounds,
                    error=str(e),
                )

        if not conclusion:
            conclusion = messages[-1].get("content", "[未产生结论]") if messages else "[未产生结论]"

        return GroupResult(group_id=group.id, conclusion=conclusion, rounds=rounds)

    # ------------------------------------------------------------------
    # Layer 2 — Cross-group synthesis
    # ------------------------------------------------------------------

    def synthesize_cross_group(
        self, results: list[GroupResult]
    ) -> str:
        """One LLM call to find cross-group connections."""
        if len(results) <= 1:
            return "仅有一个分组，无需跨组关联。"

        content = "## 各分组分析结论\n\n"
        for r in results:
            content += f"### {r.group_id}\n{r.conclusion}\n\n"

        messages = [
            {"role": "system", "content": _LAYER2_SYSTEM},
            {"role": "user", "content": content},
        ]

        try:
            return self.chat_fn(messages)
        except Exception as e:
            return f"[Layer2 错误: {e}]"

    # ------------------------------------------------------------------
    # Layer 3 — Final report
    # ------------------------------------------------------------------

    def final_report(
        self,
        results: list[GroupResult],
        cross_links: str,
        question: str,
    ) -> str:
        """Final comprehensive report."""
        content = f"""## 原始问题
{question}

## 各分组分析

"""
        for r in results:
            content += f"### {r.group_id}\n{r.conclusion}\n\n"

        content += f"## 跨组关联分析\n{cross_links}\n"

        content += "请整合以上所有信息，生成最终报告。"

        messages = [
            {"role": "system", "content": _LAYER3_SYSTEM},
            {"role": "user", "content": content},
        ]

        try:
            return self.chat_fn(messages)
        except Exception as e:
            return f"[Layer3 错误: {e}]\n\n原始内容:\n{content}"

    # ------------------------------------------------------------------
    # Full pipeline runner
    # ------------------------------------------------------------------

    def run(
        self,
        groups: list[FileGroup],
        parsed_files: list[ParsedFile],
        question: str,
        on_progress: Callable[[str], None] | None = None,
    ) -> RefineReport:
        report = RefineReport()

        # Layer 1
        if on_progress:
            on_progress(f"Layer 1: 分析 {len(groups)} 个分组...")
        report.groups = self.refine_groups(groups, parsed_files, question, on_progress)

        # Layer 2
        if on_progress:
            on_progress("Layer 2: 跨组关联分析...")
        report.cross_links = self.synthesize_cross_group(report.groups)

        # Layer 3
        if on_progress:
            on_progress("Layer 3: 生成最终报告...")
        report.final_report = self.final_report(report.groups, report.cross_links, question)

        return report
