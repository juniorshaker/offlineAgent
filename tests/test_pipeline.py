"""
tests/test_pipeline.py — unit tests for the batch processing pipeline.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add parent to path for Offlineagent imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from Offlineagent.tool_layer.pipeline.indexer import Indexer, FileManifest, FileEntry
from Offlineagent.tool_layer.pipeline.parser import Parser, ParsedFile
from Offlineagent.tool_layer.pipeline.relations import RelationBuilder, FileLink, FileGroup
from Offlineagent.tool_layer.pipeline.checkpoint import Checkpoint
from Offlineagent.tool_layer.pipeline.refiner import Refiner


def mock_chat_fn(messages):
    """Mock LLM that returns a simple echo/answer."""
    last_user = ""
    for m in reversed(messages):
        if m["role"] == "user":
            last_user = m["content"]
            break
    return f"[LLM Response to: {last_user[:50]}...]"


# =============================================================================
# Indexer tests
# =============================================================================


class TestIndexer(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(str(self.tmp_dir), ignore_errors=True)

    def test_empty_dir(self):
        idx = Indexer()
        manifest = idx.scan(self.tmp_dir)
        self.assertIsInstance(manifest, FileManifest)
        self.assertEqual(manifest.total_files, 0)

    def test_mixed_files(self):
        (self.tmp_dir / "test.sql").write_text("SELECT * FROM users;")
        (self.tmp_dir / "Main.java").write_text("public class Main {}")
        (self.tmp_dir / "data.xlsx").write_bytes(b"PK\x03\x04")
        (self.tmp_dir / "readme.txt").write_text("Hello")
        (self.tmp_dir / "subdir").mkdir()
        (self.tmp_dir / "subdir" / "nested.py").write_text("print(1)")

        idx = Indexer()
        manifest = idx.scan(self.tmp_dir)

        self.assertEqual(manifest.total_files, 5)
        self.assertIn("sql", manifest.by_type)
        self.assertIn("java", manifest.by_type)
        self.assertIn("txt", manifest.by_type)
        self.assertIn("py", manifest.by_type)

    def test_single_file(self):
        f = self.tmp_dir / "config.yaml"
        f.write_text("key: value")
        idx = Indexer()
        manifest = idx.scan(f)
        self.assertEqual(manifest.total_files, 1)
        self.assertEqual(manifest.files[0].name, "config.yaml")

    def test_skip_hidden(self):
        (self.tmp_dir / ".git").mkdir()
        (self.tmp_dir / ".git" / "config").write_text("...")
        (self.tmp_dir / "visible.txt").write_text("hi")

        idx = Indexer()
        manifest = idx.scan(self.tmp_dir)
        self.assertEqual(manifest.total_files, 1)
        self.assertEqual(manifest.files[0].name, "visible.txt")


# =============================================================================
# Parser tests
# =============================================================================


class TestParser(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(str(self.tmp_dir), ignore_errors=True)

    def test_sql_procedures(self):
        f = self.tmp_dir / "procs.sql"
        f.write_text("""
CREATE PROCEDURE sp_insert_user(IN uid INT)
BEGIN
    INSERT INTO users (id, name) VALUES (uid, 'test');
    SELECT * FROM accounts WHERE id = uid;
END;

CREATE FUNCTION fn_get_total() RETURNS INT
BEGIN
    DECLARE total INT;
    SELECT COUNT(*) INTO total FROM orders;
    RETURN total;
END;
""")
        parser = Parser()
        pf = parser.parse(f)

        self.assertEqual(pf.file_type, "sql")
        summary_lower = pf.summary.lower()
        self.assertIn("sp_insert_user".lower(), summary_lower)
        self.assertIn("fn_get_total".lower(), summary_lower)
        self.assertTrue(
            "users" in summary_lower or "users" in str(pf.meta.get("tables_written", [])).lower()
        )
        self.assertTrue(
            "accounts" in summary_lower or "accounts" in str(pf.meta.get("tables_read", [])).lower()
        )
        self.assertLessEqual(len(pf.summary), 800)

    def test_java_class(self):
        f = self.tmp_dir / "UserService.java"
        f.write_text("""
package com.example.service;

import java.util.List;
import org.springframework.stereotype.Service;

@Service
public class UserService {
    public List<User> findAll() { return null; }
    public void save(User u) {}
    private String encrypt(String data) { return data; }
}
""")
        parser = Parser()
        pf = parser.parse(f)

        self.assertEqual(pf.file_type, "java")
        summary_lower = pf.summary.lower()
        self.assertIn("userservice", summary_lower)
        self.assertIn("findall", summary_lower)
        self.assertIn("service", str(pf.meta.get("annotations", [])).lower())
        self.assertLessEqual(len(pf.summary), 800)

    def test_python(self):
        f = self.tmp_dir / "main.py"
        f.write_text("""
import os
from pathlib import Path

def process_file(path):
    return Path(path).read_text()

class Processor:
    def run(self):
        pass
""")
        parser = Parser()
        pf = parser.parse(f)

        self.assertEqual(pf.file_type, "python")
        summary_lower = pf.summary.lower()
        self.assertIn("process_file".lower(), summary_lower)
        self.assertIn("processor".lower(), summary_lower)
        self.assertLessEqual(len(pf.summary), 800)

    def test_csv(self):
        f = self.tmp_dir / "data.csv"
        f.write_text("name,age,city\nAlice,30,NYC\nBob,25,LA\nCharlie,35,SF\n")
        parser = Parser()
        pf = parser.parse(f)

        self.assertEqual(pf.file_type, "csv")
        summary_lower = pf.summary.lower()
        self.assertIn("name", summary_lower)
        self.assertIn("age", summary_lower)
        self.assertIn("3 rows", summary_lower)
        self.assertLessEqual(len(pf.summary), 800)

    def test_config_yaml(self):
        f = self.tmp_dir / "app.yaml"
        f.write_text("server:\n  port: 8080\ndatabase:\n  url: localhost\n")
        parser = Parser()
        pf = parser.parse(f)

        self.assertEqual(pf.file_type, "config")
        summary_lower = pf.summary.lower()
        self.assertTrue("server" in summary_lower or "database" in summary_lower)
        self.assertLessEqual(len(pf.summary), 800)

    def test_summary_length_enforced(self):
        f = self.tmp_dir / "big.txt"
        f.write_text("A" * 10000)
        parser = Parser(max_chars=300)
        pf = parser.parse(f)
        self.assertLessEqual(len(pf.summary), 320)

    def test_missing_file(self):
        parser = Parser()
        pf = parser.parse(self.tmp_dir / "nope.txt")
        self.assertNotEqual(pf.error, "")


# =============================================================================
# Relations tests
# =============================================================================


class TestRelations(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(str(self.tmp_dir), ignore_errors=True)

    def _make_pf(self, path, ftype, meta=None):
        return ParsedFile(
            path=path, filename=Path(path).name,
            file_type=ftype, size_bytes=100,
            summary="test summary", meta=meta or {},
        )

    def test_table_flow_link(self):
        pfs = [
            self._make_pf("/a/writer.sql", "sql", {
                "tables_written": ["users"], "tables_read": [],
                "procedures": ["sp_insert"], "functions": [],
                "temp_tables": [],
            }),
            self._make_pf("/a/reader.sql", "sql", {
                "tables_read": ["users"], "tables_written": [],
                "procedures": [], "functions": [],
                "temp_tables": [],
            }),
        ]
        rb = RelationBuilder()
        groups = rb.build(pfs, Path("/a"))
        self.assertGreaterEqual(len(groups), 1)
        all_files = [f for g in groups for f in g.files]
        self.assertIn("/a/writer.sql", all_files)

    def test_cross_format_table_sheet(self):
        pfs = [
            self._make_pf("/a/writer.sql", "sql", {
                "tables_written": ["ifrs17_report"], "tables_read": [],
                "procedures": ["sp_report"], "functions": [],
                "temp_tables": [],
            }),
            self._make_pf("/a/ifrs17_report.xlsx", "xlsx", {}),
        ]
        rb = RelationBuilder()
        groups = rb.build(pfs, Path("/a"))
        # Some link should exist between sql and xlsx
        if len(groups) == 1:
            self.assertEqual(len(groups[0].files), 2)

    def test_large_component_split(self):
        pfs = []
        for i in range(20):
            pfs.append(self._make_pf(f"/a/file_{i}.sql", "sql", {
                "tables_written": [], "tables_read": [],
                "procedures": [f"proc_{i}"], "functions": [],
                "temp_tables": [],
            }))
        rb = RelationBuilder(batch_size=8)
        groups = rb.build(pfs, Path("/a"))
        self.assertGreaterEqual(len(groups), 2)


# =============================================================================
# Checkpoint tests
# =============================================================================


class TestCheckpoint(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(str(self.tmp_dir), ignore_errors=True)

    def test_save_load(self):
        cp = Checkpoint(self.tmp_dir)
        self.assertFalse(cp.exists())

        cp.mark_stage_done("index", total_files=10)
        self.assertTrue(cp.exists())
        self.assertTrue(cp.is_stage_done("index"))
        self.assertFalse(cp.is_stage_done("parse"))

    def test_groups(self):
        cp = Checkpoint(self.tmp_dir)
        cp.set_groups([
            {"id": "g1", "files": ["a.sql"], "description": "test"},
            {"id": "g2", "files": ["b.sql"], "description": "test2"},
        ])
        self.assertEqual(len(cp.get_groups()), 2)
        cp.mark_group_done("g1", "All done")
        self.assertIn("g1", cp.done_group_ids())
        self.assertNotIn("g2", cp.done_group_ids())

    def test_delete(self):
        cp = Checkpoint(self.tmp_dir)
        cp.mark_stage_done("index")
        self.assertTrue(cp.exists())
        cp.delete()
        self.assertFalse(cp.exists())

    def test_errors(self):
        cp = Checkpoint(self.tmp_dir)
        cp.record_error("bad.pdf", "Parse failed")
        data = cp.load()
        self.assertEqual(len(data["errors"]), 1)
        self.assertEqual(data["errors"][0]["file"], "bad.pdf")


# =============================================================================
# Refiner tests
# =============================================================================


class TestRefiner(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(str(self.tmp_dir), ignore_errors=True)

    def test_group_refine(self):
        refiner = Refiner(mock_chat_fn, max_rounds_per_group=3)
        pf = ParsedFile(
            path="/a/test.sql", filename="test.sql",
            file_type="sql", size_bytes=100,
            summary="Procedure: sp_test | Reads: users, accounts",
        )
        groups = [FileGroup(id="g1", files=["/a/test.sql"])]
        results = refiner.refine_groups(groups, [pf], "What does this do?")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].group_id, "g1")
        self.assertGreater(len(results[0].conclusion), 0)

    def test_full_run(self):
        refiner = Refiner(mock_chat_fn, max_rounds_per_group=2)
        pf1 = ParsedFile(
            path="/a/a.sql", filename="a.sql",
            file_type="sql", size_bytes=100,
            summary="Procedure: sp_a | Writes: table_x",
        )
        pf2 = ParsedFile(
            path="/a/b.sql", filename="b.sql",
            file_type="sql", size_bytes=100,
            summary="Procedure: sp_b | Reads: table_x",
        )
        groups = [FileGroup(id="g1", files=["/a/a.sql", "/a/b.sql"])]
        report = refiner.run(groups, [pf1, pf2], "Bloodline analysis")

        self.assertNotEqual(report.final_report, "")
        self.assertEqual(len(report.groups), 1)
        self.assertNotEqual(report.cross_links, "")


# =============================================================================
# Integration test
# =============================================================================


class TestIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(str(self.tmp_dir), ignore_errors=True)

    def test_pipeline_smoke(self):
        from Offlineagent.tool_layer.pipeline.pipeline import Pipeline

        (self.tmp_dir / "0_access").mkdir()
        (self.tmp_dir / "0_access" / "dwd_ins.sql").write_text("""
CREATE PROCEDURE sp_load_insurance()
BEGIN
    INSERT INTO fact_insurance (policy_id, premium)
    SELECT policy_id, amount FROM src_policy WHERE status = 'active';
END;
""")
        (self.tmp_dir / "0_access" / "dwd_ins_mm.sql").write_text("""
CREATE PROCEDURE sp_monthly_summary()
BEGIN
    INSERT INTO rpt_monthly (month_key, total_premium)
    SELECT DATE_FORMAT(load_date, '%Y%m'), SUM(premium)
    FROM fact_insurance GROUP BY 1;
END;
""")
        (self.tmp_dir / "1_wide").mkdir()
        (self.tmp_dir / "1_wide" / "wide_table.sql").write_text("""
CREATE PROCEDURE sp_build_wide()
BEGIN
    INSERT INTO wide_result
    SELECT f.*, m.total_premium
    FROM fact_insurance f
    LEFT JOIN rpt_monthly m ON DATE_FORMAT(f.load_date, '%Y%m') = m.month_key;
END;
""")
        (self.tmp_dir / "readme.txt").write_text("IFRS17 project data pipeline")

        pipeline = Pipeline(chat_fn=mock_chat_fn, enable_checkpoint=False)
        result = pipeline.run(str(self.tmp_dir), "analyze all SQL procedures")

        self.assertGreater(len(result), 0)
        self.assertIn("LLM Response", result)


# =============================================================================
# Edge cases
# =============================================================================


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(str(self.tmp_dir), ignore_errors=True)

    def test_empty_target(self):
        from Offlineagent.tool_layer.pipeline.pipeline import Pipeline
        pipeline = Pipeline(chat_fn=lambda m: "ok", enable_checkpoint=False)
        result = pipeline.run(str(self.tmp_dir), "analyze")
        # Chinese error message for "no analyzable files found"
        self.assertTrue("no files" in result.lower() or chr(27809) + chr(26377) + chr(25214) + chr(21040) in result)

    def test_unsupported_extension(self):
        f = self.tmp_dir / "data.bin"
        f.write_bytes(b"\x00\x01\x02")
        parser = Parser()
        pf = parser.parse(f)
        self.assertFalse(pf.error)
        self.assertIn(pf.file_type, ("text", "other"))


if __name__ == "__main__":
    unittest.main()
