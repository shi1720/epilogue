"""Firebase Authentication, exchanged for a secure same-origin session cookie."""
from __future__ import annotations

import os
import time
from datetime import timedelta

from fastapi import HTTPException, Request

from .storage import firebase_app


def hosted():
    return os.environ.get("EPILOGUE_AUTH_MODE") == "firebase"


def identity(request: Request):
    if not hosted():
        return {"uid": "local", "name": "Local workspace"}
    from firebase_admin import auth
    cookie = request.cookies.get("__session")
    if not cookie:
        raise HTTPException(401, "Sign in to open your private test workspace.")
    try:
        claims = auth.verify_session_cookie(cookie, check_revoked=True, app=firebase_app())
    except Exception as exc:
        raise HTTPException(401, "Your session has expired. Sign in again to continue.") from exc
    return {"uid": claims["uid"], "name": claims.get("name", "Tester"), "email": claims.get("email", "")}


def session_cookie(id_token):
    from firebase_admin import auth
    try:
        claims = auth.verify_id_token(id_token, app=firebase_app())
        if claims.get("firebase", {}).get("sign_in_provider") != "google.com" or not claims.get("email_verified"):
            raise ValueError("A verified Google account is required.")
        if time.time() - claims.get("auth_time", 0) > 300:
            raise ValueError("Sign in again to create a fresh session.")
        return auth.create_session_cookie(id_token, expires_in=timedelta(days=5), app=firebase_app())
    except Exception as exc:
        raise HTTPException(401, "Google sign-in could not be verified. Please try again.") from exc
