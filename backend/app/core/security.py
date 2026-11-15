"""Supabase JWT verification for protected endpoints.

The Flutter app authenticates against Supabase Auth and sends its JWT as a
Bearer token. The backend verifies it with the project's JWT secret (HS256)
and returns the user identity. The AI key / JWT secret never leave the server.
"""

import jwt
from fastapi import Depends, Header, HTTPException

from app.core.config import settings


def verify_supabase_token(
    authorization: str | None = Header(default=None),
):
    if not settings.supabase_jwt_secret:
        raise HTTPException(status_code=503, detail="Auth not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
        )
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    uid = payload.get("sub")
    if not uid:
        raise HTTPException(status_code=401, detail="Token missing subject")
    return {"uid": uid, "email": payload.get("email", "")}


SupabaseUser = Depends(verify_supabase_token)


def optional_uid(authorization: str | None) -> str | None:
    """The caller's uid when the bearer token is valid, else None.

    Used by the AI quota: a signed-in user gets a personal allowance, a guest
    gets the smaller one. A bad or missing token is simply a guest — it must
    never turn an otherwise public route into a 401.
    """
    if not settings.supabase_jwt_secret or not authorization:
        return None
    if not authorization.lower().startswith("bearer "):
        return None
    token = authorization[7:].strip()
    try:
        payload = jwt.decode(token, settings.supabase_jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return payload.get("sub") or None
