from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..auth import verify_password
from ..database import get_db
from ..models import AdminUser
from ..security import csrf_token, require_csrf
from ..schemas import LoginRequest


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    user = db.get(AdminUser, payload.username)
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Username atau password salah")
    request.session.clear()
    request.session["admin_username"] = user.username
    token = csrf_token(request)
    return {"status": "authenticated", "username": user.username, "csrf_token": token}


@router.post("/logout")
def logout(request: Request) -> dict[str, str]:
    require_csrf(request)
    request.session.clear()
    return {"status": "logged_out"}
