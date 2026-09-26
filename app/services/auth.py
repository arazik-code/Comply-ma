"""
Authentication service — session-based with bcrypt password hashing.

Stocke dans la session FastAPI :
  user_id, company_id, role, display_name
"""
from typing import Optional

from fastapi import Request, HTTPException, status
from passlib.context import CryptContext
from sqlmodel import Session, select

from app.models.user import User
from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def authenticate_user(session: Session, username: str, password: str) -> Optional[User]:
    user = session.exec(select(User).where(User.username == username)).first()
    if user and verify_password(password, user.hashed_password):
        return user
    return None


def login_user(request: Request, user: User):
    request.session["user_id"] = user.id
    request.session["company_id"] = user.company_id
    request.session["role"] = user.role
    request.session["display_name"] = user.display_name


def logout_user(request: Request):
    for key in ["user_id", "company_id", "role", "display_name"]:
        request.session.pop(key, None)


def get_current_user(request: Request) -> Optional[dict]:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return {
        "id": user_id,
        "company_id": request.session.get("company_id"),
        "role": request.session.get("role"),
        "display_name": request.session.get("display_name"),
    }


def require_auth(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"location": "/login"})
    return user


def require_owner(request: Request):
    user = require_auth(request)
    if user["role"] != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès réservé au propriétaire")
    return user
