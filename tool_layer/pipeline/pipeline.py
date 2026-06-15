"""
pipeline/pipeline.py — Orchestrator + batch_analyze tool entry.

Wires Indexer → Parser → RelationBuilder → Refiner with checkpoint
support so long-running batch jobs can be resumed.
"""

import time
from pathlib import Path
from typing import Any, Callable

from .checkpoint import Checkpoint
from .indexer import Indexer, FileManifest
from .parser import Parser, ParsedFile
from .relations import RelationBuilder, FileGroup
from .refiner import Refiner, RefineReport, ChatFn


# ---------------------------------------------------------------------------
# Pipeline orchestrator
# ---------------------------------------------------------------------------


class Pipeline:
    """Four-stage batch analysis pipeline with checkpoint resume."""

    def __init__(
        self,
        chat_fn: ChatFn,
        max_summary_chars: int = 800,
        batch_size: int = 8,
        max_rounds_per_group: int = 5,
        enable_checkpoint: bool = True,
        on_progress: Callable[[str], None] | None = None,
    ):
        self.chat_fn = chat_fn
        self.indexer = Indexer()
        self.parser = Parser(max_chars=max_summary_chars)
        self.relation_builder = RelationBuilder(batch_size=batch_size)
        self.refiner = Refiner(chat_fn, max_rounds_per_group=max_rounds_per_group)
        self.enable_checkpoint = enable_checkpoint
        self.on_progress = on_progress or (lambda msg: None)

    def run(self, target_path: str, question: str) -> str:
        """Main entry: run the full pipeline and return the final report."""
        target = Path(target_path).resolve()
        cp = Checkpoint(target) if self.enable_checkpoint else None

        # ── Stage 1: Index ──────────────────────────────────────────
        if cp and cp.is_stage_done("index"):
            self.on_progress("Stage 1/4 (索引): 已缓存，跳过")
            manifest = FileManifest(target=str(target))
        else:
            self.on_progress(f"Stage 1/4 (索引): 扫描 {target} ...")
            t0 = time.time()
            manifest = self.indexer.scan(target)
            elapsed = time.time() - t0
            self.on_progress(
                f"  -> {manifest.total_files} 文件, {manifest.total_size_mb:.1f} MB, "
                f"类型: {dict(manifest.by_type)}, 耗时 {elapsed:.1f}s"
            )
            if cp:
                cp.mark_stage_done(
                    "index",
                    total_files=manifest.total_files,
                    total_size_mb=manifest.total_size_mb,
                    by_type=manifest.by_type,
                )

        if manifest.total_files == 0:
            if target.is_file():
                # Single file mode — still parse it
                pass
            else:
                return f"目标路径 {target} 下没有找到可分析的文件。"

        # ── Stage 2: Parse ───────────────────────────────────────────
        parsed_files: list[ParsedFile] = []
        if cp and cp.is_stage_done("parse"):
            self.on_progress("Stage 2/4 (解析): 已缓存，跳过")
            # Re-parse anyway for in-memory data (fast on cached)
            # Actually, we need the ParsedFile objects — re-parse but skip error logging
            pass

        self.on_progress(f"Stage 2/4 (解析): {manifest.total_files} 个文件...")
        t0 = time.time()
        failed = 0

        for entry in manifest.files:
            try:
                pf = self.parser.parse(entry.path, entry.type)
                parsed_files.append(pf)
                if pf.error:
                    failed += 1
                    if cp:
                        cp.record_error(entry.path, pf.error)
            except Exception as e:
                failed += 1
                if cp:
                    cp.record_error(entry.path, str(e))

        elapsed = time.time() - t0
        self.on_progress(
            f"  -> {len(parsed_files)} 成功解析, {failed} 失败, 耗时 {elapsed:.1f}s"
        )
        if cp:
            cp.mark_stage_done("parse", files_parsed=len(parsed_files), files_failed=failed)

        if not parsed_files:
            return "所有文件解析失败，无法继续分析。"

        # ── Stage 3: Relations ───────────────────────────────────────
        if cp and cp.is_stage_done("relations") and not cp.is_stage_done("refine"):
            self.on_progress("Stage 3/4 (关联): 已缓存，加载分组...")
            groups_data = cp.get_groups()
            if groups_data:
                groups = [
                    FileGroup(
                        id=g["id"], files=g["files"],
                        description=g.get("description", ""),
                    )
                    for g in groups_data
                ]
            else:
                self.on_progress("Stage 3/4 (关联): 构建依赖图...")
                groups = self.relation_builder.build(parsed_files, target)
                if cp:
                    cp.set_groups([
                        {"id": g.id, "files": g.files, "description": g.description}
                        for g in groups
                    ])
        else:
            self.on_progress("Stage 3/4 (关联): 构建依赖图...")
            t0 = time.time()
            groups = self.relation_builder.build(parsed_files, target)
            elapsed = time.time() - t0
            self.on_progress(f"  -> {len(groups)} 个分组, 耗时 {elapsed:.1f}s")
            if cp:
                cp.set_groups([
                    {"id": g.id, "files": g.files, "description": g.description}
                    for g in groups
                ])
                cp.mark_stage_done("relations", groups=len(groups))

        if not groups:
            return "无法构建文件关联关系。"

        # ── Stage 4: Refine ──────────────────────────────────────────
        self.on_progress(f"Stage 4/4 (精炼): {len(groups)} 个分组...")

        # Check for already-done groups (resume)
        done_ids: set[str] = cp.done_group_ids() if cp else set()

        # Run refiner
        pending_groups = [g for g in groups if g.id not in done_ids]
        if pending_groups:
            report = self.refiner.run(
                pending_groups, parsed_files, question,
                on_progress=self.on_progress,
            )
            # Mark done groups
            if cp:
                for gr in report.groups:
                    cp.mark_group_done(gr.group_id, gr.conclusion)
        else:
            # All groups done — just do cross-group + final
            self.on_progress("所有分组已完成，直接合成...")
            # Rebuild results from checkpoint
            prev_results = self._rebuild_results_from_checkpoint(cp, groups)
            report = RefineReport(groups=prev_results)
            report.cross_links = self.refiner.synthesize_cross_group(prev_results)
            report.final_report = self.refiner.final_report(
                prev_results, report.cross_links, question,
            )

        if cp:
            cp.mark_stage_done(
                "refine", groups_done=len(done_ids) + len(pending_groups),
            )

        return report.final_report

    def _rebuild_results_from_checkpoint(
        self, cp: Checkpoint, groups: list[FileGroup]
    ) -> list:
        """Rebuild GroupResult list from checkpoint data."""
        from .refiner import GroupResult
        results = []
        for g in groups:
            for cg in cp.get_groups():
                if cg.get("id") == g.id and cg.get("done"):
                    results.append(GroupResult(
                        group_id=g.id,
                        conclusion=cg.get("conclusion", ""),
                        rounds=cg.get("rounds", 0),
                    ))
                    break
            else:
                results.append(GroupResult(
                    group_id=g.id,
                    conclusion="[未完成]",
                ))
        return results


# ---------------------------------------------------------------------------
# batch_analyze tool entry
# ---------------------------------------------------------------------------


def batch_analyze(
    target_path: str,
    question: str,
    scope: str = "",
    _chat_fn: Any = None,
    _config: dict | None = None,
    _on_progress: Any = None,
) -> str:
    """Unified tool for batch file analysis.

    LLM calls this ONCE; the pipeline handles the rest internally.

    Args:
        target_path: absolute path to file or directory
        question:   what the user wants to know
        scope:      optional filter: "sql_only", "java_only", "all" (default)
    """
    if _chat_fn is None:
        return "[Error] batch_analyze requires a chat function (internal wiring)"

    cfg = _config or {}
    pipeline_cfg = cfg.get("pipeline", {})

    pipeline = Pipeline(
        chat_fn=_chat_fn,
        max_summary_chars=pipeline_cfg.get("max_summary_chars", 800),
        batch_size=pipeline_cfg.get("batch_size", 8),
        max_rounds_per_group=pipeline_cfg.get("max_rounds_per_group", 5),
        enable_checkpoint=pipeline_cfg.get("enable_checkpoint", True),
        on_progress=_on_progress,
    )

    return pipeline.run(target_path, question)
