import asyncio
from sqlalchemy import create_engine, MetaData
from app.config import settings

engine = create_engine(settings.DATABASE_URL)
metadata = MetaData()
metadata.reflect(bind=engine)

for table_name in ["claims", "claim_items", "coverage_rules"]:
    print(f"\n--- Table: {table_name} ---")
    if table_name in metadata.tables:
        table = metadata.tables[table_name]
        for column in table.columns:
            print(f"{column.name}: {column.type} (nullable={column.nullable}, unique={column.unique})")
        print("Indexes:")
        for index in table.indexes:
            print(f"  {index.name}: {[c.name for c in index.columns]} (unique={index.unique})")
    else:
        print("Not found")
