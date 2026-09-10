from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config import settings

engine = create_engine(settings.DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """
    FastAPI dependency that yields a database session.
    Uses the module-level SessionLocal so that tests can patch engine/SessionLocal.
    """
    import app.db.session as _self
    db = _self.SessionLocal()
    try:
        yield db
    finally:
        db.close()
