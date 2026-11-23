from sqlalchemy import inspect, text

from src.models.base import engine


# Columns added to tables that may already exist from the initial snapshot. create_all
# creates new tables but never alters old ones, so apply additive changes explicitly.
ADDED_COLUMNS = {
    'analysis_runs': {
        'kind': "VARCHAR(16) NOT NULL DEFAULT 'first'",
        'plan_id': 'INTEGER',
        'supplement_id': 'INTEGER',
    },
}


def upgrade(target=engine):
    inspector = inspect(target)
    tables = set(inspector.get_table_names())
    with target.begin() as db:
        for table, columns in ADDED_COLUMNS.items():
            if table not in tables:
                continue
            present = {column['name'] for column in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in present:
                    db.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))
