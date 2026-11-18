import base64, hashlib, hmac, os
from datetime import datetime, timedelta, timezone
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.core.config import settings

_bearer = HTTPBearer(auto_error=False)

def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000)
    return base64.b64encode(salt + dk).decode()

def verify_password(pw: str, stored: str) -> bool:
    raw = base64.b64decode(stored.encode())
    salt, dk = raw[:16], raw[16:]
    return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000), dk)

def create_token(user_id: str, role: str, name: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.TOKEN_MINUTES)
    return jwt.encode({"sub": user_id, "role": role, "name": name, "exp": exp}, settings.SECRET_KEY, algorithm="HS256")

def current_user(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    if cred is None:
        raise HTTPException(401, "Not authenticated")
    try:
        claims = jwt.decode(cred.credentials, settings.SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token")
    # The token proves WHO you are; WHAT you may do comes from the database on every request,
    # so deactivating a user or changing their role takes effect immediately (not when the 24h token expires).
    from app.core.database import SessionLocal
    from app.models.models import User
    db = SessionLocal()
    try:
        u = db.get(User, claims.get("sub"))
        if not u or not u.is_active: raise HTTPException(401, "This account is disabled or no longer exists")
        return {**claims, "role": u.role, "name": u.full_name, "client_id": u.client_id}
    finally:
        db.close()

def require_roles(*roles: str):
    def dep(user: dict = Depends(current_user)) -> dict:
        if user.get("role") not in roles and user.get("role") != "SUPER_ADMIN":
            raise HTTPException(403, f"Requires one of: {', '.join(roles)}")
        return user
    return dep
