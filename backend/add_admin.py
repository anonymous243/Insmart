import sys
sys.path.append('.')
from app.db.session import SessionLocal
from app.models.user import User
from app.core.security import get_password_hash
db = SessionLocal()
if not db.query(User).filter_by(email="admin@demo.com").first():
    db.add(User(email="admin@demo.com", password_hash=get_password_hash("test"), role="ADMIN"))
    db.commit()
    print("Admin created.")
