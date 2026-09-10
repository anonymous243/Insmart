import sys
sys.path.insert(0, '/home/amar/Desktop/Vietnam/backend')
from sqlalchemy import inspect
from app.db.session import engine

def check_constraints():
    inspector = inspect(engine)
    unique_constraints = inspector.get_unique_constraints("transactions")
    print("Transactions Unique Constraints:")
    for constraint in unique_constraints:
        print(f"Name: {constraint.get('name')}")
        print(f"Columns: {constraint.get('column_names')}")
        print("---")
    
    indexes = inspector.get_indexes("transactions")
    print("Transactions Indexes:")
    for index in indexes:
        print(f"Name: {index.get('name')}")
        print(f"Columns: {index.get('column_names')}")
        print(f"Unique: {index.get('unique')}")
        print("---")

check_constraints()
