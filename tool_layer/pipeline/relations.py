"""
pipeline/relations.py — Stage 3: cross-file dependency graph + smart grouping.

Zero LLM.  Uses name-, path-, and config-based heuristics to link
files of any type, then groups by connected components for Stage 4.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from .parser import ParsedFile


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class FileLink:
    source: str        # source file path
    target: str        # target file path
    reason: str        # e.g. "table_ref", "import", "config_ref"
    detail: str = ""   # extra context


@dataclass
class FileGroup:
    id: str
    files: list[str] = field(default_factory=list)         # file paths
    links: list[FileLink] = field(default_factory=list)
    description: str = ""


# ---------------------------------------------------------------------------
# Relation builder
# ---------------------------------------------------------------------------


class RelationBuilder:
    """Build dependency graph and group files by connected components."""

    def __init__(self, batch_size: int = 8):
        self.batch_size = batch_size

    def build(
        self, parsed_files: list[ParsedFile], target_dir: Path
    ) -> list[FileGroup]:
        """Main entry: parsed files → linked groups."""
        if not parsed_files:
            return []

        links = self._build_links(parsed_files, target_dir)
        groups = self._group_by_components(parsed_files, links)

        # Annotate with descriptions
        for g in groups:
            g.description = self._describe_group(g, parsed_files)

        return groups

    # ------------------------------------------------------------------
    # Link building
    # ------------------------------------------------------------------

    def _build_links(
        self, parsed_files: list[ParsedFile], target_dir: Path
    ) -> list[FileLink]:
        links: list[FileLink] = []

        # Collect all named entities from all file types
        table_writers: dict[str, list[str]] = {}   # table_name → [file_path]
        table_readers: dict[str, list[str]] = {}    # table_name → [file_path]
        class_names: dict[str, str] = {}             # class_name → file_path
        java_packages: dict[str, str] = {}            # package → file_path
        proc_names: dict[str, str] = {}               # procedure_name → file_path
        excel_sheets: dict[str, str] = {}             # sheet_name → file_path
        config_keys: dict[str, str] = {}              # key → file_path

        for pf in parsed_files:
            meta = pf.meta
            path = pf.path

            if pf.file_type == "sql":
                for t in meta.get("tables_written", []):
                    table_writers.setdefault(t.lower(), []).append(path)
                for t in meta.get("tables_read", []):
                    table_readers.setdefault(t.lower(), []).append(path)
                for p in meta.get("procedures", []):
                    proc_names[p.lower()] = path

            elif pf.file_type == "java":
                cls = meta.get("class", "")
                pkg = meta.get("package", "")
                if cls:
                    class_names[cls.lower()] = path
                if pkg:
                    java_packages[pkg.lower()] = path

            elif pf.file_type == "xlsx":
                # Use filename as "table" name for matching
                sheet_key = Path(path).stem.lower()
                excel_sheets[sheet_key] = path

            elif pf.file_type in ("config", "yaml", "yml", "json", "xml"):
                # Extract config key-like names
                for k in meta.get("top_keys", []):
                    config_keys[k.lower()] = path

            elif pf.file_type == "csv":
                sheet_key = Path(path).stem.lower()
                excel_sheets[sheet_key] = path

        # --- Cross-format linking ---

        # SQL table → SQL table (writer→reader chains)
        for tbl, writers in table_writers.items():
            for src in writers:
                for dst in table_readers.get(tbl, []):
                    if src != dst:
                        links.append(FileLink(src, dst, "table_flow", f"table={tbl}"))

        # SQL table → Excel/CSV sheet
        for tbl in set(list(table_writers) + list(table_readers)):
            tbl_normalized = tbl.replace("_", "").replace("-", "")
            for sheet_key, sheet_path in excel_sheets.items():
                sheet_normalized = sheet_key.replace("_", "").replace("-", "")
                if tbl_normalized == sheet_normalized or tbl in sheet_key or sheet_key in tbl:
                    writers = table_writers.get(tbl, []) + table_readers.get(tbl, [])
                    for src in writers:
                        if src != sheet_path:
                            links.append(FileLink(src, sheet_path, "table_to_sheet", f"table={tbl}, sheet={sheet_key}"))

        # Java → Java (same package)
        pkg_files: dict[str, list[str]] = {}
        for pf in parsed_files:
            if pf.file_type == "java":
                pkg = pf.meta.get("package", "")
                pkg_files.setdefault(pkg, []).append(pf.path)
        for pkg, files in pkg_files.items():
            if len(files) > 1:
                for i in range(len(files)):
                    for j in range(i + 1, len(files)):
                        links.append(FileLink(files[i], files[j], "same_package", f"pkg={pkg}"))

        # Java → SQL (same-named procedure / service → SQL)
        for cls, cls_path in class_names.items():
            for proc, proc_path in proc_names.items():
                if cls in proc or proc in cls:
                    links.append(FileLink(cls_path, proc_path, "class_to_proc", f"class={cls}, proc={proc}"))

        # Config → SQL (datasource / db references)
        for key, cfg_path in config_keys.items():
            for tbl in set(list(table_writers) + list(table_readers)):
                if tbl in key or key in tbl:
                    for sql_path in table_writers.get(tbl, []) + table_readers.get(tbl, []):
                        links.append(FileLink(cfg_path, sql_path, "config_to_table", f"key={key}, table={tbl}"))

        return links

    # ------------------------------------------------------------------
    # Connected components grouping
    # ------------------------------------------------------------------

    def _group_by_components(
        self, parsed_files: list[ParsedFile], links: list[FileLink]
    ) -> list[FileGroup]:
        # Build adjacency
        adj: dict[str, set[str]] = {pf.path: set() for pf in parsed_files}
        for link in links:
            adj.setdefault(link.source, set()).add(link.target)
            adj.setdefault(link.target, set()).add(link.source)

        # DFS to find connected components
        visited: set[str] = set()
        components: list[list[str]] = []

        for node in adj:
            if node not in visited:
                comp: list[str] = []
                stack = [node]
                while stack:
                    v = stack.pop()
                    if v not in visited:
                        visited.add(v)
                        comp.append(v)
                        stack.extend(adj.get(v, set()) - visited)
                components.append(comp)

        # Isolated files (no links) get their own component
        for pf in parsed_files:
            if pf.path not in visited:
                components.append([pf.path])
                visited.add(pf.path)

        # Split large components by batch_size
        groups: list[FileGroup] = []
        for ci, comp in enumerate(components):
            if len(comp) <= self.batch_size:
                groups.append(self._make_group(f"group_{ci+1}", comp, links))
            else:
                # Split large component intelligently — by type then by dir
                sub_groups = self._split_large_component(comp, links, ci + 1)
                groups.extend(sub_groups)

        return groups

    def _split_large_component(
        self, comp: list[str], links: list[FileLink], prefix: int
    ) -> list[FileGroup]:
        """Split a large component into type-homogeneous sub-groups."""
        # Sort by file type
        by_type: dict[str, list[str]] = {}
        for p in comp:
            ext = Path(p).suffix.lower()
            by_type.setdefault(ext, []).append(p)

        groups: list[FileGroup] = []
        sub_idx = 0
        for ext, files in by_type.items():
            # Chunk each type group
            for i in range(0, len(files), self.batch_size):
                sub_idx += 1
                chunk = files[i:i + self.batch_size]
                groups.append(self._make_group(f"group_{prefix}_{chr(96 + sub_idx)}", chunk, links))

        return groups

    def _make_group(
        self, gid: str, paths: list[str], all_links: list[FileLink]
    ) -> FileGroup:
        path_set = set(paths)
        group_links = [
            l for l in all_links
            if l.source in path_set and l.target in path_set
        ]
        return FileGroup(id=gid, files=paths, links=group_links)

    # ------------------------------------------------------------------
    # Description
    # ------------------------------------------------------------------

    def _describe_group(self, group: FileGroup, parsed_files: list[ParsedFile]) -> str:
        path_set = set(group.files)
        type_counts: dict[str, int] = {}
        names: list[str] = []

        for pf in parsed_files:
            if pf.path in path_set:
                type_counts[pf.file_type] = type_counts.get(pf.file_type, 0) + 1
                names.append(pf.filename)

        type_summary = ", ".join(f"{v}x {k}" for k, v in sorted(type_counts.items()))
        return f"{type_summary} — {', '.join(names[:5])}" + (
            f" ...+{len(names)-5}" if len(names) > 5 else ""
        )
