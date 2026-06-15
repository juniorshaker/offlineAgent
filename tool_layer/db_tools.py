"""
tool_layer/db_tools.py
Database connection tools: list/dump stored procedures, query tables, run read-only SQL.

Supported databases:
  - MySQL / MariaDB     → pymysql (pure Python)
  - TDSQL              → pymysql (MySQL-compatible)
  - GBase 8a           → pymysql (MySQL-compatible)
  - Oracle 12c+        → oracledb (thin mode, pure Python)
  - GCDW              → pymysql or pg8000 (depending on variant)

Drivers should be placed in vendor/ by the user for zero-install deployment.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Optional driver imports
# ---------------------------------------------------------------------------

_pymysql = None
_oracledb = None
_pg8000 = None

# Active connections: {engine://user@host:port/db → connection}
_CONNECTIONS: dict = {}
_CURRENT_ENGINE: str = ""

# Track whether _try_imports() has been called
_imports_tried = False


def _try_imports(vendor_dir: Path | None = None):
    """Try to import DB drivers from vendor/ directory."""
    global _pymysql, _oracledb, _pg8000

    vendor_str = str(vendor_dir) if vendor_dir else str(Path(__file__).parent.parent / "vendor")
    sys_path = __import__("sys").path
    if vendor_str not in sys_path:
        sys_path.insert(0, vendor_str)

    # pymysql (for MySQL / TDSQL / GBase)
    try:
        import pymysql as _p
        _pymysql = _p
    except ImportError:
        pass

    # oracledb (for Oracle, thin mode = pure Python)
    try:
        import oracledb as _o
        _oracledb = _o
    except ImportError:
        pass

    # pg8000 (for GCDW PG variant)
    try:
        import pg8000 as _pg
        _pg8000 = _pg
    except ImportError:
        pass


def _conn_key(engine: str, host: str, port: int, database: str) -> str:
    return f"{engine}://{host}:{port}/{database}"


def _resolve_engine(engine: str) -> str:
    """Normalize engine name to driver type."""
    e = engine.lower().strip()
    if e in ("mysql", "mariadb", "tdsql", "gbase", "gbase8a", "gcdw", "gcdw-mysql"):
        return "pymysql"
    elif e in ("oracle", "oracledb"):
        return "oracledb"
    elif e in ("gcdw-pg", "pg", "postgresql", "postgres"):
        return "pg8000"
    else:
        return e


def _ensure_imports():
    """Lazy import check. Returns (available_drivers, missing_drivers)."""
    global _pymysql, _oracledb, _pg8000, _imports_tried

    # Re-attempt imports on first call or if any driver is still missing
    if not _imports_tried or (_pymysql is None or _oracledb is None or _pg8000 is None):
        _try_imports()
        _imports_tried = True

    available = []
    missing = []
    if _pymysql:
        available.append("pymysql")
    else:
        missing.append("pymysql (MySQL/TDSQL/GBase)")
    if _oracledb:
        available.append("oracledb")
    else:
        missing.append("oracledb (Oracle)")
    if _pg8000:
        available.append("pg8000")
    else:
        missing.append("pg8000 (PostgreSQL/GCDW-PG)")
    return available, missing


# ---------------------------------------------------------------------------
# Public tool functions
# ---------------------------------------------------------------------------

def db_connect(
    engine: str,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
) -> str:
    """Connect to a database and store the connection for subsequent operations.

    Args:
        engine: Database type (mysql/tdsql/gbase/oracle/gcdw/postgresql)
        host: Hostname or IP
        port: Port number
        user: Username
        password: Password
        database: Database/schema name

    Returns:
        Connection status message.
    """
    available, missing = _ensure_imports()
    driver = _resolve_engine(engine)

    if driver == "pymysql" and not _pymysql:
        return (
            f"[Error] pymysql driver not found.\n\n"
            f"Download: https://pypi.org/project/PyMySQL/\n"
            f"Extract the 'pymysql' folder into: vendor/pymysql/\n"
            f"Available drivers: {', '.join(available) if available else 'none'}\n"
            f"Missing drivers: {', '.join(missing)}"
        )
    if driver == "oracledb" and not _oracledb:
        return (
            f"[Error] oracledb driver not found.\n\n"
            f"Download: https://pypi.org/project/oracledb/\n"
            f"Extract the 'oracledb' folder into: vendor/oracledb/\n"
            f"Available drivers: {', '.join(available) if available else 'none'}\n"
            f"Missing drivers: {', '.join(missing)}"
        )
    if driver == "pg8000" and not _pg8000:
        return (
            f"[Error] pg8000 driver not found.\n\n"
            f"Download: https://pypi.org/project/pg8000/\n"
            f"Extract the 'pg8000' folder into: vendor/pg8000/\n"
            f"Available drivers: {', '.join(available) if available else 'none'}\n"
            f"Missing drivers: {', '.join(missing)}"
        )

    key = _conn_key(engine, host, port, database)

    try:
        if driver == "pymysql":
            conn = _pymysql.connect(
                host=host, port=port, user=user, password=password,
                database=database, charset="utf8mb4",
                connect_timeout=30, read_timeout=3600,
            )
        elif driver == "oracledb":
            conn = _oracledb.connect(
                user=user, password=password,
                host=host, port=port, service_name=database,
            )
        elif driver == "pg8000":
            conn = _pg8000.connect(
                host=host, port=port, user=user, password=password,
                database=database,
            )
        else:
            return f"[Error] Unsupported engine: {engine}"

        _CONNECTIONS[key] = conn
        global _CURRENT_ENGINE
        _CURRENT_ENGINE = driver

        # Get version
        cur = conn.cursor()
        if driver in ("pymysql",):
            cur.execute("SELECT VERSION()")
        elif driver == "oracledb":
            cur.execute("SELECT banner FROM v$version WHERE ROWNUM = 1")
        elif driver == "pg8000":
            cur.execute("SELECT version()")
        version = cur.fetchone()[0]
        cur.close()

        return (
            f"[OK] Connected to {engine} at {host}:{port}/{database}\n"
            f"Version: {version}\n"
            f"Driver: {driver}"
        )

    except Exception as ex:
        return f"[Error] Connection failed: {ex}"


def db_list_procedures(filter_name: str = "") -> str:
    """List all stored procedures in the current database.

    Args:
        filter_name: Optional name filter (LIKE pattern).

    Returns:
        List of procedure names, separated by engine.
    """
    driver = _CURRENT_ENGINE
    if not _CONNECTIONS:
        return "[Error] Not connected. Use db_connect first."

    conn = list(_CONNECTIONS.values())[-1]  # latest connection
    cur = conn.cursor()

    try:
        if driver in ("pymysql",):
            sql = "SELECT ROUTINE_NAME, ROUTINE_TYPE, CREATED FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = DATABASE()"
            if filter_name:
                sql += f" AND ROUTINE_NAME LIKE '%{filter_name}%'"
            sql += " ORDER BY ROUTINE_NAME"
        elif driver == "oracledb":
            sql = "SELECT OBJECT_NAME, OBJECT_TYPE, CREATED FROM user_objects WHERE OBJECT_TYPE = 'PROCEDURE'"
            if filter_name:
                sql += f" AND OBJECT_NAME LIKE '%{filter_name.upper()}%'"
            sql += " ORDER BY OBJECT_NAME"
        elif driver == "pg8000":
            sql = "SELECT proname, 'PROCEDURE' FROM pg_proc p JOIN pg_namespace n ON p.pronamespace = n.oid WHERE n.nspname = current_schema()"
            if filter_name:
                sql += f" AND proname LIKE '%{filter_name}%'"
            sql += " ORDER BY proname"
        else:
            return f"[Error] Unknown driver: {driver}"

        cur.execute(sql)
        rows = cur.fetchall()
        cur.close()

        if not rows:
            return f"[OK] No procedures found (filter: '{filter_name or 'all'}')."

        lines = [f"[OK] Found {len(rows)} procedures:"]
        for r in rows:
            name = r[0]
            ptype = r[1] if len(r) > 1 else "PROCEDURE"
            lines.append(f"  - {name} ({ptype})")
        return "\n".join(lines)

    except Exception as ex:
        cur.close()
        return f"[Error] Failed to list procedures: {ex}"


def db_get_procedure(name: str) -> str:
    """Get the full definition (CREATE statement) of a stored procedure.

    Args:
        name: Procedure name.

    Returns:
        Full CREATE PROCEDURE ... statement.
    """
    driver = _CURRENT_ENGINE
    if not _CONNECTIONS:
        return "[Error] Not connected. Use db_connect first."

    conn = list(_CONNECTIONS.values())[-1]
    cur = conn.cursor()

    try:
        if driver in ("pymysql",):
            cur.execute(f"SHOW CREATE PROCEDURE `{name}`")
            row = cur.fetchone()
            cur.close()
            if row:
                return f"-- Procedure: {row[0]}\n\n{row[2]}"
            return f"[Error] Procedure '{name}' not found."

        elif driver == "oracledb":
            cur.execute(
                "SELECT TEXT FROM user_source WHERE NAME = :n AND TYPE = 'PROCEDURE' ORDER BY LINE",
                {"n": name.upper()}
            )
            rows = cur.fetchall()
            cur.close()
            if rows:
                return f"-- Procedure: {name}\n\n" + "\n".join(r[0] for r in rows)
            return f"[Error] Procedure '{name}' not found."

        elif driver == "pg8000":
            cur.execute(
                "SELECT pg_get_functiondef(p.oid) FROM pg_proc p "
                "JOIN pg_namespace n ON p.pronamespace = n.oid "
                "WHERE proname = %s AND n.nspname = current_schema()",
                (name,)
            )
            row = cur.fetchone()
            cur.close()
            if row:
                return f"-- Procedure: {name}\n\n{row[0]}"
            return f"[Error] Procedure '{name}' not found."

        else:
            cur.close()
            return f"[Error] Unknown driver: {driver}"

    except Exception as ex:
        cur.close()
        return f"[Error] Failed to get procedure '{name}': {ex}"


def db_list_tables(filter_name: str = "") -> str:
    """List all tables/views in the current database.

    Args:
        filter_name: Optional name filter.

    Returns:
        List of table names.
    """
    driver = _CURRENT_ENGINE
    if not _CONNECTIONS:
        return "[Error] Not connected. Use db_connect first."

    conn = list(_CONNECTIONS.values())[-1]
    cur = conn.cursor()

    try:
        if driver in ("pymysql",):
            sql = "SELECT TABLE_NAME, TABLE_TYPE FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE()"
            if filter_name:
                sql += f" AND TABLE_NAME LIKE '%{filter_name}%'"
            sql += " ORDER BY TABLE_NAME"
        elif driver == "oracledb":
            sql = "SELECT TABLE_NAME, 'TABLE' FROM user_tables"
            if filter_name:
                sql += f" WHERE TABLE_NAME LIKE '%{filter_name.upper()}%'"
            sql += " UNION ALL SELECT VIEW_NAME, 'VIEW' FROM user_views"
            if filter_name:
                sql += f" WHERE VIEW_NAME LIKE '%{filter_name.upper()}%'"
            sql += " ORDER BY 1"
        elif driver == "pg8000":
            sql = (
                "SELECT tablename, 'TABLE' FROM pg_tables WHERE schemaname = current_schema()"
            )
            if filter_name:
                sql += f" AND tablename LIKE '%{filter_name}%'"
            sql += " ORDER BY tablename"
        else:
            return f"[Error] Unknown driver: {driver}"

        cur.execute(sql)
        rows = cur.fetchall()
        cur.close()

        if not rows:
            return f"[OK] No tables found (filter: '{filter_name or 'all'}')."

        lines = [f"[OK] Found {len(rows)} tables/views:"]
        for r in rows:
            lines.append(f"  - {r[0]} ({r[1]})")
        return "\n".join(lines)

    except Exception as ex:
        cur.close()
        return f"[Error] Failed to list tables: {ex}"


def db_query(sql: str, limit: int = 100) -> str:
    """Execute a read-only SQL query and return results.

    Only SELECT queries are allowed (safety: no INSERT/UPDATE/DELETE/DDL).

    Args:
        sql: SELECT query to execute.
        limit: Max rows to return.

    Returns:
        Query results as formatted text.
    """
    driver = _CURRENT_ENGINE
    if not _CONNECTIONS:
        return "[Error] Not connected. Use db_connect first."

    # Safety: block non-SELECT
    stripped = sql.strip().upper()
    if not stripped.startswith("SELECT") and not stripped.startswith("SHOW") and not stripped.startswith("DESCRIBE") and not stripped.startswith("EXPLAIN"):
        return "[Blocked] Only SELECT / SHOW / DESCRIBE / EXPLAIN queries are allowed for safety."

    # Add LIMIT if not present (for SELECT)
    if stripped.startswith("SELECT") and "LIMIT" not in stripped and "limit" not in sql:
        if driver in ("oracledb",):
            sql = f"SELECT * FROM ({sql}) WHERE ROWNUM <= {limit}"
        else:
            sql = f"{sql.rstrip(';').rstrip()} LIMIT {limit}"

    conn = list(_CONNECTIONS.values())[-1]
    cur = conn.cursor()

    try:
        cur.execute(sql)
        if cur.description:
            columns = [d[0] for d in cur.description]
            rows = cur.fetchmany(limit + 1)
            cur.close()

            # Format as table
            col_widths = [len(c) for c in columns]
            str_rows = []
            for row in rows:
                str_row = [str(v) if v is not None else "NULL" for v in row]
                str_rows.append(str_row)
                for i, val in enumerate(str_row):
                    col_widths[i] = max(col_widths[i], min(len(val), 60))

            # Header
            header_line = " | ".join(c.ljust(col_widths[i]) for i, c in enumerate(columns))
            sep_line = "-+-".join("-" * col_widths[i] for i in range(len(columns)))
            lines = [header_line, sep_line]

            for str_row in str_rows:
                truncated = [v[:60].ljust(col_widths[i]) for i, v in enumerate(str_row)]
                lines.append(" | ".join(truncated))

            lines.append(f"\n({min(len(rows), limit)} rows returned)")

            if len(rows) > limit:
                lines.append("[Truncated] More rows exist. Add WHERE clause to narrow results.")
            return "\n".join(lines)
        else:
            cur.close()
            return "[OK] Query executed (no result set)."

    except Exception as ex:
        cur.close()
        return f"[Error] Query failed: {ex}"


def db_disconnect() -> str:
    """Close all active database connections."""
    global _CONNECTIONS, _CURRENT_ENGINE
    errors = []
    count = 0
    for key, conn in list(_CONNECTIONS.items()):
        try:
            conn.close()
            count += 1
        except Exception as ex:
            errors.append(f"{key}: {ex}")
    _CONNECTIONS.clear()
    _CURRENT_ENGINE = ""
    msg = f"[OK] Closed {count} connection(s)."
    if errors:
        msg += f"\nErrors: {'; '.join(errors)}"
    return msg


def db_status() -> str:
    """Show current database connection status and available drivers."""
    available, missing = _ensure_imports()

    lines = ["[DB Status]"]
    lines.append(f"  Available drivers: {', '.join(available) if available else 'none'}")
    if missing:
        lines.append(f"  Missing drivers:  {', '.join(missing)}")
    if _CONNECTIONS:
        lines.append(f"  Active connections: {len(_CONNECTIONS)}")
        for key, conn in _CONNECTIONS.items():
            status = "open" if conn.open else "closed"
            lines.append(f"    {key} [{status}]")
    else:
        lines.append("  Active connections: 0")
    return "\n".join(lines)
