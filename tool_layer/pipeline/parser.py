"""
pipeline/parser.py — Stage 2: per-file structured summary (<= 800 chars).

Zero LLM.  Regex + file_handler for all supported formats.
Each file produces a ParsedFile with a human-readable summary
suitable for feeding into the LLM refiner.
"""

import csv
import io
import re
import struct
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_SUMMARY_CHARS = 800

TEXT_EXTENSIONS = {
    ".txt", ".sql", ".md", ".py", ".js", ".ts", ".jsx", ".tsx",
    ".json", ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".csv", ".log", ".html", ".css", ".scss", ".less",
    ".java", ".kt", ".swift", ".rs", ".go", ".c", ".cpp", ".h", ".hpp",
    ".sh", ".bat", ".ps1", ".rb", ".php", ".lua", ".r", ".m",
    ".env", ".gitignore", ".dockerfile", ".makefile",
}

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ParsedFile:
    path: str
    filename: str
    file_type: str      # "sql", "java", "xlsx", "docx", "pdf", ...
    size_bytes: int
    summary: str        # <= MAX_SUMMARY_CHARS
    error: str = ""
    meta: dict = field(default_factory=dict)   # extra structured fields


# ---------------------------------------------------------------------------
# Parser dispatcher
# ---------------------------------------------------------------------------


class Parser:
    """Parse any supported file into a structured ParsedFile."""

    def __init__(self, max_chars: int = MAX_SUMMARY_CHARS):
        self.max_chars = max_chars

    def parse(self, file_path: str | Path, file_type: str | None = None) -> ParsedFile:
        path = Path(file_path).resolve()

        if not path.exists():
            return ParsedFile(
                path=str(path), filename=path.name,
                file_type="unknown", size_bytes=0,
                summary="", error=f"File not found: {path}",
            )

        size = path.stat().st_size
        ftype = file_type or self._detect_type(path)

        # Route to format-specific parser
        parser_map = {
            "sql":      self._parse_sql,
            "java":     self._parse_java,
            "py":       self._parse_python,
            "js":       self._parse_generic_text,
            "ts":       self._parse_generic_text,
            "xlsx":     self._parse_xlsx,
            "csv":      self._parse_csv,
            "docx":     self._parse_docx,
            "pptx":     self._parse_pptx,
            "pdf":      self._parse_pdf,
            "yaml":     self._parse_config,
            "yml":      self._parse_config,
            "json":     self._parse_config,
            "xml":      self._parse_config,
            "ini":      self._parse_config,
            "cfg":      self._parse_config,
            "conf":     self._parse_config,
            "txt":      self._parse_generic_text,
            "md":       self._parse_generic_text,
            "image":    self._parse_image,
        }

        handler = parser_map.get(ftype, self._parse_generic_text)

        try:
            return handler(path, size)
        except Exception as exc:
            return ParsedFile(
                path=str(path), filename=path.name,
                file_type=ftype, size_bytes=size,
                summary=f"[{ftype}] Parse failed: {exc}",
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # SQL
    # ------------------------------------------------------------------

    def _parse_sql(self, path: Path, size: int) -> ParsedFile:
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.split("\n")

        procs: list[str] = []
        functions: list[str] = []
        tables_written: set[str] = set()
        tables_read: set[str] = set()
        temp_tables: set[str] = set()

        text_upper = text.upper()

        # CREATE PROCEDURE / FUNCTION
        for m in re.finditer(
            r"CREATE\s+(OR\s+REPLACE\s+)?(PROCEDURE|FUNCTION)\s+(\w+)", text_upper
        ):
            kind = m.group(2).lower()
            name = m.group(3)
            if kind == "procedure":
                procs.append(name)
            else:
                functions.append(name)

        # Target tables: INSERT INTO / UPDATE / DELETE FROM / MERGE INTO
        for m in re.finditer(
            r"(INSERT\s+(INTO\s+)?|UPDATE\s+|DELETE\s+FROM\s+|MERGE\s+INTO\s+)(\w+(\.\w+)?)",
            text_upper,
        ):
            tbl = m.group(3).split(".")[-1]
            tables_written.add(tbl)

        # Source tables: FROM / JOIN
        for m in re.finditer(r"(FROM|JOIN)\s+(\w+(\.\w+)?)", text_upper):
            tbl = m.group(2).split(".")[-1]
            if tbl not in ("DUAL", "LATERAL",):
                tables_read.add(tbl)

        # Temporary tables
        for m in re.finditer(r"(CREATE|DECLARE)\s+(GLOBAL\s+)?(TEMPORARY|TEMP)\s+TABLE\s+(\w+)", text_upper):
            temp_tables.add(m.group(4))

        # Build summary
        parts: list[str] = []
        if procs:
            parts.append(f"Procedure(s): {', '.join(procs[:10])}" + (f" ...+{len(procs)-10}" if len(procs) > 10 else ""))
        if functions:
            parts.append(f"Function(s): {', '.join(functions[:10])}")
        if tables_read:
            parts.append(f"Reads: {', '.join(sorted(tables_read)[:15])}")
        if tables_written:
            parts.append(f"Writes: {', '.join(sorted(tables_written)[:15])}")
        if temp_tables:
            parts.append(f"Temp tables: {', '.join(sorted(temp_tables))}")
        if not parts:
            parts.append(f"{len(lines)} lines, no procedures/functions detected")

        summary = " | ".join(parts)
        summary += f"\n[Source: {self._rel(path)} | sql | {size:,} bytes]"

        return ParsedFile(
            path=str(path), filename=path.name, file_type="sql",
            size_bytes=size, summary=self._trim(summary),
            meta={
                "procedures": procs, "functions": functions,
                "tables_read": sorted(tables_read),
                "tables_written": sorted(tables_written),
                "temp_tables": sorted(temp_tables),
            },
        )

    # ------------------------------------------------------------------
    # Java
    # ------------------------------------------------------------------

    def _parse_java(self, path: Path, size: int) -> ParsedFile:
        text = path.read_text(encoding="utf-8", errors="replace")

        # Package
        pkg = ""
        m = re.search(r"package\s+([\w.]+)\s*;", text)
        if m:
            pkg = m.group(1)

        # Class / interface / enum name
        class_name = ""
        m = re.search(
            r"(public\s+)?(class|interface|enum)\s+(\w+)", text
        )
        if m:
            class_name = m.group(3)

        # Annotations
        annotations = re.findall(r"@(\w+)\b", text)
        annotations = [a for a in annotations if a not in ("Override", "SuppressWarnings")]
        annotations = list(set(annotations))

        # Public method signatures
        methods: list[str] = []
        for m in re.finditer(
            r"(public|protected|private)\s+(static\s+)?\s*([\w<>[\],\s]+)\s+(\w+)\s*\(([^)]*)\)",
            text,
        ):
            ret = m.group(3).strip()
            name = m.group(4)
            if name == class_name:
                continue  # skip constructors
            params_raw = m.group(5).strip()
            params = ", ".join(p.strip().split()[-1] for p in params_raw.split(",") if p.strip()) if params_raw else ""
            methods.append(f"{ret} {name}({params})")

        # Build summary
        parts: list[str] = []
        if class_name:
            prefix = f"{pkg}." if pkg else ""
            parts.append(f"Class: {prefix}{class_name}")
        if annotations:
            parts.append(f"Annotations: {', '.join(annotations[:10])}")
        if methods:
            parts.append(f"Methods ({len(methods)}):")
            for mt in methods[:8]:
                parts.append(f"  {mt}")
            if len(methods) > 8:
                parts.append(f"  ...+{len(methods)-8} more")

        summary = "\n".join(parts) if parts else f"{len(text.splitlines())} lines, no class detected"
        summary += f"\n[Source: {self._rel(path)} | java | {size:,} bytes]"

        return ParsedFile(
            path=str(path), filename=path.name, file_type="java",
            size_bytes=size, summary=self._trim(summary),
            meta={
                "package": pkg, "class": class_name,
                "annotations": annotations, "methods": methods,
            },
        )

    # ------------------------------------------------------------------
    # Python
    # ------------------------------------------------------------------

    def _parse_python(self, path: Path, size: int) -> ParsedFile:
        text = path.read_text(encoding="utf-8", errors="replace")

        imports = re.findall(r"^(?:from\s+(\S+)\s+)?import\s+(.+)$", text, re.MULTILINE)
        imp_list = [f"from {m[0]} import {m[1]}" if m[0] else f"import {m[1]}" for m in imports]

        classes = re.findall(r"class\s+(\w+)", text)
        funcs = re.findall(r"def\s+(\w+)", text)
        decorators = re.findall(r"@(\w+)", text)
        decorators = list(set(decorators))

        parts: list[str] = []
        if classes:
            parts.append(f"Classes: {', '.join(classes[:10])}")
        if funcs:
            parts.append(f"Functions: {', '.join(funcs[:15])}" + (f" ...+{len(funcs)-15}" if len(funcs) > 15 else ""))
        if imp_list:
            parts.append(f"Imports ({len(imp_list)})")
        if decorators:
            parts.append(f"Decorators: {', '.join(decorators[:8])}")

        summary = " | ".join(parts) if parts else f"{len(text.splitlines())} lines"
        summary += f"\n[Source: {self._rel(path)} | python | {size:,} bytes]"

        return ParsedFile(
            path=str(path), filename=path.name, file_type="python",
            size_bytes=size, summary=self._trim(summary),
            meta={"classes": classes, "functions": funcs, "imports": imp_list},
        )

    # ------------------------------------------------------------------
    # Excel (xlsx)
    # ------------------------------------------------------------------

    def _parse_xlsx(self, path: Path, size: int) -> ParsedFile:
        try:
            with zipfile.ZipFile(path, "r") as z:
                # shared strings
                strings: list[str] = []
                if "xl/sharedStrings.xml" in z.namelist():
                    ss = ET.fromstring(z.read("xl/sharedStrings.xml"))
                    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
                    for si in ss.iter(f"{{{ns}}}si"):
                        parts_t: list[str] = []
                        for t in si.iter(f"{{{ns}}}t"):
                            if t.text:
                                parts_t.append(t.text)
                        strings.append("".join(parts_t))

                # first sheet only (for summary)
                sheet_name = "Sheet1"
                for n in z.namelist():
                    if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"):
                        sheet_name = n.split("/")[-1].replace(".xml", "")
                        ws = ET.fromstring(z.read(n))
                        ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

                        rows_data: list[list[str]] = []
                        for row in ws.iter(f"{{{ns}}}row"):
                            cells: list[str] = []
                            for c in row.iter(f"{{{ns}}}c"):
                                t = c.get("t", "")
                                v = None
                                for v_elem in c.iter(f"{{{ns}}}v"):
                                    v = v_elem.text
                                if v is not None:
                                    if t == "s":
                                        try:
                                            idx = int(v)
                                            cells.append(strings[idx] if 0 <= idx < len(strings) else v)
                                        except (ValueError, IndexError):
                                            cells.append(v)
                                    else:
                                        cells.append(v)
                            if cells:
                                rows_data.append(cells)

                        if not rows_data:
                            break

                        headers = rows_data[0] if rows_data else []
                        data_rows = rows_data[1:] if len(rows_data) > 1 else []
                        row_count = len(data_rows)
                        col_count = len(headers)

                        # Build summary
                        parts: list[str] = [f"Sheet: {sheet_name} | {row_count} rows x {col_count} cols"]

                        if headers:
                            cols_desc = ", ".join(
                                f"{h}({self._guess_dtype(h, data_rows, i)})"
                                for i, h in enumerate(headers[:12])
                            )
                            parts.append(f"Columns: [{cols_desc}]")

                        if data_rows:
                            sample = data_rows[:3]
                            for si, srow in enumerate(sample):
                                parts.append(f"Sample[{si+1}]: {', '.join(srow[:8])}")

                        summary = "\n".join(parts)
                        break  # first sheet only
                else:
                    summary = "[xlsx] No sheet data found."

        except Exception as e:
            summary = f"[xlsx] Parse error: {e}"

        summary += f"\n[Source: {self._rel(path)} | xlsx | {size:,} bytes]"
        return ParsedFile(
            path=str(path), filename=path.name, file_type="xlsx",
            size_bytes=size, summary=self._trim(summary),
        )

    # ------------------------------------------------------------------
    # CSV
    # ------------------------------------------------------------------

    def _parse_csv(self, path: Path, size: int) -> ParsedFile:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            # Sniff delimiter
            sample_text = text[:4096]
            sniffer = csv.Sniffer()
            try:
                dialect = sniffer.sniff(sample_text, delimiters=",;\t|")
                delimiter = dialect.delimiter
            except csv.Error:
                delimiter = ","

            reader = csv.reader(io.StringIO(text), delimiter=delimiter)
            rows = list(reader)
            headers = rows[0] if rows else []
            data_rows = rows[1:] if len(rows) > 1 else []

            parts: list[str] = [
                f"CSV: {len(data_rows)} rows x {len(headers)} cols",
                f"Headers: {', '.join(headers[:15])}" + (f" ...+{len(headers)-15}" if len(headers) > 15 else ""),
            ]
            if data_rows:
                for i in range(min(3, len(data_rows))):
                    parts.append(f"Sample[{i+1}]: {', '.join(data_rows[i][:8])}")

            summary = "\n".join(parts)
        except Exception as e:
            summary = f"[csv] Parse error: {e}"

        summary += f"\n[Source: {self._rel(path)} | csv | {size:,} bytes]"
        return ParsedFile(
            path=str(path), filename=path.name, file_type="csv",
            size_bytes=size, summary=self._trim(summary),
        )

    # ------------------------------------------------------------------
    # DOCX
    # ------------------------------------------------------------------

    def _parse_docx(self, path: Path, size: int) -> ParsedFile:
        try:
            with zipfile.ZipFile(path, "r") as z:
                if "word/document.xml" not in z.namelist():
                    summary = "[docx] No document.xml"
                else:
                    root = ET.fromstring(z.read("word/document.xml"))
                    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

                    # Extract heading structure
                    heading_sizes = {
                        f"{{{ns}}}Heading1": "H1",
                        f"{{{ns}}}Heading2": "H2",
                        f"{{{ns}}}Heading3": "H3",
                    }
                    headings: list[tuple[str, str]] = []

                    # Also count paragraphs and tables
                    para_count = 0
                    table_count = 0

                    for p in root.iter(f"{{{ns}}}p"):
                        style = None
                        text_parts: list[str] = []
                        for r in p.iter(f"{{{ns}}}r"):
                            for t in r.iter(f"{{{ns}}}t"):
                                if t.text:
                                    text_parts.append(t.text)
                        text = "".join(text_parts).strip()

                        # Check style
                        pPr = p.find(f"{{{ns}}}pPr")
                        if pPr is not None:
                            pStyle = pPr.find(f"{{{ns}}}pStyle")
                            if pStyle is not None:
                                style = pStyle.get(f"{{{ns}}}val", "")

                        if style in heading_sizes and text:
                            headings.append((heading_sizes[style], text[:80]))
                        elif text:
                            para_count += 1

                    for _tbl in root.iter(f"{{{ns}}}tbl"):
                        table_count += 1

                    # Build heading tree
                    parts: list[str] = []
                    if headings:
                        parts.append(f"Title/Headings ({len(headings)}):")
                        for htype, htext in headings[:15]:
                            indent = "  " if htype == "H2" else ("    " if htype == "H3" else "")
                            parts.append(f"{indent}{htype}: {htext}")
                    parts.append(f"Paragraphs: {para_count}")
                    if table_count:
                        parts.append(f"Tables: {table_count}")

                    summary = "\n".join(parts)
        except Exception as e:
            summary = f"[docx] Parse error: {e}"

        summary += f"\n[Source: {self._rel(path)} | docx | {size:,} bytes]"
        return ParsedFile(
            path=str(path), filename=path.name, file_type="docx",
            size_bytes=size, summary=self._trim(summary),
        )

    # ------------------------------------------------------------------
    # PPTX
    # ------------------------------------------------------------------

    def _parse_pptx(self, path: Path, size: int) -> ParsedFile:
        try:
            with zipfile.ZipFile(path, "r") as z:
                slide_names = sorted(
                    [n for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")],
                    key=lambda n: int(re.search(r"slide(\d+)", n).group(1)),
                )
                ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
                slides_summary: list[str] = []

                for i, name in enumerate(slide_names[:15], 1):
                    root = ET.fromstring(z.read(name))
                    texts: list[str] = []
                    for t in root.iter(f"{{{ns}}}t"):
                        if t.text:
                            texts.append(t.text)
                    line = "".join(texts).strip()
                    slides_summary.append(f"Slide {i}: {line[:100]}")

                summary = f"Slides: {len(slide_names)}\n" + "\n".join(slides_summary)
                if len(slide_names) > 15:
                    summary += f"\n... +{len(slide_names)-15} more slides"
        except Exception as e:
            summary = f"[pptx] Parse error: {e}"

        summary += f"\n[Source: {self._rel(path)} | pptx | {size:,} bytes]"
        return ParsedFile(
            path=str(path), filename=path.name, file_type="pptx",
            size_bytes=size, summary=self._trim(summary),
        )

    # ------------------------------------------------------------------
    # PDF (best-effort stdlib)
    # ------------------------------------------------------------------

    def _parse_pdf(self, path: Path, size: int) -> ParsedFile:
        try:
            data = path.read_bytes()
            text = data.decode("latin-1", errors="replace")

            # Count pages
            pages = len(re.findall(r"/Type\s*/Page[^s]", text))

            # Extract text blocks between BT/ET
            blocks: list[str] = []
            bt_pos = 0
            while True:
                bt_pos = text.find("\nBT\n", bt_pos)
                if bt_pos == -1:
                    bt_pos = text.find("\nBT\r", 0)
                    if bt_pos == -1:
                        break
                et_pos = text.find("\nET\n", bt_pos)
                if et_pos == -1:
                    et_pos = text.find("\nET\r", bt_pos)
                    if et_pos == -1:
                        break
                block = text[bt_pos:et_pos]
                bt_pos = et_pos + 1

                chars: list[str] = []
                i = 0
                while i < len(block):
                    if block[i] == "(":
                        depth = 1
                        j = i + 1
                        s: list[str] = []
                        while j < len(block) and depth > 0:
                            if block[j] == "\\" and j + 1 < len(block):
                                j += 1
                                s.append(block[j])
                            elif block[j] == "(":
                                depth += 1
                                s.append("(")
                            elif block[j] == ")":
                                depth -= 1
                                if depth > 0:
                                    s.append(")")
                            else:
                                s.append(block[j])
                            j += 1
                        chars.append("".join(s))
                        i = j
                    else:
                        i += 1

                line = "".join(chars).strip()
                if line and len(line) > 3:
                    blocks.append(line)

            # Title = first substantial text block
            title = ""
            for b in blocks:
                if len(b) > 10:
                    title = b[:120]
                    break

            parts: list[str] = []
            if title:
                parts.append(f"Title: {title}")
            parts.append(f"Pages: {pages or '?'}")
            if blocks:
                parts.append(f"Text blocks: {len(blocks)}")
                # Show a few substantive lines
                shown = 0
                for b in blocks:
                    if len(b) > 20 and shown < 5:
                        parts.append(f"  > {b[:100]}")
                        shown += 1

            summary = "\n".join(parts)
            if not blocks:
                summary += " [Note: streams may be compressed; use external PDF tool for full text]"
        except Exception as e:
            summary = f"[pdf] Parse error: {e}"

        summary += f"\n[Source: {self._rel(path)} | pdf | {size:,} bytes]"
        return ParsedFile(
            path=str(path), filename=path.name, file_type="pdf",
            size_bytes=size, summary=self._trim(summary),
        )

    # ------------------------------------------------------------------
    # Config (YAML / JSON / XML / INI)
    # ------------------------------------------------------------------

    def _parse_config(self, path: Path, size: int) -> ParsedFile:
        text = path.read_text(encoding="utf-8", errors="replace")
        ext = path.suffix.lower()

        parts: list[str] = [f"Config ({ext}) | {len(text.splitlines())} lines"]

        if ext in (".yaml", ".yml"):
            # Top-level keys
            keys = re.findall(r"^(\w[\w_-]*)\s*:", text, re.MULTILINE)
            if keys:
                parts.append(f"Top keys ({len(keys)}): {', '.join(keys[:15])}")
        elif ext == ".json":
            keys = re.findall(r'"([^"]+)"\s*:', text)
            if keys:
                parts.append(f"Top keys ({len(keys)}): {', '.join(keys[:15])}")
        elif ext == ".xml":
            tags = re.findall(r"<(\w+)", text)
            if tags:
                parts.append(f"Root tags: {', '.join(list(dict.fromkeys(tags))[:10])}")
        elif ext in (".ini", ".cfg", ".conf"):
            sections = re.findall(r"^\[(.+)\]", text, re.MULTILINE)
            if sections:
                parts.append(f"Sections: {', '.join(sections[:10])}")

        summary = " | ".join(parts)
        summary += f"\n[Source: {self._rel(path)} | config | {size:,} bytes]"
        return ParsedFile(
            path=str(path), filename=path.name, file_type="config",
            size_bytes=size, summary=self._trim(summary),
        )

    # ------------------------------------------------------------------
    # Generic text
    # ------------------------------------------------------------------

    def _parse_generic_text(self, path: Path, size: int) -> ParsedFile:
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.split("\n")

        # First non-empty line as title
        title = ""
        for line in lines:
            stripped = line.strip()
            if stripped:
                title = stripped[:100]
                break

        parts: list[str] = []
        if title:
            parts.append(f"First line: {title}")
        parts.append(f"{len(lines)} lines, {len(text)} chars")

        summary = " | ".join(parts)
        summary += f"\n[Source: {self._rel(path)} | text | {size:,} bytes]"
        return ParsedFile(
            path=str(path), filename=path.name, file_type="text",
            size_bytes=size, summary=self._trim(summary),
        )

    # ------------------------------------------------------------------
    # Image
    # ------------------------------------------------------------------

    def _parse_image(self, path: Path, size: int) -> ParsedFile:
        try:
            data = path.read_bytes()
            dims = self._image_dimensions(data)
            w, h = dims if dims else ("?", "?")
            fmt = path.suffix.lower().lstrip(".")
            summary = f"[{fmt.upper()}] {w}x{h}, {size:,} bytes"
        except Exception as e:
            summary = f"[image] Parse error: {e}"

        summary += f"\n[Source: {self._rel(path)} | image | {size:,} bytes]"
        return ParsedFile(
            path=str(path), filename=path.name, file_type="image",
            size_bytes=size, summary=self._trim(summary),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_type(path: Path) -> str:
        ext = path.suffix.lower()
        if ext in (".xlsx", ".docx", ".pptx", ".pdf"):
            return ext.lstrip(".")
        if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".ico", ".svg"):
            return "image"
        if ext in (".csv",):
            return "csv"
        if ext in (".yaml", ".yml", ".json", ".xml", ".ini", ".cfg", ".conf"):
            return ext.lstrip(".")
        if ext in (".sql", ".java", ".py", ".js", ".ts"):
            return ext.lstrip(".")
        return "text"

    @staticmethod
    def _rel(path: Path) -> str:
        """Relative path from cwd if possible."""
        try:
            return str(path.resolve().relative_to(Path.cwd()))
        except ValueError:
            return str(path)

    def _trim(self, text: str) -> str:
        if len(text) <= self.max_chars:
            return text
        return text[:self.max_chars - 20] + "\n[...truncated]"

    @staticmethod
    def _guess_dtype(header: str, rows: list[list[str]], col_idx: int) -> str:
        """Heuristic column type: str / int / decimal / date."""
        if not rows or col_idx >= len(rows[0]):
            return "str"
        samples = []
        for row in rows[:10]:
            if col_idx < len(row) and row[col_idx].strip():
                samples.append(row[col_idx].strip())
        if not samples:
            return "str"
        # All ints?
        if all(re.match(r"^-?\d+$", s) for s in samples):
            return "int"
        # All decimals?
        if all(re.match(r"^-?\d+\.?\d*$", s) for s in samples):
            return "decimal"
        # All dates?
        if all(re.match(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}", s) for s in samples):
            return "date"
        return "str"

    @staticmethod
    def _image_dimensions(data: bytes) -> tuple[int, int] | None:
        """Get image dimensions from raw bytes."""
        try:
            if data[:8] == b"\x89PNG\r\n\x1a\n":
                w, h = struct.unpack(">II", data[16:24])
                return w, h
            elif data[:2] == b"\xff\xd8":
                i = 2
                while i < len(data) - 9:
                    if data[i] == 0xFF and data[i + 1] in (0xC0, 0xC1, 0xC2):
                        h, w = struct.unpack(">HH", data[i + 5 : i + 9])
                        return w, h
                    i += 1
            elif data[:6] in (b"GIF87a", b"GIF89a"):
                w, h = struct.unpack("<HH", data[6:10])
                return w, h
            elif data[:2] == b"BM":
                w, h = struct.unpack("<II", data[18:26])
                return w, h
        except Exception:
            pass
        return None
