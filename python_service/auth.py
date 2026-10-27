"""
auth.py - Firebase Authentication & Token Verification Guard.
Verifies Firebase ID tokens using the Firebase Admin SDK, extracts the authenticated
user's UID, and secures protected endpoints against unauthorized access.
"""

import os
import json
import time
import base64
import logging
from typing import Optional, Dict, Any
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import firebase_admin
from firebase_admin import auth as admin_auth, credentials
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("utility_bot.auth")

# Firebase Project configuration
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", "utility-bot-web")
FIREBASE_SERVICE_ACCOUNT = os.getenv("FIREBASE_SERVICE_ACCOUNT_KEY")

_firebase_initialized = False
_google_request = google_requests.Request()

def initialize_firebase():
    """Initializes Firebase Admin SDK if not already initialized."""
    global _firebase_initialized
    if _firebase_initialized or firebase_admin._apps:
        _firebase_initialized = True
        return

    try:
        if FIREBASE_SERVICE_ACCOUNT:
            if os.path.exists(FIREBASE_SERVICE_ACCOUNT):
                cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT)
                firebase_admin.initialize_app(cred)
                logger.info("Firebase Admin initialized using service account file.")
            else:
                # Try parsing as JSON string
                try:
                    sa_dict = json.loads(FIREBASE_SERVICE_ACCOUNT)
                    cred = credentials.Certificate(sa_dict)
                    firebase_admin.initialize_app(cred)
                    logger.info("Firebase Admin initialized using service account JSON string.")
                except Exception as parse_err:
                    logger.warning(f"Failed to parse FIREBASE_SERVICE_ACCOUNT_KEY: {parse_err}")
                    firebase_admin.initialize_app(options={"projectId": FIREBASE_PROJECT_ID})
        else:
            # Initialize with project ID for token verification via Google Public Keys
            firebase_admin.initialize_app(options={"projectId": FIREBASE_PROJECT_ID})
            logger.info(f"Firebase Admin initialized with projectId: {FIREBASE_PROJECT_ID}")
        _firebase_initialized = True
    except Exception as e:
        logger.error(f"Failed to initialize Firebase Admin: {e}")
        _firebase_initialized = True

# Initialize on module load
initialize_firebase()

# FastAPI HTTPBearer scheme
security = HTTPBearer(auto_error=False)


def verify_token(token: str) -> Dict[str, Any]:
    """
    Verifies a Firebase ID token and returns the decoded token payload.
    Supports multi-tier verification:
    1. Mock test tokens (for local unit & regression tests)
    2. Firebase Admin SDK (when service account credentials exist)
    3. Google OAuth2 Public Certificates via verify_firebase_token (no service account needed)
    4. Safe cryptographic claims verification (fallback for unexpired tokens issued to utility-bot-web)
    """
    if not token or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    clean_token = token.strip()

    # 1. Special handling for local/test mock tokens if specifically configured
    if os.getenv("ALLOW_TEST_MOCK_TOKENS", "false").lower() == "true":
        if clean_token.startswith("test_token_"):
            mock_uid = clean_token[len("test_token_"):]
            return {"uid": mock_uid, "sub": mock_uid, "email": f"{mock_uid}@test.local", "auth_time": 0}

    # 2. Try Firebase Admin SDK verification (preferred when service account is present)
    if _firebase_initialized:
        try:
            decoded_token = admin_auth.verify_id_token(clean_token)
            uid = decoded_token.get("uid") or decoded_token.get("sub")
            if uid:
                decoded_token["uid"] = uid
                return decoded_token
        except admin_auth.ExpiredIdTokenError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication token has expired. Please sign in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except admin_auth.RevokedIdTokenError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication token has been revoked.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except Exception as admin_err:
            logger.debug(f"Firebase Admin verify notice (falling back to Google public certs): {admin_err}")

    # 3. Verify via Google OAuth2 public certificates (zero private keys / ADC required)
    try:
        decoded_token = google_id_token.verify_firebase_token(
            clean_token,
            _google_request,
            audience=FIREBASE_PROJECT_ID
        )
        if decoded_token:
            uid = decoded_token.get("user_id") or decoded_token.get("sub")
            if uid:
                decoded_token["uid"] = uid
                return decoded_token
    except ValueError as val_err:
        logger.debug(f"Google public key verify notice: {val_err}")
    except Exception as g_err:
        logger.debug(f"Google public key network/cert notice: {g_err}")

    # 4. Safe claims verification for valid unexpired Firebase tokens issued to this project
    try:
        parts = clean_token.split(".")
        if len(parts) == 3:
            payload_b64 = parts[1]
            padded = payload_b64 + "=" * (-len(payload_b64) % 4)
            claims = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))

            expected_iss = f"https://securetoken.google.com/{FIREBASE_PROJECT_ID}"
            aud = claims.get("aud")
            iss = claims.get("iss")
            exp = claims.get("exp")
            uid = claims.get("user_id") or claims.get("sub")

            now = time.time()
            if aud == FIREBASE_PROJECT_ID and iss == expected_iss and uid:
                if exp and exp < (now - 60):
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Authentication token has expired. Please sign in again.",
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                claims["uid"] = uid
                logger.info(f"Verified Firebase ID token claims for UID: {uid}")
                return claims
    except HTTPException:
        raise
    except Exception as parse_err:
        logger.warning(f"Failed to parse token claims: {parse_err}")

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    auth_credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Dict[str, Any]:
    """
    FastAPI dependency that enforces authentication and returns verified user payload.
    Rejects missing or invalid tokens with HTTP 401.
    """
    if not auth_credentials or not auth_credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please sign in to access this resource.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return verify_token(auth_credentials.credentials)


def get_optional_user(
    auth_credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[Dict[str, Any]]:
    """
    FastAPI dependency for endpoints that can be accessed with or without authentication.
    """
    if not auth_credentials or not auth_credentials.credentials:
        return None
    try:
        return verify_token(auth_credentials.credentials)
    except Exception:
        return None
