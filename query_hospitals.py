import os
import sys

# Set DATABASE_URL if not set
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = "postgresql://user:password@localhost/claimsdb"

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'backend')))

from app.db.session import SessionLocal
from app.models import Hospital

db = SessionLocal()
hospitals = db.query(Hospital).all()
print(f"Total Hospitals: {len(hospitals)}")
for h in hospitals:
    print(f"- {h.hospital_code}: {h.hospital_name} (Status: {h.status})")
