
import unittest
import sys
import os

# Add vendor to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'vendor'))
from tool_layer import db_tools

class DBEngineMappingTests(unittest.TestCase):
    def test_gbase_maps_to_pymysql(self):
        self.assertEqual(db_tools._resolve_engine('gbase'), 'pymysql')
        self.assertEqual(db_tools._resolve_engine('GBase'), 'pymysql')
        self.assertEqual(db_tools._resolve_engine('gbase8a'), 'pymysql')

    def test_gcdw_now_maps_to_pymysql(self):
        self.assertEqual(db_tools._resolve_engine('gcdw'), 'pymysql',
                         'gcdw should map to pymysql as safety net')

    def test_gcdw_pg_still_maps_to_pg8000(self):
        self.assertEqual(db_tools._resolve_engine('gcdw-pg'), 'pg8000')

    def test_mysql_oracle_postgres_mappings(self):
        self.assertEqual(db_tools._resolve_engine('mysql'), 'pymysql')
        self.assertEqual(db_tools._resolve_engine('oracle'), 'oracledb')
        self.assertEqual(db_tools._resolve_engine('postgresql'), 'pg8000')

class DBEnsureImportsTests(unittest.TestCase):
    def setUp(self):
        db_tools._pymysql = None
        db_tools._oracledb = None
        db_tools._pg8000 = None
        db_tools._imports_tried = False

    def test_first_call_imports_all(self):
        self.assertFalse(db_tools._imports_tried)
        avail, miss = db_tools._ensure_imports()
        self.assertTrue(db_tools._imports_tried)
        self.assertIn('pymysql', avail or [])

    def test_recheck_when_driver_missing(self):
        # First call
        db_tools._ensure_imports()
        # Simulate: oracledb loaded, pymysql somehow None
        db_tools._pymysql = None
        avail, miss = db_tools._ensure_imports()
        # Should re-try and find pymysql in vendor
        self.assertIn('pymysql', avail,
                      f'pymysql should be re-found, got avail={avail}')

class DBConnectNoPg8000ErrorTests(unittest.TestCase):
    def setUp(self):
        db_tools._pymysql = None
        db_tools._oracledb = None
        db_tools._pg8000 = None
        db_tools._imports_tried = False
        db_tools._CONNECTIONS.clear()

    def test_gbase_connect_does_not_mention_pg8000(self):
        result = db_tools.db_connect('gbase', '127.0.0.1', 3306, 'x', 'x', 'x')
        self.assertNotIn('pg8000', result,
                         f'gbase should NOT trigger pg8000 error: {result}')

    def test_gcdw_connect_does_not_mention_pg8000(self):
        result = db_tools.db_connect('gcdw', '127.0.0.1', 3306, 'x', 'x', 'x')
        self.assertNotIn('pg8000', result,
                         f'gcdw should now use pymysql, not pg8000: {result}')

if __name__ == '__main__':
    unittest.main()
