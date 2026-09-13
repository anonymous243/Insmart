import asyncio
from sqlalchemy import create_engine, MetaData
from app.config import settings

engine = create_engine(settings.DATABASE_URL)
metadata = MetaData()
metadata.reflect(bind=engine)

for table_name in ["claims"]:
    table = metadata.tables[table_name]
    print("Constraints:")
    for constraint in table.constraints:
        print(f"  {constraint}")
