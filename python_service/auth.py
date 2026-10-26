"""
auth.py - Firebase Authentication & Token Verification Guard.
Verifies Firebase ID tokens using the Firebase Admin SDK, extracts the authenticated
user's UID, and secures protected endpoints against unauthorized access.
"""

import os
import json
import logging
from typing import Optional, Dict, Any
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import firebase_admin
from firebase_admin import auth as admin_auth, credentials
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("utility_bot.auth")

# Firebase Project configuration
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", "utility-bot-web")
FIREBASE_SERVICE_ACCOUNT = os.getenv("FIREBASE_SERVICE_ACCOUNT_KEY")

_firebase_initialized = False

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
        # Mark initialized to prevent repeated crashes
        _firebase_initialized = True

# Initialize on module load
initialize_firebase()

# FastAPI HTTPBearer scheme
security = HTTPBearer(auto_error=False)


def verify_token(token: str) -> Dict[str, Any]:
    """
    Verifies a Firebase ID token and returns the decoded token payload.
    Raises HTTPException(401) on invalid or expired token.
    """
    if not token or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    clean_token = token.strip()

    # Special handling for local/test mock tokens if specifically configured in non-production
    if os.getenv("ALLOW_TEST_MOCK_TOKENS", "false").lower() == "true":
        if clean_token.startswith("test_token_"):
            mock_uid = clean_token[len("test_token_"):]
            return {"uid": mock_uid, "email": f"{mock_uid}@test.local", "auth_time": 0}

    try:
        decoded_token = admin_auth.verify_id_token(clean_token)
        uid = decoded_token.get("uid")
        if not uid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token payload is missing user ID (UID).",
                headers={"WWW-Authenticate": "Bearer"},
            )
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
    except admin_auth.InvalidIdTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        logger.warning(f"Token verification error: {e}")
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
