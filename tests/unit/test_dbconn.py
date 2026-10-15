"""The PostgreSQL adapter translates the stores' SQLite phrasing (src/dbconn.py)."""

from src.dbconn import _translate, connect, schema_for, using_postgres


def test_placeholders_and_or_ignore():
    assert _translate("INSERT OR IGNORE INTO gs1_keys VALUES (?,?)") == \
        "INSERT INTO gs1_keys VALUES (%s,%s) ON CONFLICT DO NOTHING"
    assert _translate("SELECT 1 WHERE a LIKE '5%'") == "SELECT 1 WHERE a LIKE '5%%'"


def test_schema_ddl():
    assert "SERIAL PRIMARY KEY" in _translate("id INTEGER PRIMARY KEY AUTOINCREMENT")
    assert "NOCASE" not in _translate("name TEXT NOT NULL COLLATE NOCASE")


def test_schema_names_follow_the_old_files():
    assert schema_for("var/adir_node_lk-1.sqlite") == "adir_node_lk_1"
    assert schema_for("var/adir_web.sqlite") == "adir_web"


def test_memory_and_no_url_stay_sqlite(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert not using_postgres("var/x.sqlite")
    monkeypatch.setenv("DATABASE_URL", "postgresql://example/db")
    assert not using_postgres(":memory:")
    conn = connect(":memory:")
    assert conn.execute("SELECT 1").fetchone() == (1,)
