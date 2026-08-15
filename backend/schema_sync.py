"""Minimal, additive auto-migration.

`db.create_all()` only creates tables that don't exist yet — it never alters
an already-created table, so adding a new nullable column to a model (like
the provenance fields added for the disease-expansion import) silently does
nothing on a database that was created before that column existed.

This adds any model column that's missing from the live table via
`ALTER TABLE ... ADD COLUMN`. It only ever ADDs columns — never drops,
renames, or changes an existing one — which is all that's needed for the
purely-additive schema growth this project has had so far. It is not a
substitute for a real migration tool (Alembic) once an existing column
needs to change; see the README's Limitations section.
"""

import logging

from sqlalchemy import inspect, text

logger = logging.getLogger(__name__)


def sync_schema(db):
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())

    for mapper in db.Model.registry.mappers:
        table = mapper.local_table
        if table is None or table.name not in existing_tables:
            continue  # brand-new table — db.create_all() already handled it

        existing_columns = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing_columns:
                continue
            if not column.nullable:
                # Adding a NOT NULL column to a table with existing rows
                # needs a default/backfill strategy — deliberately out of
                # scope for this helper. Every column added so far is
                # nullable, so this should never actually trigger.
                logger.warning(
                    "Skipping non-nullable missing column %s.%s — needs a real migration",
                    table.name,
                    column.name,
                )
                continue

            ddl_type = column.type.compile(dialect=db.engine.dialect)
            with db.engine.begin() as conn:
                conn.execute(
                    text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {ddl_type}')
                )
            logger.info("schema_sync: added missing column %s.%s", table.name, column.name)
