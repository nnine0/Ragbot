import os
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from datetime import datetime, timedelta
import uuid

security = HTTPBearer(auto_error=False)

JWT_SECRET = os.getenv("JWT_SECRET", "change-this-to-a-strong-secret")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))
DISABLE_AUTH = os.getenv("DISABLE_AUTH", "0") == "1"


def create_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def extract_user_id(request: Request) -> str:
    if DISABLE_AUTH:
        return "anonymous"

    token_header = request.headers.get("Authorization", "")

    if not token_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = token_header.removeprefix("Bearer ")

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token: missing subject")
        return user_id
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
