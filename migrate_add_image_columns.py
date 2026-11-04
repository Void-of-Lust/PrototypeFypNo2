"""One-off migration for databases created before the image and food-price features.

db.create_all() creates missing tables but does not add columns to existing ones,
so run this once against an existing database:

    python migrate_add_image_columns.py

It is safe to run again; columns that already exist are skipped.
"""
from sqlalchemy import inspect, text
from app import create_app
from app.extensions import db

NEW_COLUMNS = [
    ('menu', 'gambar_minuman', 'VARCHAR(255)'),
    ('pelanggan', 'gambar_makanan', 'VARCHAR(255)'),
    ('pelanggan', 'harga_makanan', 'NUMERIC(10, 2) NOT NULL DEFAULT 0'),
    ('pelanggan', 'tarikh_masa', 'DATETIME'),
]

app = create_app()

with app.app_context():
    inspector = inspect(db.engine)
    for table, column, ddl in NEW_COLUMNS:
        existing = {col['name'] for col in inspector.get_columns(table)}
        if column in existing:
            print(f'skip   {table}.{column} (already exists)')
            continue
        db.session.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}'))
        print(f'added  {table}.{column}')
    db.session.commit()
    print('Done.')
