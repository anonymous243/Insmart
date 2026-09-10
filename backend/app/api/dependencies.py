from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.config import settings
from app.core.security import ALGORITHM
from app.models.user import User, FacilityUser

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise credentials_exception

    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        raise credentials_exception
    if user.status != "ACTIVE":
        raise HTTPException(status_code=403, detail="Inactive user")
    return user

def get_current_facility_user(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> FacilityUser:
    if current_user.role != "FACILITY_USER":
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    fac_user = db.query(FacilityUser).filter(FacilityUser.user_id == current_user.id).first()
    if not fac_user:
        raise HTTPException(status_code=403, detail="User is not associated with a facility")
    
    return fac_user

def get_current_admin_user(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return current_user
