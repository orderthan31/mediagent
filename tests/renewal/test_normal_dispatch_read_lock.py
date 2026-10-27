"""A read-only dispatch caller needs a row lock, not control-group UPDATE authority."""

from uuid import uuid4

from psycopg import sql
from test_execution import db as _db

db = _db


def test_normal_dispatch_reader_can_lock_but_cannot_mutate_control_groups(db):
    role = "dispatch_read_" + uuid4().hex[:12]
    with db.connection() as c:
        schema = c.execute("SELECT current_schema() s").fetchone()["s"]
        c.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(role)))
        c.execute(
            sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                sql.Identifier(schema), sql.Identifier(role)
            )
        )
        c.execute(
            sql.SQL("GRANT SELECT ON remote_control_groups TO {}").format(
                sql.Identifier(role)
            )
        )
        c.execute(
            sql.SQL(
                "GRANT EXECUTE ON FUNCTION managed_dispatch_group(text) TO {}"
            ).format(sql.Identifier(role))
        )
        c.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
        assert (
            c.execute("SELECT * FROM managed_dispatch_group('encode')").fetchall() == []
        )
        assert not c.execute(
            "SELECT has_any_column_privilege(current_user,'remote_control_groups','UPDATE') ok"
        ).fetchone()["ok"]
